"""Smoke-test installed guided shared-classroom setup from the built wheel."""

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


class ClassroomSetupSmokeTestError(RuntimeError):
    """Raised when installed shared-classroom setup acceptance fails."""


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
        raise ClassroomSetupSmokeTestError(
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
        raise ClassroomSetupSmokeTestError(
            "Smoke test imported paper_data_suite outside the isolated environment: "
            f"{installed_path}"
        ) from error


def _classroom_state(
    python: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
    school_year: str = "2026-2027",
) -> dict[str, object]:
    code = f"""
import json
from pds_core.academic_period_storage import load_current_academic_period_calendar
from pds_core.classes import list_class_folders
from pds_core.school_years import get_active_school_year
from pds_core.standards import load_workspace_standards_library
from pds_core.workspace import inspect_workspace_root

root = inspect_workspace_root().root
library = load_workspace_standards_library(root)
calendar = load_current_academic_period_calendar(root, {school_year!r})
print(json.dumps({{
    "root": str(root),
    "active_school_year": get_active_school_year(root),
    "class_count": len(list_class_folders(root)),
    "standards_count": len(library.standards),
    "profile_count": len(library.profiles),
    "calendar_revision": None if calendar is None else calendar.calendar_revision,
}}))
""".strip()
    result = _run([str(python), "-c", code], cwd=cwd, env=env)
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ClassroomSetupSmokeTestError(
            "Core classroom state was not a JSON object."
        )
    return cast(dict[str, object], payload)


def _assert_state(
    payload: Mapping[str, object],
    *,
    root: Path,
    active_school_year: str | None,
) -> None:
    if payload.get("root") != str(root.resolve()):
        raise ClassroomSetupSmokeTestError(
            f"Core resolved unexpected workspace root: {payload.get('root')!r}"
        )
    expected = {
        "active_school_year": active_school_year,
        "class_count": 0,
        "standards_count": 0,
        "profile_count": 0,
        "calendar_revision": None,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ClassroomSetupSmokeTestError(
                f"Unexpected Core classroom state for {key}: {payload.get(key)!r}"
            )


def _assert_no_setup_plan_artifacts(root: Path) -> None:
    if not root.is_dir():
        return
    unexpected = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and "setup" in path.name.lower()
        and "plan" in path.name.lower()
    ]
    if unexpected:
        raise ClassroomSetupSmokeTestError(
            "Guided setup persisted a suite setup-plan artifact: "
            + ", ".join(str(path) for path in unexpected)
        )


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        raise ClassroomSetupSmokeTestError(
            "Classroom smoke command created working-directory artifacts: "
            + ", ".join(item.name for item in contents)
        )


def smoke_test_classroom_setup_wheel(
    suite_wheel: Path,
    core_wheel: Path,
) -> None:
    """Exercise installed review-before-write classroom setup beside exact Core."""
    suite_wheel = suite_wheel.resolve()
    core_wheel = core_wheel.resolve()
    if not suite_wheel.is_file():
        raise ClassroomSetupSmokeTestError(f"Suite wheel does not exist: {suite_wheel}")
    if not core_wheel.is_file():
        raise ClassroomSetupSmokeTestError(f"Core wheel does not exist: {core_wheel}")

    with tempfile.TemporaryDirectory(prefix="pds-classroom-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        user_home = temp_root / "user"
        cancel_workspace = temp_root / "cancel-workspace"
        apply_workspace = temp_root / "apply-workspace"
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

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=command_env,
        )
        launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not launcher.is_file():
            raise ClassroomSetupSmokeTestError(
                f"Installed pds launcher does not exist: {launcher}"
            )

        module_help = _run(
            [str(python), "-m", "paper_data_suite", "setup", "--help"],
            cwd=run_directory,
            env=command_env,
        )
        console_help = _run(
            [str(launcher), "setup", "--help"],
            cwd=run_directory,
            env=command_env,
        )
        for output in (module_help.stdout, console_help.stdout):
            if "only exact APPLY authorizes Core writes" not in output:
                raise ClassroomSetupSmokeTestError(
                    "Installed setup help is missing the APPLY safety boundary."
                )

        _run(
            [str(launcher), "workspace", "set", str(cancel_workspace)],
            cwd=run_directory,
            env=command_env,
        )
        cancel_input = "2026-2027\n\n\n2\napply\nQ\n"
        cancelled = _run(
            [str(python), "-m", "paper_data_suite", "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=cancel_input,
        )
        if "Type exact APPLY, E, or Q." not in cancelled.stdout:
            raise ClassroomSetupSmokeTestError(
                "Installed setup accepted or failed to reject lowercase apply."
            )
        if "No setup changes were made." not in cancelled.stdout:
            raise ClassroomSetupSmokeTestError(
                "Installed setup cancellation did not report the no-write boundary."
            )
        _assert_state(
            _classroom_state(python, cwd=run_directory, env=command_env),
            root=cancel_workspace,
            active_school_year=None,
        )
        _assert_no_setup_plan_artifacts(cancel_workspace)

        _run(
            [str(launcher), "workspace", "set", str(apply_workspace)],
            cwd=run_directory,
            env=command_env,
        )
        apply_input = "2026-2027\n\n\n2\nAPPLY\n"
        applied = _run(
            [str(launcher), "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=apply_input,
        )
        required = (
            "Shared setup review",
            "2026-2027: OPEN",
            "Plan is eligible for final APPLY.",
            "Shared classroom setup complete",
            "school_year:OPEN:2026-2027",
        )
        missing = [fragment for fragment in required if fragment not in applied.stdout]
        if missing:
            raise ClassroomSetupSmokeTestError(
                "Installed setup APPLY output is missing expected content: "
                + ", ".join(missing)
            )
        _assert_state(
            _classroom_state(python, cwd=run_directory, env=command_env),
            root=apply_workspace,
            active_school_year="2026-2027",
        )
        _assert_no_setup_plan_artifacts(apply_workspace)

        rerun_input = "\n\n2\nAPPLY\n"
        rerun = _run(
            [str(launcher), "setup"],
            cwd=run_directory,
            env=command_env,
            input_text=rerun_input,
        )
        if "No persistent changes were needed" not in rerun.stdout:
            raise ClassroomSetupSmokeTestError(
                "Installed idempotent rerun did not report a no-op."
            )
        _assert_state(
            _classroom_state(python, cwd=run_directory, env=command_env),
            root=apply_workspace,
            active_school_year="2026-2027",
        )
        _assert_no_setup_plan_artifacts(apply_workspace)
        _assert_clean_directory(run_directory)


def build_parser() -> argparse.ArgumentParser:
    """Build the installed classroom-setup smoke-test parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built Paper Data Suite wheel beside the exact Core wheel "
            "and exercise guided shared-classroom setup in an isolated user profile."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run installed shared-classroom setup acceptance from the command line."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test_classroom_setup_wheel(
            arguments.suite_wheel,
            arguments.core_wheel,
        )
    except ClassroomSetupSmokeTestError as error:
        print(f"Classroom setup smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Classroom setup wheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
