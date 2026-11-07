"""Suite #16 Slice 1: metadata observation never licenses provider execution."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Iterable

import pytest

from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_operations_inventory import (
    collect_module_operations_metadata,
)


@dataclass(frozen=True)
class EntryPoint:
    provider_kind: str = "module_operations"
    entry_point_group: str = "paper_data_suite.module_operations"
    entry_point_name: str = "scoreform"
    entry_point_target: str = "scoreform.pds_operations:get_module_operations_profile"
    distribution_name: str | None = "scoreform"


def _rows(*items: object):
    return collect_module_operations_metadata(
        inspect=lambda: items  # type: ignore[arg-type]
    )


def _declared_ids() -> list[str]:
    return [row.component_id for row in _rows().applications]


def _launch(
    component_id: str,
    status: ApplicationLaunchStatus,
) -> ApplicationInventory:
    component = next(
        value for value in APPROVED_COMPONENTS
        if value.component_id == component_id
    )
    return ApplicationInventory((ApplicationObservation(
        component_id=component_id,
        display_name=component.display_name,
        purpose="Synthetic test only",
        distribution=component.distribution,
        qualified_version="0.0.0",
        installed_version=(
            "0.0.0" if status is not ApplicationLaunchStatus.NOT_INSTALLED else None
        ),
        console_script_name=component.console_scripts[0].name,
        console_script_target=component.console_scripts[0].target,
        status=status,
        reason="synthetic fixture",
    ),))


def test_all_six_approved_modules_present_in_fixed_registry_order() -> None:
    assert _declared_ids() == [
        "scoreform", "quillan", "concord", "meridian", "vitrine", "portia"
    ]
    result = _rows()
    assert result.inspection_available
    assert result.unapproved_candidates == 0
    assert all(x.metadata_state == "not_declared" for x in result.applications)
    assert result.for_component("core") is None
    assert result.for_component("foreign") is None


def test_metadata_is_declared_but_never_validates_a_profile_or_capability() -> None:
    result = _rows(EntryPoint())
    row = result.for_component("scoreform")
    assert row is not None
    assert row.metadata_state == "declared_unvalidated"
    assert row.readiness_state == "not_evaluated"
    assert row.attention_state == "not_evaluated"
    assert not row.profile_validated
    assert not row.provenance_qualified
    assert row.launch_state is None


@pytest.mark.parametrize("owner", ["other-project", None, "scoreform-other"])
def test_metadata_foreign_or_unknown_distribution_is_not_approved(
    owner: str | None,
) -> None:
    row = _rows(EntryPoint(distribution_name=owner)).for_component("scoreform")
    assert row is not None
    assert row.metadata_state == "owner_mismatch"


def test_distribution_name_uses_pep503_normalization_only_for_comparison() -> None:
    row = _rows(EntryPoint(
        entry_point_name="concord",
        entry_point_target="concord.pds_operations:get_module_operations_profile",
        distribution_name="PDS_CONCORD",
    )).for_component("concord")
    assert row is not None
    assert row.metadata_state == "declared_unvalidated"
    assert not row.provenance_qualified


def test_duplicate_same_name_is_ambiguous_even_if_one_candidate_looks_valid() -> None:
    row = _rows(EntryPoint(), EntryPoint(distribution_name="foreign")).for_component(
        "scoreform"
    )
    assert row is not None
    assert row.metadata_state == "ambiguous"


def test_malformed_metadata_for_approved_name_is_not_treated_as_valid() -> None:
    row = _rows(EntryPoint(entry_point_group="foreign.group")).for_component(
        "scoreform"
    )
    assert row is not None
    assert row.metadata_state == "invalid_metadata"
    row = _rows(SimpleNamespace(entry_point_name="scoreform")).for_component(
        "scoreform"
    )
    assert row is not None
    assert row.metadata_state == "invalid_metadata"


def test_unapproved_candidates_counted_not_promoted_into_inventory() -> None:
    result = _rows(
        EntryPoint(entry_point_name="surprise", distribution_name="surprise"),
        EntryPoint(entry_point_name="other", distribution_name="other"),
    )
    assert result.unapproved_candidates == 2
    assert len(result.applications) == 6
    assert all(x.metadata_state == "not_declared" for x in result.applications)


def test_inspection_exception_cannot_be_misreported_as_no_providers() -> None:
    def failed() -> Iterable[EntryPoint]:
        raise OSError("sensitive/path/private student contents")

    result = collect_module_operations_metadata(inspect=failed)
    assert not result.inspection_available
    assert result.unapproved_candidates == 0
    assert all(
        x.metadata_state == "inspection_unavailable" for x in result.applications
    )
    assert "private" not in repr(result)


def test_abnormally_large_metadata_inventory_fails_closed() -> None:
    result = collect_module_operations_metadata(inspect=lambda: [EntryPoint()] * 513)
    assert not result.inspection_available
    assert all(
        x.metadata_state == "inspection_unavailable" for x in result.applications
    )


@pytest.mark.parametrize("status", list(ApplicationLaunchStatus))
def test_launch_and_provider_states_are_orthogonal(
    status: ApplicationLaunchStatus,
) -> None:
    inventory = _launch("quillan", status)
    result = collect_module_operations_metadata(
        launch_inventory=inventory,
        inspect=lambda: (),
    )
    row = result.for_component("quillan")
    assert row is not None
    assert row.launch_state is status
    assert row.metadata_state == "not_declared"
    assert row.readiness_state == "not_evaluated"
    assert row.attention_state == "not_evaluated"


def test_declared_operations_does_not_authorize_launch() -> None:
    result = collect_module_operations_metadata(
        inspect=lambda: (EntryPoint(),),
        launch_inventory=_launch("scoreform", ApplicationLaunchStatus.INCOMPATIBLE),
    )
    row = result.for_component("scoreform")
    assert row is not None
    assert row.metadata_state == "declared_unvalidated"
    assert row.launch_state is ApplicationLaunchStatus.INCOMPATIBLE


def test_injected_metadata_path_calls_only_the_supplied_reader() -> None:
    count = 0

    def inspect() -> Iterable[EntryPoint]:
        nonlocal count
        count += 1
        return (EntryPoint(),)

    result = collect_module_operations_metadata(inspect=inspect)
    assert count == 1
    assert result.inspection_available


def test_default_path_requests_only_core_metadata_not_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.module_operations_inventory as mod

    called: list[str] = []

    def metadata_only(*, provider_kind: str) -> tuple[EntryPoint, ...]:
        called.append(provider_kind)
        return (EntryPoint(),)

    def importer(name: str) -> object:
        called.append(name)
        return SimpleNamespace(inspect_core_provider_entry_points=metadata_only)

    monkeypatch.setattr(mod, "import_module", importer)
    result = collect_module_operations_metadata()
    scoreform = result.for_component("scoreform")
    assert scoreform is not None
    assert scoreform.metadata_state == "declared_unvalidated"
    assert called == ["pds_core.provider_diagnostics", "module_operations"]


def test_broken_core_discovery_does_not_import_producers_or_expose_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_data_suite.module_operations_inventory as mod

    called: list[str] = []

    def importer(name: str) -> object:
        called.append(name)
        raise ModuleNotFoundError("private student data")

    monkeypatch.setattr(mod, "import_module", importer)
    result = collect_module_operations_metadata()
    assert not result.inspection_available
    assert called == ["pds_core.provider_diagnostics"]
    assert "student" not in repr(result)


def test_broken_metadata_accessor_is_isolated_not_executed() -> None:
    class FaultyMetadata:
        @property
        def entry_point_name(self) -> str:
            raise RuntimeError("private record trace")

    result = _rows(FaultyMetadata())
    assert result.inspection_available
    assert result.unapproved_candidates == 1
    assert all(row.metadata_state == "not_declared" for row in result.applications)
    assert "private" not in repr(result)
