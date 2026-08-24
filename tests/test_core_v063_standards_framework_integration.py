from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.school_years import open_school_year
from pds_core.standards import (
    StandardsLibrary,
    load_workspace_standards_library,
    write_workspace_standards_library,
)
from pds_core.starter_standards import (
    list_starter_standards_packs,
    load_starter_standards_library,
)

from paper_data_suite.classroom_apply import (
    ClassroomSetupPreflightError,
    execute_shared_setup_plan,
    load_core_classroom_apply_services,
)
from paper_data_suite.classroom_planning import (
    SchoolYearDisposition,
    SchoolYearPlan,
    SharedSetupPlan,
    StandardsAction,
    load_core_classroom_planning_services,
    plan_starter_standards,
)
from paper_data_suite.classroom_setup import assess_shared_setup

SCHOOL_YEAR = "2026-2027"
NOW = datetime(2026, 8, 24, 20, 0, tzinfo=UTC)

PACK_EXPECTATIONS = {
    "ap_csp_fall_2023": (95, 3, 1),
    "njsls_clks_2020": (301, 4, 1),
    "njsls_csdt_2020": (163, 2, 1),
    "njsls_ela_2023": (135, 3, 1),
}


def _activate_workspace(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    root.mkdir(parents=True)
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", str(root))
    open_school_year(
        root,
        SCHOOL_YEAR,
        opened_at=NOW,
        overwrite=False,
    )


def _existing_school_year_plan() -> SchoolYearPlan:
    return SchoolYearPlan(
        requested_school_year=SCHOOL_YEAR,
        disposition=SchoolYearDisposition.EXISTING_MATCH,
        reason="Synthetic Core v0.6.3 qualification workspace is already open.",
    )


def _plan_and_apply_pack(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    pack_id: str,
) -> tuple[object, StandardsLibrary]:
    _activate_workspace(monkeypatch, root)

    planning = load_core_classroom_planning_services()
    apply = load_core_classroom_apply_services()
    reviewed = assess_shared_setup(services=planning.readers)
    standards_plan = plan_starter_standards(
        reviewed,
        pack_id,
        services=planning,
    )
    plan = SharedSetupPlan(
        school_year=_existing_school_year_plan(),
        classes=(),
        rosters=(),
        standards=standards_plan,
        academic_periods=None,
    )

    result = execute_shared_setup_plan(
        reviewed,
        plan,
        services=apply,
        clock=lambda: NOW,
    )
    assert result.changed_actions == (f"standards:INSTALL:{pack_id}",)
    return standards_plan, load_workspace_standards_library(root)


def test_exact_core_v063_starter_pack_inventory_is_release_qualified() -> None:
    packs = list_starter_standards_packs()
    by_id = {pack.pack_id: pack for pack in packs}

    assert tuple(by_id) == tuple(PACK_EXPECTATIONS)
    assert sum(pack.standard_count for pack in packs) == 694
    assert sum(pack.profile_count for pack in packs) == 12
    assert sum(pack.framework_count for pack in packs) == 4

    for pack_id, expected in PACK_EXPECTATIONS.items():
        standard_count, profile_count, framework_count = expected
        metadata = by_id[pack_id]
        library = load_starter_standards_library(pack_id)

        assert metadata.standard_count == standard_count
        assert metadata.profile_count == profile_count
        assert metadata.framework_count == framework_count
        assert len(library.standards) == standard_count
        assert len(library.profiles) == profile_count
        assert len(library.frameworks) == framework_count
        assert metadata.framework_ids == tuple(
            framework.framework_id for framework in library.frameworks
        )


@pytest.mark.parametrize(
    ("pack_id", "expected_counts"),
    tuple(PACK_EXPECTATIONS.items()),
)
def test_each_core_v063_pack_plans_applies_and_reruns_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_id: str,
    expected_counts: tuple[int, int, int],
) -> None:
    root = tmp_path / pack_id
    standards_plan, installed = _plan_and_apply_pack(
        monkeypatch,
        root,
        pack_id,
    )

    standards_count, profile_count, framework_count = expected_counts
    assert standards_plan.action is StandardsAction.INSTALL
    assert standards_plan.standards_to_add == standards_count
    assert standards_plan.profiles_to_add == profile_count
    assert standards_plan.frameworks_to_add == framework_count
    assert standards_plan.standard_conflicts == ()
    assert standards_plan.profile_conflicts == ()
    assert standards_plan.framework_conflicts == ()

    assert len(installed.standards) == standards_count
    assert len(installed.profiles) == profile_count
    assert len(installed.frameworks) == framework_count

    planning = load_core_classroom_planning_services()
    current = assess_shared_setup(services=planning.readers)
    rerun = plan_starter_standards(current, pack_id, services=planning)

    assert rerun.action is StandardsAction.KEEP
    assert rerun.standards_to_add == 0
    assert rerun.profiles_to_add == 0
    assert rerun.frameworks_to_add == 0
    assert rerun.standards_identical == standards_count
    assert rerun.profiles_identical == profile_count
    assert rerun.frameworks_identical == framework_count


