"""Smoke-test the full qualified PDS application composition from wheels."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    verify_artifact_directory,
)
from paper_data_suite.compatibility import (
    CompatibilityManifestError,
    load_release_compatibility_manifest,
)


class ApplicationWheelSmokeError(RuntimeError):
    """Raised when full-composition installed application acceptance fails."""


@dataclass(frozen=True, slots=True)
class ApplicationExpectation:
    """One launchable application expected from the active suite manifest."""

    component_id: str
    display_name: str
    version: str
    wheel: str
    console_script: str


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    timeout: float = 180.0,
    require_success: bool = True,
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
        raise ApplicationWheelSmokeError(
            f"Command could not complete: {' '.join(command)}: {error}"
        ) from error
    if require_success and result.returncode != 0:
        raise ApplicationWheelSmokeError(
            "Command failed "
            f"({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
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


def _assert_clean_directory(path: Path) -> None:
    contents = tuple(path.iterdir())
    if contents:
        names = ", ".join(item.name for item in contents)
        raise ApplicationWheelSmokeError(
            f"Application acceptance created working-directory artifacts: {names}"
        )


def _expectations() -> tuple[ApplicationExpectation, ...]:
    manifest = load_release_compatibility_manifest()
    applications: list[ApplicationExpectation] = []
    for component in manifest.components:
        if "launchable_application" not in component.capabilities:
            continue
        console_scripts = tuple(
            entry_point.name
            for entry_point in component.entry_points
            if entry_point.group == "console_scripts"
        )
        if len(console_scripts) != 1:
            raise ApplicationWheelSmokeError(
                f"{component.component_id} must declare one console script."
            )
        applications.append(
            ApplicationExpectation(
                component_id=component.component_id,
                display_name=component.display_name,
                version=component.version,
                wheel=component.release.wheel,
                console_script=console_scripts[0],
            )
        )
    if not applications:
        raise ApplicationWheelSmokeError(
            "Compatibility manifest declares no launchable applications."
        )
    return tuple(applications)


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
        raise ApplicationWheelSmokeError(
            "Compatibility manifest must declare exactly one Core component."
        )
    core_wheel = artifact_dir / core_rows[0].release.wheel
    application_wheels = tuple(
        artifact_dir / application.wheel for application in applications
    )
    missing = tuple(
        path
        for path in (core_wheel, *application_wheels)
        if not path.is_file()
    )
    if missing:
        raise ApplicationWheelSmokeError(
            "Verified component artifact is missing: "
            + ", ".join(str(path) for path in missing)
        )
    return core_wheel, application_wheels


def _assert_inventory_output(
    output: str,
    applications: Sequence[ApplicationExpectation],
) -> None:
    if not output.startswith("Paper Data Suite applications\n"):
        raise ApplicationWheelSmokeError(
            "Installed pds modules output has an unexpected heading."
        )
    for application in applications:
        required = (
            application.display_name,
            "Status: available",
            f"Component ID: {application.component_id}",
            f"Suite-qualified version: {application.version}",
            f"Installed version: {application.version}",
            f"Launch: pds launch {application.component_id}",
        )
        missing = tuple(fragment for fragment in required if fragment not in output)
        if missing:
            raise ApplicationWheelSmokeError(
                f"Inventory for {application.component_id} is incomplete: "
                + ", ".join(missing)
            )
    if output.count("Status: available") != len(applications):
        raise ApplicationWheelSmokeError(
            "All-qualified inventory contains an unexpected application status."
        )
    forbidden = ("PDS Core\n", "Meridian\n", "Portia\n", ".cli:main")
    leaked = tuple(fragment for fragment in forbidden if fragment in output)
    if leaked:
        raise ApplicationWheelSmokeError(
            "All-qualified inventory exposed an invalid row or private target: "
            + ", ".join(leaked)
        )


def _foreign_launcher(
    directory: Path,
    component_id: str,
) -> tuple[Path, Path]:
    marker = directory / f"foreign-{component_id}-ran.txt"
    if os.name == "nt":
        launcher = directory / f"{component_id}.cmd"
        launcher.write_text(
            "@echo off\r\n"
            f'> "{marker}" echo foreign launcher executed\r\n',
            encoding="utf-8",
        )
    else:
        launcher = directory / component_id
        launcher.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' 'foreign launcher executed' > '{marker}'\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher, marker


def _assert_menu_launch(
    pds_launcher: Path,
    application: ApplicationExpectation,
    *,
    cwd: Path,
    env: Mapping[str, str],
    missing_workspace: Path,
    foreign_marker: Path,
) -> None:
    result = _run(
        [str(pds_launcher), "launch", application.component_id],
        cwd=cwd,
        env=env,
        input_text="q\n",
        timeout=60.0,
    )
    if application.display_name.casefold() not in result.stdout.casefold():
        raise ApplicationWheelSmokeError(
            f"{application.display_name} menu did not identify itself in output."
        )
    if missing_workspace.exists():
        raise ApplicationWheelSmokeError(
            f"{application.display_name} menu created the synthetic workspace."
        )
    if foreign_marker.exists():
        raise ApplicationWheelSmokeError(
            f"pds launch used a foreign {application.component_id} command from PATH."
        )
    _assert_clean_directory(cwd)


def smoke_test(suite_wheel: Path, artifact_dir: Path) -> None:
    """Install the exact qualified composition and launch every application menu."""
    suite_wheel = suite_wheel.resolve()
    artifact_dir = artifact_dir.resolve()
    if not suite_wheel.is_file():
        raise ApplicationWheelSmokeError(
            f"Suite wheel does not exist: {suite_wheel}"
        )
    if not artifact_dir.is_dir():
        raise ApplicationWheelSmokeError(
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
        OSError,
        CompatibilityManifestError,
        ArtifactVerificationError,
    ) as error:
        raise ApplicationWheelSmokeError(
            f"Qualified component artifact verification failed: {error}"
        ) from error

    with tempfile.TemporaryDirectory(prefix="pds-suite-app-smoke-") as temporary:
        temp_root = Path(temporary)
        environment = temp_root / "venv"
        run_directory = temp_root / "run"
        foreign_bin = temp_root / "foreign-bin"
        missing_workspace = temp_root / "synthetic-missing-workspace"
        run_directory.mkdir()
        foreign_bin.mkdir()

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

        command_env = dict(install_env)
        command_env["PDS_WORKSPACE_ROOT"] = str(missing_workspace)

        foreign_markers: dict[str, Path] = {}
        for application in applications:
            _launcher, marker = _foreign_launcher(
                foreign_bin,
                application.console_script,
            )
            foreign_markers[application.component_id] = marker

        existing_path = command_env.get("PATH", "")
        command_env["PATH"] = (
            f"{foreign_bin}{os.pathsep}{existing_path}"
            if existing_path
            else str(foreign_bin)
        )

        module_inventory = _run(
            [str(python), "-m", "paper_data_suite", "modules"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_inventory_output(module_inventory.stdout, applications)
        _assert_clean_directory(run_directory)

        scripts = _scripts_directory(
            python,
            cwd=run_directory,
            env=command_env,
        )
        pds_launcher = scripts / ("pds.exe" if os.name == "nt" else "pds")
        if not pds_launcher.is_file():
            raise ApplicationWheelSmokeError(
                f"Installed pds launcher does not exist: {pds_launcher}"
            )

        console_inventory = _run(
            [str(pds_launcher), "modules"],
            cwd=run_directory,
            env=command_env,
        )
        _assert_inventory_output(console_inventory.stdout, applications)
        _assert_clean_directory(run_directory)

        for application in applications:
            _assert_menu_launch(
                pds_launcher,
                application,
                cwd=run_directory,
                env=command_env,
                missing_workspace=missing_workspace,
                foreign_marker=foreign_markers[application.component_id],
            )

        unexpected_markers = tuple(
            marker for marker in foreign_markers.values() if marker.exists()
        )
        if unexpected_markers:
            raise ApplicationWheelSmokeError(
                "Foreign PATH launchers executed: "
                + ", ".join(str(path) for path in unexpected_markers)
            )


def build_parser() -> argparse.ArgumentParser:
    """Build the full-composition installed-wheel smoke-test parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Install the built suite wheel with every exact qualified component "
            "wheel, verify the all-available inventory, and launch/quit every "
            "teacher menu through installed pds."
        )
    )
    parser.add_argument("suite_wheel", type=Path)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        required=True,
        help=(
            "directory containing every exact component wheel declared by the "
            "suite compatibility manifest"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run full-composition installed application acceptance."""
    arguments = build_parser().parse_args(argv)
    try:
        smoke_test(arguments.suite_wheel, arguments.artifact_dir)
    except ApplicationWheelSmokeError as error:
        print(f"Application wheel smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Application wheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
