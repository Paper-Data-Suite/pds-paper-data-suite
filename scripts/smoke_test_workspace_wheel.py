"""Smoke-test installed workspace workflows from the built suite wheel."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast


class WorkspaceSmokeTestError(RuntimeError):
    """Raised when installed workspace acceptance fails."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != expected_returncode:
        raise WorkspaceSmokeTestError(
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
    env["PIP_NO_INDEX"] = "1"
    env["HOME"] = str(user_home)
    env["USERPROFILE"] = str(user_home)
    env["APPDATA"] = str(user_home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(user_home / ".config")
    return env


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        names = ", ".join(item.name for item in contents)
        raise WorkspaceSmokeTestError(
            "Workspace smoke command created working-directory artifacts: " + names
        )


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
    installed_path = Path(result.stdout.strip()).resolve()
    try:
        installed_path.relative_to(environment.resolve())
    except ValueError as error:
        raise WorkspaceSmokeTestError(
            "Smoke test imported paper_data_suite outside the isolated environment: "
            f"{installed_path}"
        ) from error


def _core_workspace_status(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> dict[str, object]:
    code = """
import json
from pds_core.workspace import inspect_workspace_root

status = inspect_workspace_root()
print(json.dumps({
    "root": str(status.root),
    "source": status.source,
    "exists": status.exists,
    "is_dir": status.is_dir,
    "is_writable": status.is_writable,
}))
""".strip()
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise WorkspaceSmokeTestError("Core workspace status was not a JSON object.")
    return cast(dict[str, object], payload)


def _assert_show_output(
    output: str,
    *,
    root: Path,
    source_label: str,
) -> None:
    required = (
        "Paper Data Suite workspace",
        str(root),
        source_label,
        "Core configuration:",
        "Core default workspace:",
    )
    missing = [fragment for fragment in required if fragment not in output]
    if missing:
        raise WorkspaceSmokeTestError(
            "Workspace show output is missing expected content: "
            + ", ".join(missing)
        )


def _assert_workspace_initialized(root: Path) -> None:
    required = (
        root / ".pds",
        root / "classes",
        root / "scans_inbox",
        root / "scans",
        root / "scans" / "source",
        root / "scans" / "review",
    )
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise WorkspaceSmokeTestError(
            "Core workspace initialization is missing expected directories: "
            + ", ".join(missing)
        )


def _assert_status(
    payload: Mapping[str, object],
    *,
    root: Path,
    source: str,
    exists: bool,
) -> None:
    if payload.get("root") != str(root.resolve()):
        raise WorkspaceSmokeTestError(
            f"Core resolved unexpected workspace root: {payload.get('root')!r}"
        )
    if payload.get("source") != source:
        raise WorkspaceSmokeTestError(
            f"Core reported unexpected workspace source: {payload.get('source')!r}"
        )
    if payload.get("exists") is not exists:
        raise WorkspaceSmokeTestError(
            f"Core reported unexpected workspace existence: {payload.get('exists')!r}"
        )


def smoke_test_workspace_wheel(suite_wheel: Path, core_wheel: Path) -> None:
    """Exercise installed workspace setup beside only the exact Core wheel."""
    suite_wheel = suite_wheel.resolve()
    core_wheel = core_wheel.resolve()
    if not suite_wheel.is_file():
        raise WorkspaceSmokeTestError(f"Suite wheel does not exist: {suite_wheel}")
    if not core_wheel.is_file():
        raise WorkspaceSmokeTestError(f"Core wheel does not exist: {core_wheel}")

    with tempfile.TemporaryDirectory(prefix="pds-workspace-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        user_home = temp_root / "user"
        selected_workspace = temp_root / "selected-workspace"
        blocked_workspace = temp_root / "blocked-workspace"
        environment_workspace = temp_root / "environment-workspace"
        run_directory.mkdir()
        user_home.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _venv_python(environment)
        command_env = _isolated_command_env(os.environ, user_home=user_home)

        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(core_wheel)],
            cwd=run_directory,
            env=command_env,
        )
        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(suite_wheel)],
            cwd=run_directory,
            env=command_env,
        )
        _run(
            [str(python), "-m", "pip", "check"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_installed_suite_location(
            python,
            environment=environment,
            cwd=run_directory,
            env=command_env,
        )

        default_root = (user_home / "Paper Data Suite").resolve()
        initial = _run(
            [str(python), "-m", "paper_data_suite", "workspace", "show"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_show_output(
            initial.stdout,
            root=default_root,
            source_label="Core default location",
        )
        if default_root.exists():
            raise WorkspaceSmokeTestError("Workspace show created the default root.")

        validation = _run(
            [
                str(python),
                "-m",
                "paper_data_suite",
                "workspace",
                "validate",
                str(selected_workspace),
            ],
            cwd=run_directory,
            env=command_env,
            expected_returncode=1,
        )
        if "does not exist" not in f"{validation.stdout}\n{validation.stderr}".lower():
            raise WorkspaceSmokeTestError(
                "Validate-only failure did not explain the missing workspace."
            )
        if selected_workspace.exists():
            raise WorkspaceSmokeTestError(
                "Validate-only command created the missing workspace."
            )

        guided_input = f"2\n{selected_workspace}\nUSE\n"
        guided = _run(
            [str(python), "-m", "paper_data_suite", "workspace", "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=guided_input,
        )
        guided_required = (
            "Workspace candidate",
            "This folder does not exist yet.",
            "Workspace ready",
            "saved workspace selection",
            "No school year or classroom setup was changed.",
            "Next: pds doctor",
        )
        missing_guided = [
            fragment for fragment in guided_required if fragment not in guided.stdout
        ]
        if missing_guided:
            raise WorkspaceSmokeTestError(
                "Guided installed workspace setup is missing expected output: "
                + ", ".join(missing_guided)
            )
        _assert_workspace_initialized(selected_workspace)
        _assert_status(
            _core_workspace_status(
                python,
                cwd=run_directory,
                env=command_env,
            ),
            root=selected_workspace,
            source="saved_config",
            exists=True,
        )

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=command_env,
        )
        launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not launcher.is_file():
            raise WorkspaceSmokeTestError(
                f"Installed pds launcher does not exist: {launcher}"
            )

        console_show = _run(
            [str(launcher), "workspace", "show"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_show_output(
            console_show.stdout,
            root=selected_workspace.resolve(),
            source_label="saved workspace selection",
        )

        reset = _run(
            [str(launcher), "workspace", "reset"],
            cwd=run_directory,
            env=command_env,
        )
        if "No workspace files were deleted." not in reset.stdout:
            raise WorkspaceSmokeTestError(
                "Installed workspace reset did not report its deletion boundary."
            )
        if not selected_workspace.is_dir():
            raise WorkspaceSmokeTestError("Workspace reset deleted the workspace.")
        _assert_status(
            _core_workspace_status(
                python,
                cwd=run_directory,
                env=command_env,
            ),
            root=default_root,
            source="default",
            exists=False,
        )

        direct_set = _run(
            [str(launcher), "workspace", "set", str(selected_workspace)],
            cwd=run_directory,
            env=command_env,
        )
        if "Workspace ready" not in direct_set.stdout:
            raise WorkspaceSmokeTestError(
                "Installed direct workspace set did not report success."
            )
        _assert_status(
            _core_workspace_status(
                python,
                cwd=run_directory,
                env=command_env,
            ),
            root=selected_workspace,
            source="saved_config",
            exists=True,
        )

        override_env = dict(command_env)
        override_env["PDS_WORKSPACE_ROOT"] = str(environment_workspace)
        blocked = _run(
            [str(launcher), "workspace", "set", str(blocked_workspace)],
            cwd=run_directory,
            env=override_env,
            expected_returncode=1,
        )
        blocked_output = f"{blocked.stdout}\n{blocked.stderr}".lower()
        if "pds_workspace_root" not in blocked_output:
            raise WorkspaceSmokeTestError(
                "Environment-override refusal did not identify PDS_WORKSPACE_ROOT."
            )
        if blocked_workspace.exists():
            raise WorkspaceSmokeTestError(
                "Environment-override refusal mutated the blocked candidate."
            )

        final_reset = _run(
            [str(launcher), "workspace", "reset"],
            cwd=run_directory,
            env=command_env,
        )
        if "No workspace files were deleted." not in final_reset.stdout:
            raise WorkspaceSmokeTestError("Final workspace reset was not bounded.")
        if not selected_workspace.is_dir():
            raise WorkspaceSmokeTestError(
                "Final workspace reset removed initialized workspace data."
            )

        _assert_clean_directory(run_directory)


def build_parser() -> argparse.ArgumentParser:
    """Build the installed workspace smoke-test parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built Paper Data Suite wheel beside the exact Core wheel "
            "and exercise guided/direct workspace workflows in an isolated user "
            "configuration outside the source tree."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run installed workspace acceptance from the command line."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test_workspace_wheel(arguments.suite_wheel, arguments.core_wheel)
    except WorkspaceSmokeTestError as error:
        print(f"Workspace smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Workspace wheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
