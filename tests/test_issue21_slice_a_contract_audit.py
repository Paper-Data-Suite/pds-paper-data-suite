"""Suite #21 Slice A: tagged-contract GREEN witnesses and explicit RED gates.

This is deliberately synthetic, with no installed producer callback or private
workspace read. The xfail marks a real Core 0.6.6 public API dependency; it
does not qualify a workaround or an installed producer.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core import provider_diagnostics
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsNotice,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    invoke_module_attention,
)

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_attention_label_policy import (
    GENERIC_ATTENTION_LABEL,
    label_for_attention_category,
)
from paper_data_suite.module_attention_projection import project_module_attention
from paper_data_suite.module_attention_rendering import (
    filter_attention_projection,
    format_attention_display,
)
from paper_data_suite.module_operations_diagnosis import (
    ModuleOperationsProfileInventory,
    ModuleOperationsProfileRow,
)
from paper_data_suite.module_operations_inventory import (
    ModuleOperationsMetadataInventory,
    ModuleOperationsMetadataRow,
    collect_module_operations_metadata,
)

APPROVED = tuple(item for item in APPROVED_COMPONENTS if item.launchable)
OWNERS = tuple(item.component_id for item in APPROVED)
PRIVATE = "private_student_source_never_display"


def _metadata() -> ModuleOperationsMetadataInventory:
    return ModuleOperationsMetadataInventory(
        applications=tuple(
            ModuleOperationsMetadataRow(
                component_id=item.component_id,
                display_name=item.display_name,
                expected_distribution=item.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
            )
            for item in APPROVED
        ),
        unapproved_candidates=0,
        inspection_available=True,
    )


def _profiles() -> ModuleOperationsProfileInventory:
    return ModuleOperationsProfileInventory(
        applications=tuple(
            ModuleOperationsProfileRow(
                component_id=item.component_id,
                display_name=item.display_name,
                expected_distribution=item.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
                profile_state="valid",
                readiness_declared=True,
                attention_declared=True,
            )
            for item in APPROVED
        ),
        unapproved_diagnostics=0,
        diagnosis_available=True,
    )


def _invoke(
    owner: str,
    report: ModuleAttentionReport,
    *,
    request: ModuleOperationsRequest | None = None,
):
    return invoke_module_attention(
        ModuleOperationsProfile(
            module_id=owner,
            supported_core_operations_contract_versions=frozenset({"1"}),
            attention_provider=lambda _: report,
        ),
        request or ModuleOperationsRequest(),
    )


def _project(*results: object, request: ModuleOperationsRequest | None = None):
    return project_module_attention(
        metadata_inventory=_metadata(),
        profile_inventory=_profiles(),
        request=request or ModuleOperationsRequest(),
        invocation_results=results,
    )


def test_source_census_is_not_a_provider_factory_or_attention_call() -> None:
    """Metadata can look valid while its .load must remain untouched."""
    dangerous = SimpleNamespace(
        provider_kind="module_operations",
        entry_point_group="paper_data_suite.module_operations",
        entry_point_name="scoreform",
        entry_point_target="scoreform.pds_operations:get_module_operations_profile",
        distribution_name="scoreform",
    )
    result = collect_module_operations_metadata(inspect=lambda: (dangerous,))
    assert result.for_component("scoreform").metadata_state == "declared_unvalidated"
    assert result.for_component("scoreform").attention_state == "not_evaluated"
    assert result.for_component("scoreform").provenance_qualified is False
    assert result.for_component("quillan").metadata_state == "not_declared"


def test_duplicate_candidates_cannot_authorize_identity() -> None:
    candidate = SimpleNamespace(
        provider_kind="module_operations",
        entry_point_group="paper_data_suite.module_operations",
        entry_point_name="scoreform",
        entry_point_target="scoreform.pds_operations:get_module_operations_profile",
        distribution_name="scoreform",
    )
    inventory = collect_module_operations_metadata(
        inspect=lambda: (candidate, candidate)
    )
    assert inventory.for_component("scoreform").metadata_state == "ambiguous"
    assert inventory.for_component("quillan").metadata_state == "not_declared"


def test_core_v1_diagnostic_public_signature_is_not_owner_selected() -> None:
    """GREEN evidence for the current API gap, not permission to use internals."""
    parameters = inspect.signature(
        provider_diagnostics.diagnose_core_providers
    ).parameters
    assert tuple(parameters) == ("provider_kind",)
    assert "entry_point_name" not in parameters


@pytest.mark.xfail(
    strict=True,
    reason="Core v0.6.6 has no public exact-owner scoped profile diagnosis",
)
def test_red_public_core_diagnostic_can_target_single_approved_owner() -> None:
    """RED: do not replace this with broad diagnose_core_providers()."""
    parameters = inspect.signature(
        provider_diagnostics.diagnose_core_providers
    ).parameters
    assert "entry_point_name" in parameters


def test_neutral_core_request_allows_missing_workspace_so_not_authorization() -> None:
    """Demonstrates why Suite #21 must reject missing context before invocation."""
    called: list[ModuleOperationsRequest] = []

    def unsafe_if_admitted(req: ModuleOperationsRequest) -> ModuleAttentionReport:
        called.append(req)
        return ModuleAttentionReport(evaluation="evaluated")

    request = ModuleOperationsRequest()
    assert request.workspace_root is None
    result = invoke_module_attention(
        ModuleOperationsProfile(
            module_id="scoreform",
            supported_core_operations_contract_versions=frozenset({"1"}),
            attention_provider=unsafe_if_admitted,
        ),
        request,
    )
    assert result.code == "module_operations.evaluated"
    assert called == [request]
    # This is intentionally not an authorized Suite #21 execution seam.


