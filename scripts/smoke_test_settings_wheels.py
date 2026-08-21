"""Smoke-test installed suite settings against the exact qualified composition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    verify_artifact_directory,
)
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
)


class SettingsWheelSmokeError(RuntimeError):
    """Raised when installed suite-settings acceptance fails."""


@dataclass(frozen=True, slots=True)
class ApplicationExpectation:
    """One exact launchable application from the active suite manifest."""

    component_id: str
    display_name: str
    wheel: str


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    timeout: float = 180.0,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=dict(env),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SettingsWheelSmokeError(
            f"Command could not complete: {' '.join(command)}: {error}"
        ) from error
    if result.returncode != expected_returncode:
        raise SettingsWheelSmokeError(
            "Command returned an unexpected status "
            f"({result.returncode}, expected {expected_returncode}): "
            f"{' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _scripts_directory(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> Path:
    result = _run(
        [
            str(python),
            "-c",
            "import sysconfig; print(sysconfig.get_path('scripts'))",
        ],
        cwd=cwd,
        env=env,
    )
    return Path(result.stdout.strip())


def _expectations() -> tuple[ApplicationExpectation, ...]:
    manifest = load_release_compatibility_manifest()
    applications = tuple(
        ApplicationExpectation(
            component_id=component.component_id,
            display_name=component.display_name,
            wheel=component.release.wheel,
        )
        for component in manifest.components
        if "launchable_application" in component.capabilities
    )
    if len(applications) < 2:
        raise SettingsWheelSmokeError(
            "Settings acceptance requires at least two qualified applications."
        )
    return applications


def _component_wheels(
    artifact_dir: Path,
    applications: Sequence[ApplicationExpectation],
) -> tuple[Path, tuple[Path, ...]]:
    manifest = load_release_compatibility_manifest()
    core_rows = tuple(
        component
        for component in manifest.components
        if component.component_id == "core"
    )
    if len(core_rows) != 1:
        raise SettingsWheelSmokeError(
            "Compatibility manifest must declare exactly one Core component."
        )
    core_wheel = artifact_dir / core_rows[0].release.wheel
    application_wheels = tuple(
        artifact_dir / application.wheel for application in applications
    )
    missing = tuple(
        path for path in (core_wheel, *application_wheels) if not path.is_file()
    )
    if missing:
        raise SettingsWheelSmokeError(
            "Verified component artifact is missing: "
            + ", ".join(str(path) for path in missing)
        )
    return core_wheel, application_wheels


def _isolated_command_env(
    base_env: Mapping[str, str],
    *,
    user_home: Path,
) -> dict[str, str]:
    env = dict(base_env)
    for key in tuple(env):
        if key.upper() in {"PYTHONPATH", "PDS_WORKSPACE_ROOT"}:
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["HOME"] = str(user_home)
    env["USERPROFILE"] = str(user_home)
    env["LOCALAPPDATA"] = str(user_home / "AppData" / "Local")
    env["APPDATA"] = str(user_home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(user_home / ".config")
    return env


def _assert_installed_suite_location(
    python: Path,
    *,
    environment: Path,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    result = _run(
        [
            str(python),
            "-c",
            (
                "from pathlib import Path; import paper_data_suite; "
                "print(Path(paper_data_suite.__file__).resolve())"
            ),
        ],
        cwd=cwd,
        env=env,
    )
    installed = Path(result.stdout.strip()).resolve()
    try:
        installed.relative_to(environment.resolve())
    except ValueError as error:
        raise SettingsWheelSmokeError(
            "Smoke test imported paper_data_suite outside the isolated environment: "
            f"{installed}"
        ) from error


def _settings_path(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> Path:
    result = _run(
        [
            str(python),
            "-c",
            (
                "from paper_data_suite.settings import suite_settings_path; "
                "print(suite_settings_path())"
            ),
        ],
        cwd=cwd,
        env=env,
    )
    return Path(result.stdout.strip())


def _snapshot_tree(root: Path) -> tuple[tuple[str, int, str], ...]:
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SettingsWheelSmokeError(
                f"Synthetic workspace unexpectedly contains a symlink: {path}"
            )
        if not path.is_file():
            continue
        data = path.read_bytes()
        rows.append(
            (
                path.relative_to(root).as_posix(),
                len(data),
                hashlib.sha256(data).hexdigest(),
            )
        )
    return tuple(rows)


def _read_settings(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SettingsWheelSmokeError(
            "Installed settings document could not be independently read."
        ) from error
    if not isinstance(raw, dict):
        raise SettingsWheelSmokeError("Installed settings document is not an object.")
    return cast(dict[str, object], raw)


def _assert_safe_document(path: Path) -> dict[str, object]:
    data = _read_settings(path)
    if set(data) != {"record_type", "schema_version", "recent_components"}:
        raise SettingsWheelSmokeError(
            "Installed settings document contains unexpected fields."
        )
    if data.get("record_type") != "paper_data_suite_settings":
        raise SettingsWheelSmokeError("Installed settings record_type is incorrect.")
    if data.get("schema_version") != "1":
        raise SettingsWheelSmokeError("Installed settings schema_version is incorrect.")
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    forbidden = (
        "student_id",
        "answers",
        "score",
        "writing",
        "feedback",
        "teacher_note",
        "raw_scan",
        "grouping_band",
        "portfolio_candidate",
        "behavior_narrative",
        "workspace_root",
        "selected_workspace",
        "active_workspace",
    )
    leaked = tuple(fragment for fragment in forbidden if fragment in serialized)
    if leaked:
        raise SettingsWheelSmokeError(
            "Installed settings document contains prohibited state: "
            + ", ".join(leaked)
        )
    return data


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        raise SettingsWheelSmokeError(
            "Settings smoke created working-directory artifacts: "
            + ", ".join(item.name for item in contents)
        )


def smoke_test_settings_wheels(suite_wheel: Path, artifact_dir: Path) -> None:
    """Exercise settings through installed module and console entry points."""
    suite_wheel = suite_wheel.resolve()
    artifact_dir = artifact_dir.resolve()
    if not suite_wheel.is_file():
        raise SettingsWheelSmokeError(f"Suite wheel does not exist: {suite_wheel}")
    if not artifact_dir.is_dir():
        raise SettingsWheelSmokeError(
            f"Artifact directory does not exist: {artifact_dir}"
        )

    try:
        verify_artifact_directory(artifact_dir)
        applications = _expectations()
        core_wheel, application_wheels = _component_wheels(
            artifact_dir,
            applications,
        )
    except (
        ArtifactVerificationError,
        CompatibilityManifestError,
        OSError,
    ) as error:
        raise SettingsWheelSmokeError(
            f"Qualified component artifact verification failed: {error}"
        ) from error

    with tempfile.TemporaryDirectory(prefix="pds-settings-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        user_home = temp_root / "user"
        workspace = temp_root / "workspace"
        missing_workspace = temp_root / "missing-workspace"
        run_directory.mkdir()
        user_home.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _venv_python(environment)
        install_env = dict(os.environ)
        install_env["PYTHONDONTWRITEBYTECODE"] = "1"
        install_env["PYTHONNOUSERSITE"] = "1"
        install_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        install_env.pop("PYTHONPATH", None)
        install_env.pop("PIP_NO_INDEX", None)

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-input",
                str(core_wheel),
                str(suite_wheel),
                *(str(path) for path in application_wheels),
            ],
            cwd=run_directory,
            env=install_env,
            timeout=300.0,
        )
        _run(
            [str(python), "-m", "pip", "check"],
            cwd=run_directory,
            env=install_env,
        )
        _assert_clean_directory(run_directory)
        install_env = _isolated_command_env(
            install_env,
            user_home=user_home,
        )
        _assert_installed_suite_location(
            python,
            environment=environment,
            cwd=run_directory,
            env=install_env,
        )

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=install_env,
        )
        launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not launcher.is_file():
            raise SettingsWheelSmokeError(
                f"Installed pds launcher does not exist: {launcher}"
            )

        settings_path = _settings_path(
            python,
            cwd=run_directory,
            env=install_env,
        )
        if settings_path.exists():
            raise SettingsWheelSmokeError(
                "Resolving the installed settings path created the settings file."
            )

        _run(
            [str(python), "-c", "import paper_data_suite.settings"],
            cwd=run_directory,
            env=install_env,
        )
        _run(
            [str(launcher), "settings", "--help"],
            cwd=run_directory,
            env=install_env,
        )
        first_show = _run(
            [str(python), "-m", "paper_data_suite", "settings", "show"],
            cwd=run_directory,
            env=install_env,
        )
        if "Recent components:\n  None" not in first_show.stdout:
            raise SettingsWheelSmokeError(
                "First-run installed settings show did not report empty recency."
            )
        if settings_path.exists():
            raise SettingsWheelSmokeError(
                "Import/help/read-only first-run settings access created the file."
            )

        launch_env = dict(install_env)
        launch_env["PDS_WORKSPACE_ROOT"] = str(missing_workspace)
        first = applications[0]
        second = applications[1]
        _run(
            [str(launcher), "launch", first.component_id],
            cwd=run_directory,
            env=launch_env,
            input_text="q\n",
            timeout=60.0,
        )
        first_data = _assert_safe_document(settings_path)
        if first_data.get("recent_components") != [first.component_id]:
            raise SettingsWheelSmokeError(
                "First successful installed launch did not record exact component ID."
            )

        _run(
            [str(launcher), "launch", second.component_id],
            cwd=run_directory,
            env=launch_env,
            input_text="q\n",
            timeout=60.0,
        )
        second_data = _assert_safe_document(settings_path)
        if second_data.get("recent_components") != [
            second.component_id,
            first.component_id,
        ]:
            raise SettingsWheelSmokeError(
                "Installed settings MRU ordering is not deterministic."
            )

        shown = _run(
            [str(launcher), "settings", "show"],
            cwd=run_directory,
            env=install_env,
        )
        if (
            first.display_name not in shown.stdout
            or second.display_name not in shown.stdout
        ):
            raise SettingsWheelSmokeError(
                "Installed settings show did not re-resolve recent applications."
            )
        if "Managed by PDS Core" not in shown.stdout:
            raise SettingsWheelSmokeError(
                "Installed settings show omitted the Core workspace authority boundary."
            )

        _run(
            [str(launcher), "workspace", "set", str(workspace)],
            cwd=run_directory,
            env=install_env,
        )
        workspace_before = _snapshot_tree(workspace)
        workspace_show_before = _run(
            [str(launcher), "workspace", "show"],
            cwd=run_directory,
            env=install_env,
        ).stdout

        _run(
            [str(launcher), "settings", "clear-recent"],
            cwd=run_directory,
            env=install_env,
        )
        cleared = _assert_safe_document(settings_path)
        if cleared.get("recent_components") != []:
            raise SettingsWheelSmokeError(
                "Installed clear-recent did not clear only recent context."
            )
        if _snapshot_tree(workspace) != workspace_before:
            raise SettingsWheelSmokeError(
                "settings clear-recent modified canonical workspace bytes."
            )
        if (
            _run(
                [str(launcher), "workspace", "show"],
                cwd=run_directory,
                env=install_env,
            ).stdout
            != workspace_show_before
        ):
            raise SettingsWheelSmokeError(
                "settings clear-recent changed Core workspace selection."
            )

        _run(
            [str(python), "-m", "paper_data_suite", "settings", "reset"],
            cwd=run_directory,
            env=install_env,
        )
        reset = _assert_safe_document(settings_path)
        if reset.get("recent_components") != []:
            raise SettingsWheelSmokeError(
                "Installed settings reset did not restore schema-v1 defaults."
            )
        if _snapshot_tree(workspace) != workspace_before:
            raise SettingsWheelSmokeError(
                "settings reset modified canonical workspace bytes."
            )
        if (
            _run(
                [str(launcher), "workspace", "show"],
                cwd=run_directory,
                env=install_env,
            ).stdout
            != workspace_show_before
        ):
            raise SettingsWheelSmokeError(
                "settings reset changed Core workspace selection."
            )

        try:
            settings_path.relative_to(workspace)
        except ValueError:
            pass
        else:
            raise SettingsWheelSmokeError(
                "Suite settings were stored inside the canonical workspace."
            )
        _assert_clean_directory(run_directory)


def build_parser() -> argparse.ArgumentParser:
    """Build the installed settings smoke-test parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built suite wheel with the exact verified qualified "
            "composition and exercise privacy-minimized suite settings."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument(
        "--artifact-dir",
        required=True,
        type=Path,
        help="verified directory containing exact qualified Core/application wheels",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run installed suite-settings acceptance."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test_settings_wheels(arguments.suite_wheel, arguments.artifact_dir)
    except SettingsWheelSmokeError as error:
        print(f"Settings wheel smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Settings wheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
