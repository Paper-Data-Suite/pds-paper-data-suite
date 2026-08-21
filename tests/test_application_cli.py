from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from paper_data_suite.application_launching import (
    ApplicationLaunchExecutionError,
    ApplicationLaunchResult,
)
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationInventoryError,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.cli import main, render_application_inventory


def _application(
    component_id: str = "quillan",
    *,
    status: ApplicationLaunchStatus = ApplicationLaunchStatus.AVAILABLE,
    installed_version: str | None = "0.9.0",
    remediation: str | None = None,
    launcher_path: Path | None = Path("C:/PDS/Scripts/quillan.exe"),
) -> ApplicationObservation:
    return ApplicationObservation(
        component_id=component_id,
        display_name=component_id.title(),
        purpose=f"Teacher purpose for {component_id}.",
        distribution=component_id,
        qualified_version="0.9.0",
        installed_version=installed_version,
        console_script_name=component_id,
        console_script_target=f"{component_id}.cli:main",
        status=status,
        reason=f"{component_id} status reason.",
        remediation=remediation,
        launcher_path=launcher_path,
    )


def _console_script_path() -> Path:
    script_name = "pds.exe" if os.name == "nt" else "pds"
    return Path(sysconfig.get_path("scripts")) / script_name


@pytest.fixture(autouse=True)
def _isolate_suite_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import paper_data_suite.cli as cli

    monkeypatch.setattr(cli, "record_recent_component", lambda component_id: None)


def test_render_application_inventory_is_teacher_facing_and_bounded() -> None:
    inventory = ApplicationInventory(
        (
            _application(),
            _application(
                "scoreform",
                status=ApplicationLaunchStatus.NOT_INSTALLED,
                installed_version=None,
                remediation="Use the verified bootstrap workflow.",
                launcher_path=None,
            ),
        )
    )

    output = render_application_inventory(inventory)

    assert output.startswith("Paper Data Suite applications\n\n")
    assert "Quillan" in output
    assert "Purpose: Teacher purpose for quillan." in output
    assert "Status: available" in output
    assert "Launch: pds launch quillan" in output
    assert "Scoreform" in output
    assert "Status: not installed" in output
    assert "Installed version: not installed" in output
    assert "Reason: scoreform status reason." in output
    assert "Remediation: Use the verified bootstrap workflow." in output
    assert "quillan.cli:main" not in output
    assert "C:/PDS" not in output


def test_modules_dispatches_inventory_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    inventory = ApplicationInventory((_application(),))
    monkeypatch.setattr(cli, "_resolved_inventory", lambda manifest: inventory)

    assert main(("modules",)) == 0
    output = capsys.readouterr().out
    assert "Paper Data Suite applications" in output
    assert "pds launch quillan" in output


def test_modules_inventory_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    def fail(manifest: object) -> ApplicationInventory:
        del manifest
        raise ApplicationInventoryError("metadata unavailable")

    monkeypatch.setattr(cli, "_resolved_inventory", fail)

    assert main(("modules",)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Application inventory failed: metadata unavailable\n"


def test_launch_available_application_returns_child_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    application = _application()
    inventory = ApplicationInventory((application,))
    monkeypatch.setattr(cli, "_resolved_inventory", lambda manifest: inventory)
    observed: list[ApplicationObservation] = []

    def launch(value: ApplicationObservation) -> ApplicationLaunchResult:
        observed.append(value)
        assert value.launcher_path is not None
        return ApplicationLaunchResult(
            component_id=value.component_id,
            display_name=value.display_name,
            launcher_path=value.launcher_path,
            exit_code=0,
        )

    monkeypatch.setattr(cli, "launch_application", launch)

    assert main(("launch", "quillan")) == 0
    assert observed == [application]
    assert capsys.readouterr().out == ""


def test_launch_refuses_not_installed_application(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    application = _application(
        status=ApplicationLaunchStatus.NOT_INSTALLED,
        installed_version=None,
        remediation="Use the verified bootstrap workflow.",
        launcher_path=None,
    )
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )

    assert main(("launch", "quillan")) == 1
    captured = capsys.readouterr()
    assert "Cannot launch Quillan: quillan status reason." in captured.err
    assert "Remediation: Use the verified bootstrap workflow." in captured.err


def test_launch_known_non_launchable_core_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("launch", "core")) == 1
    assert "not a suite-launchable application" in capsys.readouterr().err


def test_launch_unknown_component_returns_request_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("launch", "not-a-component")) == 2
    assert "Unknown Paper Data Suite component ID" in capsys.readouterr().err


def test_launch_missing_component_argument_is_argparse_usage_error() -> None:
    with pytest.raises(SystemExit) as raised:
        main(("launch",))
    assert raised.value.code == 2


def test_launch_child_nonzero_returns_suite_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    application = _application()
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )

    def launch(value: ApplicationObservation) -> ApplicationLaunchResult:
        assert value.launcher_path is not None
        return ApplicationLaunchResult(
            component_id=value.component_id,
            display_name=value.display_name,
            launcher_path=value.launcher_path,
            exit_code=4,
        )

    monkeypatch.setattr(cli, "launch_application", launch)

    assert main(("launch", "quillan")) == 1
    error = capsys.readouterr().err
    assert "Quillan exited with status 4." in error
    assert "application reported a non-success status" in error


def test_launch_start_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import paper_data_suite.cli as cli

    application = _application()
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((application,)),
    )

    def launch(value: ApplicationObservation) -> ApplicationLaunchResult:
        del value
        raise ApplicationLaunchExecutionError("could not start Quillan")

    monkeypatch.setattr(cli, "launch_application", launch)

    assert main(("launch", "quillan")) == 1
    assert capsys.readouterr().err == "Launch failed: could not start Quillan\n"


def test_modules_help_is_explicit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("modules", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: pds modules" in output
    assert "without importing or starting them" in output


def test_launch_help_is_explicit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("launch", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    normalized_output = " ".join(output.split())
    assert "usage: pds launch" in output
    assert "component_id" in output
    assert "verified public console boundary" in normalized_output


@pytest.mark.parametrize(
    "command",
    [
        (sys.executable, "-m", "paper_data_suite", "modules"),
        (str(_console_script_path()), "modules"),
    ],
)
def test_public_modules_command_is_read_only(
    tmp_path: Path,
    command: tuple[str, ...],
) -> None:
    before = tuple(tmp_path.iterdir())
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert tuple(tmp_path.iterdir()) == before
    assert result.stdout.startswith("Paper Data Suite applications\n")
    assert "Core\n" not in result.stdout
