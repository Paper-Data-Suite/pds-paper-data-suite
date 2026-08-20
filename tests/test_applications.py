from __future__ import annotations

from importlib import metadata

import pytest

from paper_data_suite.applications import (
    ApplicationInventoryError,
    ApplicationLaunchStatus,
    collect_application_inventory,
)
from paper_data_suite.compatibility import (
    ComponentCompatibility,
    EntryPointExpectation,
    PythonCompatibility,
    ReleaseArtifact,
    ReleaseCompatibilityManifest,
    SuiteCompatibility,
)
from paper_data_suite.component_inspection import EntryPointObservation


def _component(
    component_id: str,
    distribution: str,
    version: str,
    *,
    capabilities: tuple[str, ...],
    purpose: str | None,
    console_name: str | None = None,
    routing: bool = False,
) -> ComponentCompatibility:
    entry_points: list[EntryPointExpectation] = []
    if console_name is not None:
        entry_points.append(
            EntryPointExpectation(
                group="console_scripts",
                name=console_name,
                target=f"{component_id}.cli:main",
            )
        )
    if routing:
        entry_points.append(
            EntryPointExpectation(
                group="paper_data_suite.modules",
                name=component_id,
                target=f"{component_id}.pds_module:get_module_profile",
            )
        )
    return ComponentCompatibility(
        component_id=component_id,
        display_name=component_id.title(),
        repository=f"Paper-Data-Suite/pds-{component_id}",
        distribution=distribution,
        import_name=component_id,
        required=component_id == "core",
        compatibility_status="supported",
        version=version,
        requires_python=">=3.11,<3.15",
        release=ReleaseArtifact(
            tag=f"v{version}",
            wheel=f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl",
            sha256="0" * 64,
        ),
        capabilities=capabilities,
        entry_points=tuple(entry_points),
        external_prerequisites=(),
        purpose=purpose,
    )


def _manifest() -> ReleaseCompatibilityManifest:
    return ReleaseCompatibilityManifest(
        record_type="paper_data_suite_release_compatibility_manifest",
        contract_version="1",
        suite=SuiteCompatibility(
            distribution="paper-data-suite",
            version="0.1.0.dev0",
            release_status="development",
        ),
        python=PythonCompatibility(
            specifier=">=3.11,<3.15",
            tested_minors=("3.11", "3.12", "3.13", "3.14"),
        ),
        components=(
            _component(
                "concord",
                "pds-concord",
                "0.2.0",
                capabilities=("launchable_application",),
                purpose="Collaborative classroom evidence.",
                console_name="concord",
            ),
            _component(
                "core",
                "pds-core",
                "0.6.0",
                capabilities=("shared_core",),
                purpose=None,
            ),
            _component(
                "vitrine",
                "pds-vitrine",
                "0.2.0",
                capabilities=("launchable_application",),
                purpose="Portfolio curation.",
                console_name="vitrine",
                routing=False,
            ),
        ),
    )


def _lookup(versions: dict[str, str]):
    def lookup(distribution: str) -> str:
        try:
            return versions[distribution]
        except KeyError as error:
            raise metadata.PackageNotFoundError(distribution) from error

    return lookup


def _entry_point(
    *,
    name: str,
    target: str,
    distribution: str,
    version: str,
) -> EntryPointObservation:
    return EntryPointObservation(
        group="console_scripts",
        name=name,
        target=target,
        distribution=distribution,
        distribution_version=version,
    )


def _base_versions(**overrides: str) -> dict[str, str]:
    result = {
        "paper-data-suite": "0.1.0.dev0",
        "pds-core": "0.6.0",
    }
    result.update(overrides)
    return result


def test_inventory_filters_to_launchable_applications_in_manifest_order() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(_base_versions()),
        entry_point_inventory_lookup=lambda: (),
    )

    assert tuple(item.component_id for item in inventory.applications) == (
        "concord",
        "vitrine",
    )
    assert inventory.for_component("core") is None
    assert all(
        item.status is ApplicationLaunchStatus.NOT_INSTALLED
        for item in inventory.applications
    )


def test_exact_application_with_exact_console_metadata_is_available() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(_base_versions(**{"pds-concord": "0.2.0"})),
        entry_point_inventory_lookup=lambda: (
            _entry_point(
                name="concord",
                target="concord.cli:main",
                distribution="PDS-Concord",
                version="0.2.0",
            ),
        ),
    )

    concord = inventory.for_component("concord")
    assert concord is not None
    assert concord.status is ApplicationLaunchStatus.AVAILABLE
    assert concord.installed_version == "0.2.0"
    assert concord.console_script_name == "concord"
    assert concord.console_script_target == "concord.cli:main"
    assert concord.remediation is None


def test_launchability_does_not_require_routing_profile() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(_base_versions(**{"pds-vitrine": "0.2.0"})),
        entry_point_inventory_lookup=lambda: (
            _entry_point(
                name="vitrine",
                target="vitrine.cli:main",
                distribution="pds-vitrine",
                version="0.2.0",
            ),
        ),
    )

    vitrine = inventory.for_component("vitrine")
    assert vitrine is not None
    assert vitrine.status is ApplicationLaunchStatus.AVAILABLE


