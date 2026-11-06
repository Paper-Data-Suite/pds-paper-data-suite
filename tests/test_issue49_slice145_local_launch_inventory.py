"""Slice 145: version-tolerant module listing and launch preflight regressions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from paper_data_suite.application_launching import (
    ApplicationLauncherResolutionError,
    LauncherResolutionCode,
)
from paper_data_suite.applications import ApplicationLaunchStatus
from paper_data_suite.evergreen_local_application_inventory import (
    collect_local_launch_inventory,
)
from paper_data_suite.evergreen_local_compatibility import (
    ConsoleDeclaration,
    InstalledPackage,
    LocalCompatibilityReport,
    LocalInspectionError,
    assess_local_environment,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS


def _pkg(
    component_id: str,
    version: str,
    *,
    requires: tuple[str, ...] = (),
) -> InstalledPackage:
    spec = next(
        c for c in APPROVED_COMPONENTS if c.component_id == component_id
    )
    return InstalledPackage(
        distribution=spec.distribution,
        version=version,
        requires_python=">=3.11,<3.15",
        requires_dist=requires,
        entry_points=tuple(
            ConsoleDeclaration(c.name, c.target) for c in spec.console_scripts
        ),
    )


def _assess(*packages: InstalledPackage) -> LocalCompatibilityReport:
    return assess_local_environment(packages, python_version="3.13.7")


def _resolve(name: str) -> Path:
    return Path("C:/PDS/env/Scripts") / f"{name}.exe"


def _inventory(*packages: InstalledPackage):
    return collect_local_launch_inventory(
        report=_assess(*packages), launcher_resolver=_resolve
    )


def test_six_approved_applications_exclude_core() -> None:
    report = _inventory(_pkg("core", "0.6.6"))
    ids = [a.component_id for a in report.applications]
    assert ids == [
        "scoreform", "quillan", "concord", "meridian", "vitrine", "portia"
    ]
    assert report.for_component("core") is None
    assert report.for_component("unregistered") is None


@pytest.mark.parametrize(
    ("component_id", "version"),
    [
        ("scoreform", "0.13.0"),
        ("quillan", "0.10.6"),
        ("concord", "0.3.4"),
        ("meridian", "0.4.2"),
        ("vitrine", "0.4.0"),
        ("portia", "0.2.0"),
    ],
)
def test_newer_approved_installed_wheels_can_be_locally_launchable(
    component_id: str, version: str
) -> None:
    item = _inventory(_pkg("core", "0.6.6"), _pkg(component_id, version))
    app = item.for_component(component_id)
    assert app is not None
    assert app.status is ApplicationLaunchStatus.AVAILABLE
    assert app.installed_version == version
    assert app.launcher_path is not None
    assert "provenance unverified" in app.reason
    assert "integration qualification is separate" in app.reason


def test_missing_optional_component_remains_not_installed() -> None:
    row = _inventory(_pkg("core", "0.6.6")).for_component("quillan")
    assert row is not None
    assert row.status is ApplicationLaunchStatus.NOT_INSTALLED
    assert row.launcher_path is None


def test_newer_core_compatible_without_0_6_3_pin() -> None:
    row = _inventory(
        _pkg("core", "0.6.6"),
        _pkg("quillan", "0.10.6", requires=("pds-core>=0.6.5,<0.7",)),
    ).for_component("quillan")
    assert row is not None
    assert row.status is ApplicationLaunchStatus.AVAILABLE
    assert row.qualified_version == "0.9.0"  # Historical reference only


def test_wrong_entry_point_target_blocks_module_only() -> None:
    broken = replace(
        _pkg("quillan", "0.10.6"),
        entry_points=(ConsoleDeclaration("quillan", "foreign.cli:main"),),
    )
    inventory = _inventory(
        _pkg("core", "0.6.6"), broken, _pkg("scoreform", "0.13.0")
    )
    assert inventory.for_component("quillan").status is (
        ApplicationLaunchStatus.INCOMPATIBLE
    )
    assert inventory.for_component("scoreform").status is (
        ApplicationLaunchStatus.AVAILABLE
    )


def test_wrong_core_range_blocks_launch() -> None:
    row = _inventory(_pkg("core", "0.7.0"), _pkg("quillan", "0.10.6"))
    app = row.for_component("quillan")
    assert app is not None
    assert app.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "core_not_compatible" in app.reason


def test_missing_runtime_dependency_blocks_launch() -> None:
    row = _inventory(
        _pkg("core", "0.6.6"),
        _pkg("scoreform", "0.13.0", requires=("absent-library>=2",)),
    ).for_component("scoreform")
    assert row is not None
    assert row.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "dependency_missing" in row.reason


def test_editable_install_does_not_gain_launch_permission() -> None:
    row = _inventory(
        _pkg("core", "0.6.6"),
        replace(_pkg("portia", "0.2.0"), editable=True),
    ).for_component("portia")
    assert row is not None
    assert row.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "editable_pds_install" in row.reason


def test_launcher_failure_isolated_from_other_applications() -> None:
    def resolver(name: str) -> Path:
        if name == "quillan":
            raise ApplicationLauncherResolutionError(
                LauncherResolutionCode.MISSING, "synthetic missing launcher"
            )
        return _resolve(name)

    result = collect_local_launch_inventory(
        report=_assess(
            _pkg("core", "0.6.6"),
            _pkg("quillan", "0.10.6"),
            _pkg("portia", "0.2.0"),
        ),
        launcher_resolver=resolver,
    )
    quillan = result.for_component("quillan")
    portia = result.for_component("portia")
    assert quillan is not None and portia is not None
    assert quillan.status is ApplicationLaunchStatus.UNAVAILABLE
    assert portia.status is ApplicationLaunchStatus.AVAILABLE
    assert quillan.launcher_path is None
    assert "launcher could not be resolved" in quillan.reason


def test_unexpected_registry_report_identity_is_refused() -> None:
    result = _assess(_pkg("core", "0.6.6"))
    mismatched = replace(
        result.components[1], distribution="completely-different"
    )
    forged = replace(
        result, components=(result.components[0], mismatched, *result.components[2:])
    )
    with pytest.raises(LocalInspectionError, match="distribution mismatch"):
        collect_local_launch_inventory(
            report=forged, launcher_resolver=_resolve
        )


def test_no_installed_module_code_is_imported_in_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import evergreen_local_application_inventory as mod

    def fail() -> None:
        raise AssertionError("observer must not be called with explicit report")

    monkeypatch.setattr(mod, "inspect_local_compatibility", fail)
    result = mod.collect_local_launch_inventory(
        report=_assess(_pkg("core", "0.6.6")),
        launcher_resolver=_resolve,
    )
    assert len(result.applications) == 6
