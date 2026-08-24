from __future__ import annotations

from importlib import import_module, metadata

from pds_core import module_operations, provider_diagnostics, starter_standards


def test_core_v063_release_metadata_and_required_modules_are_qualified() -> None:
    distribution = metadata.distribution("pds-core")

    assert distribution.version == "0.6.3"
    requirements = tuple(distribution.requires or ())
    assert requirements
    assert all('extra == "dev"' in requirement for requirement in requirements)

    console_scripts = {
        entry_point.name: entry_point.value
        for entry_point in distribution.entry_points
        if entry_point.group == "console_scripts"
    }
    assert console_scripts == {
        "core": "pds_core.core_menu:main",
        "pds-core": "pds_core.cli:main",
    }

    for module_name in (
        "pds_core.roster_imports",
        "pds_core.provider_diagnostics",
        "pds_core.module_operations",
        "pds_core.cli_support.roster_imports",
    ):
        assert import_module(module_name) is not None


def test_core_v063_provider_diagnostic_surface_is_available() -> None:
    assert callable(provider_diagnostics.inspect_core_provider_entry_points)
    assert callable(provider_diagnostics.diagnose_core_providers)


def test_core_v063_module_operations_contract_is_v1_and_capabilities_are_distinct(
) -> None:
    assert module_operations.MODULE_OPERATIONS_CONTRACT_VERSION == "1"
    assert (
        module_operations.MODULE_OPERATIONS_ENTRY_POINT_GROUP
        == "paper_data_suite.module_operations"
    )
    assert callable(module_operations.invoke_module_readiness)
    assert callable(module_operations.invoke_module_attention)
    assert (
        module_operations.invoke_module_readiness
        is not module_operations.invoke_module_attention
    )


def test_core_v063_framework_aware_starter_surface_is_qualified() -> None:
    packs = starter_standards.list_starter_standards_packs()
    by_id = {pack.pack_id: pack for pack in packs}

    assert tuple(by_id) == (
        "ap_csp_fall_2023",
        "njsls_clks_2020",
        "njsls_csdt_2020",
        "njsls_ela_2023",
    )
    assert sum(pack.standard_count for pack in packs) == 694
    assert sum(pack.profile_count for pack in packs) == 12
    assert sum(pack.framework_count for pack in packs) == 4
    assert all(pack.framework_count == 1 for pack in packs)

    for pack_id, metadata_value in by_id.items():
        library = starter_standards.load_starter_standards_library(pack_id)
        assert len(library.frameworks) == 1
        assert library.frameworks[0].framework_id in metadata_value.framework_ids
