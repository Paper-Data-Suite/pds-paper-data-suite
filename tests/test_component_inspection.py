from __future__ import annotations

from importlib import metadata
from types import SimpleNamespace

from paper_data_suite.compatibility import (
    ComponentCompatibility,
    ReleaseArtifact,
)
from paper_data_suite.component_inspection import (
    EntryPointObservation,
    component_is_suite_qualified,
    installed_entry_point_inventory,
    lookup_distribution_version,
    normalize_entry_point_owner,
)


def _component() -> ComponentCompatibility:
    return ComponentCompatibility(
        component_id="sample",
        display_name="Sample",
        repository="Paper-Data-Suite/pds-sample",
        distribution="pds-sample",
        import_name="sample",
        required=False,
        compatibility_status="supported",
        version="1.2.3",
        requires_python=">=3.11",
        release=ReleaseArtifact(
            tag="v1.2.3",
            wheel="pds_sample-1.2.3-py3-none-any.whl",
            sha256="0" * 64,
        ),
        capabilities=("launchable_application",),
        entry_points=(),
        external_prerequisites=(),
        purpose="Synthetic application used by metadata tests.",
    )


def _lookup(versions: dict[str, str]):
    def lookup(distribution: str) -> str:
        try:
            return versions[distribution]
        except KeyError as error:
            raise metadata.PackageNotFoundError(distribution) from error

    return lookup


def test_lookup_distribution_version_distinguishes_absence() -> None:
    lookup = _lookup({"pds-sample": "1.2.3"})

    assert lookup_distribution_version("pds-sample", lookup) == "1.2.3"
    assert lookup_distribution_version("missing", lookup) is None


def test_component_suite_qualification_requires_exact_version() -> None:
    component = _component()

    assert component_is_suite_qualified(
        component,
        version_lookup=_lookup({"pds-sample": "1.2.3"}),
    )
    assert not component_is_suite_qualified(
        component,
        version_lookup=_lookup({"pds-sample": "1.2.4"}),
    )
    assert not component_is_suite_qualified(
        component,
        version_lookup=_lookup({}),
    )


def test_normalize_entry_point_owner_is_bounded() -> None:
    assert normalize_entry_point_owner("PDS.Sample") == "pds-sample"
    assert normalize_entry_point_owner("bad owner/name") is None


def test_entry_point_inventory_is_metadata_only_and_deterministic() -> None:
    alpha = SimpleNamespace(
        metadata={"Name": "PDS-Alpha"},
        version="2.0.0",
        entry_points=(
            SimpleNamespace(
                group="console_scripts",
                name="zeta",
                value="alpha.cli:zeta",
            ),
            SimpleNamespace(
                group="console_scripts",
                name="alpha",
                value="alpha.cli:main",
            ),
        ),
    )
    beta = SimpleNamespace(
        metadata={"Name": "pds_beta"},
        version="1.0.0",
        entry_points=(
            SimpleNamespace(
                group="paper_data_suite.modules",
                name="beta",
                value="beta.pds_module:get_module_profile",
            ),
        ),
    )

    inventory = installed_entry_point_inventory(lambda: (beta, alpha))

    assert inventory == (
        EntryPointObservation(
            group="console_scripts",
            name="alpha",
            target="alpha.cli:main",
            distribution="PDS-Alpha",
            distribution_version="2.0.0",
        ),
        EntryPointObservation(
            group="console_scripts",
            name="zeta",
            target="alpha.cli:zeta",
            distribution="PDS-Alpha",
            distribution_version="2.0.0",
        ),
        EntryPointObservation(
            group="paper_data_suite.modules",
            name="beta",
            target="beta.pds_module:get_module_profile",
            distribution="pds_beta",
            distribution_version="1.0.0",
        ),
    )


def test_entry_point_inventory_skips_unreadable_distribution_metadata() -> None:
    broken = SimpleNamespace(metadata={}, version="1.0.0", entry_points=())

    assert installed_entry_point_inventory(lambda: (broken,)) == ()
