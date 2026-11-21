"""Suite #20 Slice A: synthetic Core v1 attention, no real module evaluation."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsNotice,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    ModuleReadinessReport,
    invoke_module_attention,
    invoke_module_readiness,
)
from pds_core.routing_models import ModuleWorkRef

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_attention_projection import project_module_attention
from paper_data_suite.module_operations_diagnosis import (
    ModuleOperationsProfileInventory,
    ModuleOperationsProfileRow,
)
from paper_data_suite.module_operations_inventory import (
    ModuleOperationsMetadataInventory,
    ModuleOperationsMetadataRow,
)

APPROVED = tuple(item for item in APPROVED_COMPONENTS if item.launchable)
IDS = tuple(item.component_id for item in APPROVED)


def _metadata(
    *, declared: tuple[str, ...] = IDS, inspection: bool = True
) -> ModuleOperationsMetadataInventory:
    return ModuleOperationsMetadataInventory(
        applications=tuple(
            ModuleOperationsMetadataRow(
                component_id=item.component_id,
                display_name=item.display_name,
                expected_distribution=item.distribution,
                launch_state=None,
                metadata_state=(
                    "declared_unvalidated"
                    if item.component_id in declared else "not_declared"
                ),
            )
            for item in APPROVED
        ),
        unapproved_candidates=0,
        inspection_available=inspection,
    )


def _profiles(
    *, valid: tuple[str, ...] = IDS, no_attention: tuple[str, ...] = (),
    available: bool = True,
) -> ModuleOperationsProfileInventory:
    return ModuleOperationsProfileInventory(
        applications=tuple(
            ModuleOperationsProfileRow(
                component_id=item.component_id,
                display_name=item.display_name,
                expected_distribution=item.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
                profile_state=(
                    "valid" if item.component_id in valid else "profile_invalid"
                ),
                readiness_declared=True,
                attention_declared=item.component_id not in no_attention,
            )
            for item in APPROVED
        ),
        unapproved_diagnostics=0,
        diagnosis_available=available,
    )


def _invoke(
    owner: str = "scoreform",
    *, report: ModuleAttentionReport | None = None,
    request: ModuleOperationsRequest | None = None,
    failure: bool = False,
):
    def provide(_: ModuleOperationsRequest) -> ModuleAttentionReport:
        if failure:
            raise ValueError("PRIVATE_STUDENT_DO_NOT_LEAK")
        return report or ModuleAttentionReport(evaluation="evaluated")

    profile = ModuleOperationsProfile(
        module_id=owner,
        supported_core_operations_contract_versions=frozenset({"1"}),
        attention_provider=provide,
    )
    return invoke_module_attention(profile, request or ModuleOperationsRequest())


def _project(*results: object, request: ModuleOperationsRequest | None = None,
             metadata: ModuleOperationsMetadataInventory | None = None,
             profiles: ModuleOperationsProfileInventory | None = None):
    return project_module_attention(
        metadata_inventory=metadata if metadata is not None else _metadata(),
        profile_inventory=profiles if profiles is not None else _profiles(),
        request=request if request is not None else ModuleOperationsRequest(),
        invocation_results=results,
    )


def test_six_approved_rows_without_implicit_evaluation() -> None:
    projected = _project()
    assert tuple(x.module_id for x in projected.modules) == IDS
    assert projected.coverage == "none_evaluated"
    assert projected.evaluated_modules == 0
    assert all(x.state == "not_evaluated" and not x.items for x in projected.modules)
    assert projected.for_module("core") is None


def test_no_profile_diagnosis_does_not_imply_attention() -> None:
    projection = project_module_attention(
        metadata_inventory=_metadata(), profile_inventory=None,
        request=ModuleOperationsRequest(),
    )
    assert all(x.state == "profile_not_checked" for x in projection.modules)
    assert projection.coverage == "none_evaluated"


def test_missing_metadata_and_failed_census_remain_unknown() -> None:
    without = _project(metadata=_metadata(declared=("scoreform",)))
    assert without.for_module("scoreform").state == "not_evaluated"
    assert without.for_module("quillan").state == "not_declared"
    failed = _project(metadata=_metadata(inspection=False))
    assert all(x.state == "metadata_unavailable" for x in failed.modules)


def test_profile_not_valid_and_absent_capability() -> None:
    profiles = _profiles(valid=("scoreform",), no_attention=("scoreform",))
    projection = _project(profiles=profiles)
    assert projection.for_module("scoreform").state == "capability_absent"
    assert projection.for_module("quillan").state == "profile_unqualified"
    assert projection.coverage == "none_evaluated"


def test_valid_capability_absent_core_result_does_not_mean_zero() -> None:
    profile = ModuleOperationsProfile(
        module_id="scoreform",
        supported_core_operations_contract_versions=frozenset({"1"}),
        readiness_provider=lambda req: ModuleReadinessReport(
            evaluation="evaluated", ready=True
        ),
    )
    absent = invoke_module_attention(profile, ModuleOperationsRequest())
    projection = _project(
        absent, profiles=_profiles(no_attention=("scoreform",))
    )
    assert projection.for_module("scoreform").state == "capability_absent"
    assert projection.evaluated_modules == 0
    invalid = _project(absent)
    assert invalid.for_module("scoreform").state == "result_invalid"


def test_successful_empty_vs_unavailable_are_separate() -> None:
    empty = _project(_invoke())
    unknown = _project(_invoke(report=ModuleAttentionReport(evaluation="unavailable")))
    assert empty.for_module("scoreform").state == "evaluated_empty"
    assert empty.coverage == "partial" and empty.evaluated_modules == 1
    assert unknown.for_module("scoreform").state == "evaluation_unavailable"
    assert unknown.coverage == "none_evaluated"
    assert unknown.evaluated_modules == 0


def test_owner_counts_preserved_no_cross_module_total_or_priority() -> None:
    some = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(
            ModuleAttentionSummary(code="review", label="Safe", count=None),
            ModuleAttentionSummary(code="pending", label="Safe", count=0),
        ),
    )
    projection = _project(_invoke(report=some))
    row = projection.for_module("scoreform")
    assert row is not None and row.state == "evaluated_items"
    assert [x.count for x in row.items] == [None, 0]
    assert not hasattr(projection, "total_count")
    assert not hasattr(row.items[0], "urgency")


def test_private_strings_discarded_from_public_projection() -> None:
    secret = "PRIVATE_STUDENT_DO_NOT_LEAK"
    report = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(ModuleAttentionSummary(
            code="review", label=secret, count=2,
            class_id="class_a",
            work_ref=ModuleWorkRef(
                module_id="scoreform", class_id="class_a", work_id="work_private"
            ),
            action=ModuleOwnerActionRef(
                module_id="scoreform", action_id="private_action"
            ),
        ),),
        notices=(ModuleOperationsNotice(code="notice", summary=secret),),
    )
    projection = _project(_invoke(report=report))
    row = projection.for_module("scoreform")
    assert row is not None and row.notice_count == 1
    assert row.items[0].action is not None
    assert row.items[0].code == "review"
    assert secret not in repr(projection)
    assert "work_private" not in repr(projection)
    assert "private_action" not in repr(projection)


def test_cross_class_provided_result_refused_at_projection_boundary() -> None:
    report = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(ModuleAttentionSummary(
            code="review", label="Synthetic", class_id="class_a"
        ),),
    )
    result = _invoke(report=report, request=ModuleOperationsRequest())
    scoped = _project(result, request=ModuleOperationsRequest(class_id="class_b"))
    assert scoped.for_module("scoreform").state == "result_invalid"
    assert not scoped.for_module("scoreform").items


def test_wrong_owner_action_is_not_promoted() -> None:
    report = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(ModuleAttentionSummary(
            code="review", label="Safe",
            action=ModuleOwnerActionRef(module_id="portia", action_id="open"),
        ),),
    )
    result = _invoke(report=report)
    assert result.code == "module_operations.result_invalid"
    projection = _project(result)
    assert projection.for_module("scoreform").state == "result_invalid"


def test_failed_and_invalid_provider_do_not_erase_healthy_neighbor() -> None:
    healthy = _invoke("quillan")
    failed = _invoke("scoreform", failure=True)
    projection = _project(failed, healthy)
    assert projection.for_module("scoreform").state == "provider_failed"
    assert projection.for_module("quillan").state == "evaluated_empty"
    assert projection.coverage == "partial"
    assert "PRIVATE_STUDENT_DO_NOT_LEAK" not in repr(projection)


def test_duplicate_owner_and_unapproved_result_are_non_authorizing() -> None:
    valid = _invoke()
    projection = _project(valid, valid, SimpleNamespace(module_id="unknown"))
    assert projection.for_module("scoreform").state == "result_invalid"
    assert projection.for_module("unknown") is None
    assert projection.unapproved_result_count == 1


def test_invalid_result_shape_and_wrong_capability_fail_closed() -> None:
    fake = SimpleNamespace(module_id="scoreform", message="SECRET")
    result = _project(fake)
    assert result.for_module("scoreform").state == "result_invalid"
    assert "SECRET" not in repr(result)
    profile = ModuleOperationsProfile(
        module_id="scoreform",
        supported_core_operations_contract_versions=frozenset({"1"}),
        readiness_provider=lambda r: ModuleReadinessReport(
            evaluation="evaluated", ready=True
        ),
    )
    wrong = invoke_module_readiness(profile, ModuleOperationsRequest())
    assert _project(wrong).for_module("scoreform").state == "result_invalid"


def test_six_evaluated_producers_are_covered_but_never_summed() -> None:
    results = tuple(_invoke(owner) for owner in IDS)
    projection = _project(*results)
    assert projection.coverage == "complete"
    assert projection.evaluated_modules == 6
    assert all(row.state == "evaluated_empty" for row in projection.modules)


def test_corrupted_inventory_and_conflicting_profile_cannot_authorize() -> None:
    meta = _metadata()
    duplicate = replace(meta, applications=meta.applications + (meta.applications[0],))
    projection = _project(metadata=duplicate)
    assert projection.for_module("scoreform").state == "metadata_unqualified"
    assert projection.for_module("quillan").state == "not_evaluated"
    profiles = _profiles()
    bad = replace(profiles.applications[0], expected_distribution="unapproved")
    mismatch = replace(profiles, applications=(bad,) + profiles.applications[1:])
    assert (
        _project(profiles=mismatch).for_module("scoreform").state
        == "profile_unqualified"
    )


def test_unqualified_result_cannot_override_profile_evidence() -> None:
    result = _invoke()
    projection = _project(result, profiles=_profiles(valid=()))
    assert projection.for_module("scoreform").state == "result_invalid"
    assert projection.evaluated_modules == 0


def test_bad_input_limited_and_safe_error() -> None:
    with pytest.raises(ValueError, match="attention_input_limit"):
        _project(*(SimpleNamespace(module_id="rogue") for _ in range(513)))
    with pytest.raises(TypeError, match="invalid_metadata_inventory"):
        project_module_attention(
            metadata_inventory=object(),  # type: ignore[arg-type]
            profile_inventory=None, request=ModuleOperationsRequest(),
        )
