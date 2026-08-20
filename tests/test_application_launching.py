from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from paper_data_suite.application_launching import (
    ApplicationLauncherResolutionError,
    ApplicationLaunchExecutionError,
    ApplicationLaunchRefusedError,
    LauncherResolutionCode,
    launch_application,
    resolve_application_launchers,
    resolve_current_environment_launcher,
)
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)


def _application(
    *,
    component_id: str = "scoreform",
    status: ApplicationLaunchStatus = ApplicationLaunchStatus.AVAILABLE,
    launcher_path: Path | None = None,
) -> ApplicationObservation:
    return ApplicationObservation(
        component_id=component_id,
        display_name=component_id.title(),
        purpose="Synthetic test application.",
        distribution=component_id,
        qualified_version="1.0.0",
        installed_version="1.0.0",
        console_script_name=component_id,
        console_script_target=f"{component_id}.cli:main",
        status=status,
        reason="metadata qualified",
        launcher_path=launcher_path,
    )


def test_windows_launcher_resolves_only_from_current_scripts_directory(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "Current Env" / "Scripts"
    scripts.mkdir(parents=True)
    expected = scripts / "scoreform.exe"
    expected.write_bytes(b"launcher")

    foreign = tmp_path / "foreign" / "scoreform.exe"
    foreign.parent.mkdir()
    foreign.write_bytes(b"foreign")

    resolved = resolve_current_environment_launcher(
        "scoreform",
        scripts_path_lookup=lambda: str(scripts),
        platform="win32",
    )

    assert resolved == expected.resolve()
    assert resolved != foreign.resolve()


def test_posix_launcher_resolves_bare_script_name(tmp_path: Path) -> None:
    scripts = tmp_path / "bin"
    scripts.mkdir()
    expected = scripts / "quillan"
    expected.write_text("#!/bin/sh\n", encoding="utf-8")

    resolved = resolve_current_environment_launcher(
        "quillan",
        scripts_path_lookup=lambda: str(scripts),
        platform="linux",
        executable_check=lambda path: path == expected.resolve(),
    )

    assert resolved == expected.resolve()


def test_launcher_resolution_rejects_unsafe_name(tmp_path: Path) -> None:
    with pytest.raises(ApplicationLauncherResolutionError) as raised:
        resolve_current_environment_launcher(
            "../scoreform",
            scripts_path_lookup=lambda: str(tmp_path),
            platform="win32",
        )

    assert raised.value.code is LauncherResolutionCode.INVALID_NAME


def test_launcher_resolution_rejects_missing_scripts_directory(tmp_path: Path) -> None:
    with pytest.raises(ApplicationLauncherResolutionError) as raised:
        resolve_current_environment_launcher(
            "scoreform",
            scripts_path_lookup=lambda: str(tmp_path / "missing"),
            platform="win32",
        )

    assert raised.value.code is LauncherResolutionCode.SCRIPTS_DIRECTORY_UNAVAILABLE


def test_launcher_resolution_rejects_missing_launcher(tmp_path: Path) -> None:
    scripts = tmp_path / "Scripts"
    scripts.mkdir()

    with pytest.raises(ApplicationLauncherResolutionError) as raised:
        resolve_current_environment_launcher(
            "scoreform",
            scripts_path_lookup=lambda: str(scripts),
            platform="win32",
        )

    assert raised.value.code is LauncherResolutionCode.MISSING


def test_posix_launcher_must_be_executable(tmp_path: Path) -> None:
    scripts = tmp_path / "bin"
    scripts.mkdir()
    (scripts / "concord").write_text("#!/bin/sh\n", encoding="utf-8")

    with pytest.raises(ApplicationLauncherResolutionError) as raised:
        resolve_current_environment_launcher(
            "concord",
            scripts_path_lookup=lambda: str(scripts),
            platform="linux",
            executable_check=lambda _path: False,
        )

    assert raised.value.code is LauncherResolutionCode.NOT_EXECUTABLE


def test_launcher_resolution_rejects_symlink_escape_when_supported(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "bin"
    scripts.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    link = scripts / "vitrine"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlink creation is unavailable")

    with pytest.raises(ApplicationLauncherResolutionError) as raised:
        resolve_current_environment_launcher(
            "vitrine",
            scripts_path_lookup=lambda: str(scripts),
            platform="linux",
            executable_check=lambda _path: True,
        )

    assert raised.value.code is LauncherResolutionCode.OUTSIDE_ENVIRONMENT


def test_inventory_launcher_resolution_isolates_one_missing_launcher() -> None:
    inventory = ApplicationInventory(
        (
            _application(component_id="scoreform"),
            _application(component_id="quillan"),
            _application(
                component_id="vitrine",
                status=ApplicationLaunchStatus.NOT_INSTALLED,
            ),
        )
    )
    expected = Path("C:/PDS/Scripts/scoreform.exe")

    def resolver(name: str) -> Path:
        if name == "scoreform":
            return expected
        raise ApplicationLauncherResolutionError(
            LauncherResolutionCode.MISSING,
            "missing",
        )

    resolved = resolve_application_launchers(
        inventory,
        launcher_resolver=resolver,
    )

    scoreform = resolved.for_component("scoreform")
    quillan = resolved.for_component("quillan")
    vitrine = resolved.for_component("vitrine")
    assert scoreform is not None
    assert quillan is not None
    assert vitrine is not None
    assert scoreform.status is ApplicationLaunchStatus.AVAILABLE
    assert scoreform.launcher_path == expected
    assert quillan.status is ApplicationLaunchStatus.UNAVAILABLE
    assert quillan.launcher_path is None
    assert "missing" in quillan.reason
    assert vitrine.status is ApplicationLaunchStatus.NOT_INSTALLED


def test_launch_uses_exact_launcher_and_sanitized_inherited_environment() -> None:
    launcher = Path(r"C:\PDS Suite\Scripts\scoreform.exe")
    application = _application(launcher_path=launcher)
    observed: dict[str, object] = {}

    def runner(
        args: object,
        *,
        check: bool,
        shell: bool,
        env: object,
    ) -> subprocess.CompletedProcess[object]:
        observed["args"] = args
        observed["check"] = check
        observed["shell"] = shell
        observed["env"] = env
        return subprocess.CompletedProcess([str(launcher)], 0)

    source_environment = {
        "PATH": r"C:\foreign",
        "PYTHONPATH": r"C:\Dev\pds-scoreform",
        "PDS_WORKSPACE_ROOT": r"C:\Teacher Workspace",
        "KEEP_ME": "yes",
    }
    result = launch_application(
        application,
        process_runner=runner,
        environ=source_environment,
    )

    assert result.succeeded is True
    assert result.exit_code == 0
    assert observed["args"] == (str(launcher),)
    assert observed["check"] is False
    assert observed["shell"] is False
    child_environment = observed["env"]
    assert isinstance(child_environment, dict)
    assert "PYTHONPATH" not in child_environment
    assert child_environment["PDS_WORKSPACE_ROOT"] == r"C:\Teacher Workspace"
    assert child_environment["PATH"] == r"C:\foreign"
    assert child_environment["KEEP_ME"] == "yes"
    assert source_environment["PYTHONPATH"] == r"C:\Dev\pds-scoreform"


def test_launch_preserves_child_nonzero_status() -> None:
    launcher = Path("/suite/bin/concord")
    application = _application(component_id="concord", launcher_path=launcher)

    def runner(
        args: object,
        *,
        check: bool,
        shell: bool,
        env: object,
    ) -> subprocess.CompletedProcess[object]:
        del args, check, shell, env
        return subprocess.CompletedProcess([str(launcher)], 4)

    result = launch_application(application, process_runner=runner, environ={})

    assert result.succeeded is False
    assert result.exit_code == 4


def test_launch_refuses_unavailable_application() -> None:
    application = _application(status=ApplicationLaunchStatus.UNAVAILABLE)

    with pytest.raises(ApplicationLaunchRefusedError, match="not available"):
        launch_application(application, environ={})


def test_launch_startup_oserror_is_bounded() -> None:
    application = _application(launcher_path=Path("/suite/bin/scoreform"))

    def runner(
        args: object,
        *,
        check: bool,
        shell: bool,
        env: object,
    ) -> subprocess.CompletedProcess[object]:
        del args, check, shell, env
        raise OSError("cannot execute")

    with pytest.raises(ApplicationLaunchExecutionError, match="cannot execute"):
        launch_application(application, process_runner=runner, environ={})