def test_v062_ela_workspace_upgrades_additively_through_suite_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "ela-upgrade"
    _activate_workspace(monkeypatch, root)

    released = load_starter_standards_library("njsls_ela_2023")
    old_profiles = tuple(
        profile
        for profile in released.profiles
        if profile.profile_id != "english11_2023_njsls_ela"
    )
    assert len(released.standards) == 135
    assert tuple(profile.profile_id for profile in old_profiles) == (
        "english10_2023_njsls_ela",
        "english12_2023_njsls_ela",
    )

    v062_library = StandardsLibrary(
        standards=released.standards,
        profiles=old_profiles,
        frameworks=(),
    )
    write_workspace_standards_library(
        root,
        v062_library,
        overwrite=False,
    )
    before_bytes = (root / "standards" / "library.json").read_bytes()

    planning = load_core_classroom_planning_services()
    apply = load_core_classroom_apply_services()
    reviewed = assess_shared_setup(services=planning.readers)
    standards_plan = plan_starter_standards(
        reviewed,
        "njsls_ela_2023",
        services=planning,
    )

    assert standards_plan.action is StandardsAction.INSTALL
    assert standards_plan.standards_to_add == 0
    assert standards_plan.standards_identical == 135
    assert standards_plan.profiles_to_add == 1
    assert standards_plan.profiles_identical == 2
    assert standards_plan.frameworks_to_add == 1
    assert standards_plan.frameworks_identical == 0
    assert standards_plan.standard_conflicts == ()
    assert standards_plan.profile_conflicts == ()
    assert standards_plan.framework_conflicts == ()

    plan = SharedSetupPlan(
        school_year=_existing_school_year_plan(),
        classes=(),
        rosters=(),
        standards=standards_plan,
        academic_periods=None,
    )
    result = execute_shared_setup_plan(
        reviewed,
        plan,
        services=apply,
        clock=lambda: NOW,
    )
    assert result.changed_actions == ("standards:INSTALL:njsls_ela_2023",)

    upgraded = load_workspace_standards_library(root)
    assert len(upgraded.standards) == 135
    assert upgraded.profiles[:2] == old_profiles
    assert tuple(profile.profile_id for profile in upgraded.profiles) == (
        "english10_2023_njsls_ela",
        "english12_2023_njsls_ela",
        "english11_2023_njsls_ela",
    )
    assert tuple(framework.framework_id for framework in upgraded.frameworks) == (
        "njsls_ela_2023",
    )
    assert (root / "standards" / "library.json").read_bytes() != before_bytes

    current = assess_shared_setup(services=planning.readers)
    rerun = plan_starter_standards(
        current,
        "njsls_ela_2023",
        services=planning,
    )
    assert rerun.action is StandardsAction.KEEP
    assert rerun.standards_identical == 135
    assert rerun.profiles_identical == 3
    assert rerun.frameworks_identical == 1

    stable_bytes = (root / "standards" / "library.json").read_bytes()
    no_op_plan = SharedSetupPlan(
        school_year=_existing_school_year_plan(),
        classes=(),
        rosters=(),
        standards=rerun,
        academic_periods=None,
    )
    no_op = execute_shared_setup_plan(
        current,
        no_op_plan,
        services=apply,
        clock=lambda: NOW,
    )
    assert no_op.changed_actions == ()
    assert (root / "standards" / "library.json").read_bytes() == stable_bytes


def test_real_core_framework_only_conflict_blocks_suite_apply_without_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "framework-conflict"
    _activate_workspace(monkeypatch, root)

    released = load_starter_standards_library("njsls_ela_2023")
    original_framework = released.frameworks[0]
    conflicting_framework = replace(
        original_framework,
        title=original_framework.title + " synthetic conflicting title",
    )
    conflicting_library = StandardsLibrary(
        standards=released.standards,
        profiles=released.profiles,
        frameworks=(conflicting_framework,),
    )
    write_workspace_standards_library(
        root,
        conflicting_library,
        overwrite=False,
    )
    library_path = root / "standards" / "library.json"
    before = library_path.read_bytes()

    planning = load_core_classroom_planning_services()
    reviewed = assess_shared_setup(services=planning.readers)
    standards_plan = plan_starter_standards(
        reviewed,
        "njsls_ela_2023",
        services=planning,
    )

    assert standards_plan.action is StandardsAction.REFUSE
    assert standards_plan.standard_conflicts == ()
    assert standards_plan.profile_conflicts == ()
    assert standards_plan.framework_conflicts == ("njsls_ela_2023",)
    assert standards_plan.blocks_apply is True

    plan = SharedSetupPlan(
        school_year=_existing_school_year_plan(),
        classes=(),
        rosters=(),
        standards=standards_plan,
        academic_periods=None,
    )
    with pytest.raises(
        ClassroomSetupPreflightError,
        match="blocking conflict",
    ):
        execute_shared_setup_plan(
            reviewed,
            plan,
            services=load_core_classroom_apply_services(),
            clock=lambda: NOW,
        )

    assert library_path.read_bytes() == before
    current = load_workspace_standards_library(root)
    assert current == conflicting_library