def test_wrong_application_version_is_incompatible_before_entry_point_checks() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(_base_versions(**{"pds-concord": "0.3.0"})),
        entry_point_inventory_lookup=lambda: (),
    )

    concord = inventory.for_component("concord")
    assert concord is not None
    assert concord.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "0.3.0" in concord.reason
    assert "0.2.0" in concord.reason


def test_unqualified_python_blocks_an_installed_exact_application() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 15, 0),
        version_lookup=_lookup(_base_versions(**{"pds-concord": "0.2.0"})),
        entry_point_inventory_lookup=lambda: (
            _entry_point(
                name="concord",
                target="concord.cli:main",
                distribution="pds-concord",
                version="0.2.0",
            ),
        ),
    )

    concord = inventory.for_component("concord")
    assert concord is not None
    assert concord.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "Python 3.15" in concord.reason


def test_wrong_suite_version_blocks_an_installed_exact_application() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(
            {
                "paper-data-suite": "9.9.9",
                "pds-core": "0.6.0",
                "pds-concord": "0.2.0",
            }
        ),
        entry_point_inventory_lookup=lambda: (),
    )

    concord = inventory.for_component("concord")
    assert concord is not None
    assert concord.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "9.9.9" in concord.reason


def test_wrong_core_version_blocks_an_installed_exact_application() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(
            {
                "paper-data-suite": "0.1.0.dev0",
                "pds-core": "0.6.1",
                "pds-concord": "0.2.0",
            }
        ),
        entry_point_inventory_lookup=lambda: (),
    )

    concord = inventory.for_component("concord")
    assert concord is not None
    assert concord.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert "0.6.1" in concord.reason
    assert "0.6.0" in concord.reason


@pytest.mark.parametrize(
    ("observations", "reason_text"),
    [
        ((), "is missing"),
        (
            (
                _entry_point(
                    name="concord",
                    target="concord.cli:main",
                    distribution="foreign-package",
                    version="1.0.0",
                ),
            ),
            "not owned",
        ),
        (
            (
                _entry_point(
                    name="concord",
                    target="concord.cli:main",
                    distribution="pds-concord",
                    version="0.2.0",
                ),
                _entry_point(
                    name="concord",
                    target="concord.other:main",
                    distribution="pds-concord",
                    version="0.2.0",
                ),
            ),
            "duplicate definitions",
        ),
        (
            (
                _entry_point(
                    name="concord",
                    target="concord.other:main",
                    distribution="pds-concord",
                    version="0.2.0",
                ),
            ),
            "unexpected target",
        ),
        (
            (
                _entry_point(
                    name="concord",
                    target="concord.cli:main",
                    distribution="pds-concord",
                    version="0.2.0",
                ),
                _entry_point(
                    name="concord",
                    target="foreign.cli:main",
                    distribution="foreign-package",
                    version="1.0.0",
                ),
            ),
            "conflicts",
        ),
    ],
)
def test_console_metadata_failures_are_isolated_as_incompatible(
    observations: tuple[EntryPointObservation, ...],
    reason_text: str,
) -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(
            _base_versions(
                **{"pds-concord": "0.2.0", "pds-vitrine": "0.2.0"}
            )
        ),
        entry_point_inventory_lookup=lambda: observations
        + (
            _entry_point(
                name="vitrine",
                target="vitrine.cli:main",
                distribution="pds-vitrine",
                version="0.2.0",
            ),
        ),
    )

    concord = inventory.for_component("concord")
    vitrine = inventory.for_component("vitrine")
    assert concord is not None
    assert vitrine is not None
    assert concord.status is ApplicationLaunchStatus.INCOMPATIBLE
    assert reason_text in concord.reason
    assert vitrine.status is ApplicationLaunchStatus.AVAILABLE


def test_unrelated_installed_distribution_is_ignored() -> None:
    inventory = collect_application_inventory(
        _manifest(),
        python_version=(3, 11, 9),
        version_lookup=_lookup(
            _base_versions(
                **{
                    "totally-pds-looking": "1.0.0",
                }
            )
        ),
        entry_point_inventory_lookup=lambda: (
            _entry_point(
                name="mystery",
                target="mystery.cli:main",
                distribution="totally-pds-looking",
                version="1.0.0",
            ),
        ),
    )

    assert tuple(item.component_id for item in inventory.applications) == (
        "concord",
        "vitrine",
    )


def test_entry_point_inventory_failure_is_suite_level_error() -> None:
    def broken_inventory() -> tuple[EntryPointObservation, ...]:
        raise OSError("metadata store unavailable")

    with pytest.raises(ApplicationInventoryError, match="could not be inventoried"):
        collect_application_inventory(
            _manifest(),
            python_version=(3, 11, 9),
            version_lookup=_lookup(_base_versions()),
            entry_point_inventory_lookup=broken_inventory,
        )


def test_distribution_metadata_failure_is_suite_level_error() -> None:
    def broken_lookup(distribution: str) -> str:
        if distribution == "paper-data-suite":
            raise ValueError("broken metadata")
        raise metadata.PackageNotFoundError(distribution)

    with pytest.raises(ApplicationInventoryError, match="paper-data-suite"):
        collect_application_inventory(
            _manifest(),
            python_version=(3, 11, 9),
            version_lookup=broken_lookup,
            entry_point_inventory_lookup=lambda: (),
        )


def test_unavailable_status_is_reserved_for_launcher_resolution() -> None:
    assert ApplicationLaunchStatus.UNAVAILABLE.value == "UNAVAILABLE"
