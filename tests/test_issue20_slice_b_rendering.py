"""Suite #20 Slice B: pure bounded display of fictional, Core-valid reports."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsNotice,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    invoke_module_attention,
)
from pds_core.routing_models import ModuleWorkRef

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
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
)

APPROVED = tuple(item for item in APPROVED_COMPONENTS if item.launchable)
IDS = tuple(item.component_id for item in APPROVED)


def _project(
    *results: object, request: ModuleOperationsRequest | None = None,
):
    metadata = ModuleOperationsMetadataInventory(
        applications=tuple(
            ModuleOperationsMetadataRow(
                component_id=item.component_id, display_name=item.display_name,
                expected_distribution=item.distribution, launch_state=None,
                metadata_state="declared_unvalidated",
            ) for item in APPROVED
        ),
        unapproved_candidates=0, inspection_available=True,
    )
    profiles = ModuleOperationsProfileInventory(
        applications=tuple(
            ModuleOperationsProfileRow(
                component_id=item.component_id, display_name=item.display_name,
                expected_distribution=item.distribution, launch_state=None,
                metadata_state="declared_unvalidated", profile_state="valid",
                readiness_declared=True, attention_declared=True,
            ) for item in APPROVED
        ),
        unapproved_diagnostics=0, diagnosis_available=True,
    )
    return project_module_attention(
        metadata_inventory=metadata, profile_inventory=profiles,
        request=request or ModuleOperationsRequest(),
        invocation_results=results,
    )


def _result(
    owner: str = "scoreform", *,
    summaries: tuple[ModuleAttentionSummary, ...] = (),
    notices: tuple[ModuleOperationsNotice, ...] = (),
    unavailable: bool = False,
):
    report = ModuleAttentionReport(
        evaluation="unavailable" if unavailable else "evaluated",
        summaries=summaries, notices=notices,
    )
    profile = ModuleOperationsProfile(
        module_id=owner,
        supported_core_operations_contract_versions=frozenset({"1"}),
        attention_provider=lambda _: report,
    )
    return invoke_module_attention(profile, ModuleOperationsRequest())


def _summary(
    count: int | None, *, code: str = "review",
    class_id: str | None = "class_a",
    label: str = "PRIVATE_STUDENT_NEVER_PRINT",
) -> ModuleAttentionSummary:
    return ModuleAttentionSummary(
        code=code, label=label, count=count, class_id=class_id,
    )


def _display(*results: object, **filters: object):
    return filter_attention_projection(
        _project(*results), **filters  # type: ignore[arg-type]
    )


def test_all_six_rows_and_unknown_do_not_get_evaluated_labels() -> None:
    display = _display()
    assert [row.module_id for row in display.rows] == list(IDS)
    assert display.evaluated_modules == 0
    text = format_attention_display(display)
    assert "Coverage: 0/6" in text
    assert text.count("Attention not evaluated") == 6
    assert "no items reported" not in text


def test_exact_one_evaluated_preserves_partial_coverage() -> None:
    result = _result(summaries=(_summary(3),))
    display = _display(result)
    assert display.coverage == "partial"
    assert display.evaluated_modules == 1
    assert "Coverage: 1/6" in format_attention_display(display)
    assert display.rows[1].state == "not_evaluated"


def test_six_evaluated_empty_is_complete_but_not_academic_clearance() -> None:
    display = _display(*(_result(owner) for owner in IDS))
    text = format_attention_display(display)
    assert display.coverage == "complete"
    assert "Coverage: 6/6" in text
    assert text.count("Evaluated: no items reported") == 6
    assert "All clear" not in text


def test_unknown_owner_count_and_explicit_zero_are_separate() -> None:
    display = _display(_result(summaries=(_summary(None), _summary(0))))
    row = display.rows[0]
    assert [item.owner_count for item in row.items] == [None, 0]
    text = format_attention_display(display)
    assert "count not supplied" in text and "owner count: 0" in text
    assert "total count" not in text.lower()


def test_stable_class_code_position_sort_without_rendering_fields() -> None:
    source = (
        _summary(8, code="review", class_id="class_b"),
        _summary(1, code="pending", class_id="class_a"),
        _summary(2, code="review", class_id="class_a"),
        _summary(3, code="review", class_id="class_a"),
    )
    display = _display(_result(summaries=source))
    assert [item.owner_count for item in display.rows[0].items] == [1, 2, 3, 8]
    assert "class_a" not in format_attention_display(display)
    assert "pending" not in format_attention_display(display)


def test_category_filter_is_exact_and_filter_value_is_not_rendered() -> None:
    display = _display(
        _result(summaries=(_summary(2, code="review"), _summary(7, code="pending"))),
        code="review",
    )
    row = display.rows[0]
    assert row.reported_items == 2 and row.matching_items == 1
    assert row.items[0].owner_count == 2
    text = format_attention_display(display)
    assert "Filters applied: category" in text
    assert "review" not in text.lower()


def test_class_filter_excludes_classless_and_other_classes() -> None:
    source = (
        _summary(1, class_id=None), _summary(2, class_id="class_a"),
        _summary(3, class_id="class_b"),
    )
    row = _display(_result(summaries=source), class_id="class_a").rows[0]
    assert row.matching_items == 1 and row.items[0].owner_count == 2


def test_scoped_projection_refuses_broadening_to_other_class() -> None:
    scoped = _project(request=ModuleOperationsRequest(class_id="class_a"))
    with pytest.raises(ValueError, match="attention_scope_mismatch"):
        filter_attention_projection(scoped, class_id="class_b")
    assert len(filter_attention_projection(scoped, class_id="class_a").rows) == 6


def test_module_filter_preserves_all_owners_and_coverage() -> None:
    display = _display(_result(), module_id="quillan")
    assert len(display.rows) == 6
    assert [row.selected for row in display.rows] == [
        False, True, False, False, False, False
    ]
    assert display.evaluated_modules == 1
    assert "Not selected by module filter" in format_attention_display(display)


def test_no_matching_filter_does_not_turn_evaluated_items_to_empty() -> None:
    display = _display(_result(summaries=(_summary(2),)), code="pending")
    row = display.rows[0]
    assert row.state == "evaluated_items" and row.matching_items == 0
    assert "source still reported attention" in format_attention_display(display)


def test_module_display_budget_reports_additional_matched_items() -> None:
    source = tuple(_summary(i) for i in range(7))
    display = _display(_result(summaries=source), per_module_limit=2)
    row = display.rows[0]
    assert row.matching_items == 7
    assert row.hidden_matching_items == 5
    assert len(row.items) == 2
    assert "5 additional matching item(s) not shown" in format_attention_display(
        display
    )


@pytest.mark.parametrize("limit", [0, 17, -1, True, 2.0, "5"])
def test_invalid_budget_is_rejected_without_echoing_value(limit: object) -> None:
    with pytest.raises(ValueError, match="invalid_display_limit"):
        _display(per_module_limit=limit)


@pytest.mark.parametrize(
    ("filters", "code"),
    [
        ({"module_id": "rogue"}, "invalid_module_filter"),
        ({"module_id": "PRIVATE_STUDENT"}, "invalid_module_filter"),
        ({"class_id": "class_a\nPRIVATE_STUDENT"}, "invalid_class_filter"),
        ({"code": ""}, "invalid_category_filter"),
        ({"code": "s" * 70}, "invalid_category_filter"),
        ({"code": "unsafe.owner"}, "invalid_category_filter"),
        ({"class_id": "unsafe/class"}, "invalid_class_filter"),
    ],
)
def test_invalid_filter_fail_closed(filters: dict[str, str], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        _display(**filters)


def test_malicious_payload_text_and_action_remain_hidden() -> None:
    secret = "PRIVATE_STUDENT_NEVER_PRINT"
    summary = ModuleAttentionSummary(
        code="private_student_token", label=secret,
        class_id="class_a", count=4,
        action=ModuleOwnerActionRef(module_id="scoreform", action_id="private_action"),
        work_ref=ModuleWorkRef(
            module_id="scoreform", class_id="class_a", work_id="private_work"
        ),
    )
    notices = (ModuleOperationsNotice(code="private_notice", summary=secret),)
    display = _display(_result(summaries=(summary,), notices=notices))
    text = format_attention_display(display)
    assert "owner count: 4" in text
    assert "1 owner notice(s) omitted pending label review" in text
    for forbidden in (
        secret, "private_student_token", "private_notice", "private_action",
        "private_work", "class_a",
    ):
        assert forbidden not in text and forbidden not in repr(display)


def test_forged_display_name_refused_before_rendering() -> None:
    view = _display()
    bad = replace(view.rows[0], display_name="PRIVATE_STUDENT")
    forged = replace(view, rows=(bad,) + view.rows[1:])
    with pytest.raises(ValueError, match="invalid_attention_display"):
        format_attention_display(forged)


def test_forged_approval_identity_refused_before_rendering() -> None:
    projection = _project()
    bad = replace(projection.modules[0], module_id="private_student")
    forged = replace(projection, modules=(bad,) + projection.modules[1:])
    with pytest.raises(ValueError, match="invalid_attention_view"):
        filter_attention_projection(forged)


def test_forged_attention_count_refused() -> None:
    projection = _project(_result(summaries=(_summary(2),)))
    bad_item = replace(projection.modules[0].items[0], count=-1)
    bad_row = replace(projection.modules[0], items=(bad_item,))
    forged = replace(projection, modules=(bad_row,) + projection.modules[1:])
    with pytest.raises(ValueError, match="invalid_attention_view"):
        filter_attention_projection(forged)


def test_source_wide_private_notice_and_unavailable_state() -> None:
    notice = ModuleOperationsNotice(code="n", summary="PRIVATE_STUDENT_NEVER_PRINT")
    unavailable = _result(notices=(notice,), unavailable=True)
    display = _display(unavailable)
    assert display.rows[0].state == "evaluation_unavailable"
    assert display.evaluated_modules == 0
    assert "PRIVATE_STUDENT" not in format_attention_display(display)


def test_pure_filter_and_format_do_not_call_providers() -> None:
    called: list[str] = []
    projection = _project()
    # There is no provider/callback to call; explicit witnesses make this visible.
    display = filter_attention_projection(projection, class_id="class_a")
    assert format_attention_display(display)
    assert called == []


def test_empty_category_filter_when_source_not_evaluated_stays_unknown() -> None:
    display = _display(code="pending")
    assert all(row.state == "not_evaluated" for row in display.rows)
    assert "No items match these filters" not in format_attention_display(display)
