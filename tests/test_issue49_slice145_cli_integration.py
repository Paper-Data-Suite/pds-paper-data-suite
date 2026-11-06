"""Slice 145: normal CLI paths use installed local compatibility, not v0.1 pins."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_data_suite import cli
from paper_data_suite.application_launching import ApplicationLaunchResult
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)


def _app(component_id: str, *, available: bool = True) -> ApplicationObservation:
    return ApplicationObservation(
        component_id=component_id,
        display_name=component_id.title(),
        purpose="Teacher workflow.",
        distribution=f"pds-{component_id}",
        qualified_version="not listed",
        installed_version="0.4.2",
        console_script_name=component_id,
        console_script_target=f"{component_id}.cli:main",
        status=(
            ApplicationLaunchStatus.AVAILABLE
            if available
            else ApplicationLaunchStatus.INCOMPATIBLE
        ),
        reason="local checks passed; wheel provenance unverified",
        remediation=None,
        launcher_path=(Path("C:/PDS/Scripts") / f"{component_id}.exe")
        if available
        else None,
    )


def test_resolved_inventory_uses_local_adapter_not_manifest_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = ApplicationInventory((_app("meridian"),))
    monkeypatch.setattr(cli, "collect_local_launch_inventory", lambda: inventory)
    assert cli._resolved_inventory(object()) is inventory


def test_modules_prints_provenance_and_historical_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((_app("meridian"),)),
    )
    assert cli.main(("modules",)) == 0
    output = capsys.readouterr().out
    assert "Historical manifest version: not listed" in output
    assert "Installed version: 0.4.2" in output
    assert "provenance" in output.lower()
    assert "pds launch meridian" in output
    assert "exact integration" in output.lower()


def test_launch_meridian_not_registered_in_historical_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chosen = _app("meridian")
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((chosen,)),
    )
    monkeypatch.setattr(cli, "record_recent_component", lambda name: None)
    launched: list[ApplicationObservation] = []

    def run(application: ApplicationObservation) -> ApplicationLaunchResult:
        launched.append(application)
        assert application.launcher_path is not None
        return ApplicationLaunchResult(
            component_id=application.component_id,
            display_name=application.display_name,
            launcher_path=application.launcher_path,
            exit_code=0,
        )

    monkeypatch.setattr(cli, "launch_application", run)
    assert cli.main(("launch", "meridian")) == 0
    assert launched == [chosen]
    assert "provenance" in capsys.readouterr().err.lower()


def test_launch_portia_refuses_incompatible_install(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "_resolved_inventory",
        lambda manifest: ApplicationInventory((_app("portia", available=False),)),
    )
    monkeypatch.setattr(
        cli,
        "launch_application",
        lambda app: pytest.fail("incompatible module must not run"),
    )
    assert cli.main(("launch", "portia")) == 1
    assert "Cannot launch Portia" in capsys.readouterr().err


def test_core_is_still_not_suite_launchable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("launch", "core")) == 1
    assert "not a suite-launchable application" in capsys.readouterr().err


def test_unknown_module_remains_a_request_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("launch", "unregistered")) == 2
    assert "Unknown Paper Data Suite component ID" in capsys.readouterr().err