def test_partial_with_empty_report_is_not_whole_source_clearance() -> None:
    partial = ModuleAttentionReport(
        evaluation="evaluated",
        notices=(
            ModuleOperationsNotice(
                code="scoreform_attention_partial", summary=PRIVATE
            ),
        ),
    )
    projection = _project(_invoke("scoreform", partial))
    assert [row.module_id for row in projection.modules] == list(OWNERS)
    assert projection.for_module("scoreform").state == "evaluated_empty"
    assert projection.for_module("scoreform").notice_count == 1
    assert projection.evaluated_modules == 1
    assert projection.coverage == "partial"
    display = format_attention_display(filter_attention_projection(projection))
    assert "1 owner notice(s) omitted pending label review" in display
    assert "Coverage: 1/6" in display
    assert PRIVATE not in display and PRIVATE not in repr(projection)
    assert "all clear" not in display.lower()


@pytest.mark.parametrize(
    ("owner", "notice_code"),
    (
        ("scoreform", "scoreform_attention_partial"),
        ("quillan", "quillan_attention_partial"),
        ("concord", "concord_attention_partial"),
    ),
)
def test_each_tagged_partial_notice_is_private_and_non_authorizing(
    owner: str, notice_code: str
) -> None:
    result = _invoke(
        owner,
        ModuleAttentionReport(
            evaluation="evaluated",
            notices=(ModuleOperationsNotice(code=notice_code, summary=PRIVATE),),
        ),
    )
    projection = _project(result)
    row = projection.for_module(owner)
    assert row is not None and row.state == "evaluated_empty"
    assert row.notice_count == 1
    assert PRIVATE not in repr(projection)
    assert PRIVATE not in format_attention_display(
        filter_attention_projection(projection)
    )


def test_classless_aggregates_do_not_become_class_attributed() -> None:
    report = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(
            ModuleAttentionSummary(
                code="quillan_needs_assembly",
                label=PRIVATE,
                count=3,
                class_id=None,
                work_ref=None,
            ),
        ),
    )
    projection = _project(_invoke("quillan", report))
    view = filter_attention_projection(projection, class_id="class_a")
    quillan = next(row for row in view.rows if row.module_id == "quillan")
    assert quillan.state == "evaluated_items"
    assert quillan.reported_items == 1
    assert quillan.matching_items == 0
    display = format_attention_display(view)
    assert "No items match these filters" in display
    assert PRIVATE not in display


def test_owner_failures_are_isolated_without_raw_exceptions() -> None:
    def broken(_: ModuleOperationsRequest) -> ModuleAttentionReport:
        raise RuntimeError(PRIVATE)

    bad = invoke_module_attention(
        ModuleOperationsProfile(
            module_id="quillan",
            supported_core_operations_contract_versions=frozenset({"1"}),
            attention_provider=broken,
        ),
        ModuleOperationsRequest(),
    )
    good = _invoke(
        "scoreform",
        ModuleAttentionReport(
            evaluation="evaluated",
            summaries=(
                ModuleAttentionSummary(
                    code="scoreform_scan_review", label=PRIVATE, count=2
                ),
            ),
        ),
    )
    projection = _project(good, bad)
    assert projection.for_module("scoreform").state == "evaluated_items"
    assert projection.for_module("quillan").state == "provider_failed"
    assert projection.for_module("concord").state == "not_evaluated"
    display = format_attention_display(filter_attention_projection(projection))
    assert label_for_attention_category(
        "scoreform", "scoreform_scan_review"
    ) == GENERIC_ATTENTION_LABEL
    assert PRIVATE not in display and PRIVATE not in repr(projection)


def test_foreign_action_and_explicit_cross_class_are_rejected() -> None:
    stolen = _invoke(
        "concord",
        ModuleAttentionReport(
            evaluation="evaluated",
            summaries=(
                ModuleAttentionSummary(
                    code="concord_score_ready",
                    label=PRIVATE,
                    count=1,
                    action=ModuleOwnerActionRef(
                        module_id="quillan", action_id="private_action"
                    ),
                ),
            ),
        ),
    )
    assert stolen.code == "module_operations.result_invalid"
    assert _project(stolen).for_module("concord").state == "result_invalid"

    cross_class = _invoke(
        "scoreform",
        ModuleAttentionReport(
            evaluation="evaluated",
            summaries=(
                ModuleAttentionSummary(
                    code="scoreform_scan_review",
                    label=PRIVATE,
                    class_id="class_a",
                    count=1,
                ),
            ),
        ),
    )
    projection = _project(
        cross_class, request=ModuleOperationsRequest(class_id="class_b")
    )
    assert projection.for_module("scoreform").state == "result_invalid"
    assert PRIVATE not in repr(projection)


def test_slice_a_audit_matrix_is_exact_tagged_census_not_allowlist() -> None:
    doc = (
        Path(__file__).resolve().parents[1]
        / "docs/integration/issue21-slice-a-released-attention-audit.md"
    ).read_text(encoding="utf-8")
    assert doc.count("| ScoreForm 0.13.0 |") == 8
    assert doc.count("| Quillan 0.10.6 |") == 17
    assert doc.count("| Concord 0.3.4 |") == 20
    for code in (
        "scoreform_incomplete_attempt",
        "scoreform_results_publication_recovery",
        "quillan_post_dispatch_review",
        "quillan_results_republication_attention",
        "concord_collect_assembly",
        "concord_collect_author_confirmation",
        "concord_collect_subject_confirmation",
        "concord_score_ready",
        "concord_share_supersede",
    ):
        assert "`" + code + "`" in doc
        owner = code.split("_")[0]
        assert label_for_attention_category(owner, code) == GENERIC_ATTENTION_LABEL
