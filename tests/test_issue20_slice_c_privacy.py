"""Suite #20 Slice C: adversarial owner/context and static-display label policy.

Only synthetic Core objects. No provider factory, workspace or OS call is made.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleAttentionSummary,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    invoke_module_attention,
)
from pds_core.routing_models import ModuleWorkRef

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_attention_label_policy import (
    GENERIC_ATTENTION_LABEL,
    allowed_attention_label,
    label_for_attention_category,
)
from paper_data_suite.module_attention_projection import project_module_attention
from paper_data_suite.module_attention_rendering import (
    AttentionDisplayItem,
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

APPROVED = tuple(x for x in APPROVED_COMPONENTS if x.launchable)
SECRET = "STUDENT_SSN_PRIVATE_NEVER_DISPLAY"


def _projection(
    *,
    class_id: str | None = None,
    code: str = "review",
    label: str = "PRIVATE_STUDENT_DO_NOT_RENDER",
    count: int | None = 2,
    work_ref: ModuleWorkRef | None = None,
    action: ModuleOwnerActionRef | None = None,
):
    metadata = ModuleOperationsMetadataInventory(
        applications=tuple(
            ModuleOperationsMetadataRow(
                component_id=c.component_id,
                display_name=c.display_name,
                expected_distribution=c.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
            )
            for c in APPROVED
        ),
        unapproved_candidates=0,
        inspection_available=True,
    )
    profiles = ModuleOperationsProfileInventory(
        applications=tuple(
            ModuleOperationsProfileRow(
                component_id=c.component_id,
                display_name=c.display_name,
                expected_distribution=c.distribution,
                launch_state=None,
                metadata_state="declared_unvalidated",
                profile_state="valid",
                readiness_declared=True,
                attention_declared=True,
            )
            for c in APPROVED
        ),
        unapproved_diagnostics=0,
        diagnosis_available=True,
    )
    report = ModuleAttentionReport(
        evaluation="evaluated",
        summaries=(
            ModuleAttentionSummary(
                code=code,
                label=label,
                class_id=class_id,
                count=count,
                work_ref=work_ref,
                action=action,
            ),
        ),
    )
    profile = ModuleOperationsProfile(
        module_id="scoreform",
        supported_core_operations_contract_versions=frozenset({"1"}),
        attention_provider=lambda _: report,
    )
    result = invoke_module_attention(profile, ModuleOperationsRequest())
    return project_module_attention(
        metadata_inventory=metadata,
        profile_inventory=profiles,
        request=ModuleOperationsRequest(),
        invocation_results=(result,),
    )


def _tamper_item(projection: object, **fields: object):
    first = projection.modules[0]  # type: ignore[attr-defined]
    changed = replace(first.items[0], **fields)
    return replace(
        projection, modules=(replace(first, items=(changed,)),) + projection.modules[1:]
    )


def _tamper_row(projection: object, **fields: object):
    first = projection.modules[0]  # type: ignore[attr-defined]
    return replace(
        projection, modules=(replace(first, **fields),) + projection.modules[1:]
    )


def test_default_policy_cannot_echo_unreviewed_provider_category_text() -> None:
    assert label_for_attention_category("scoreform", SECRET) == GENERIC_ATTENTION_LABEL
    assert (
        label_for_attention_category("scoreform", "review")
        == GENERIC_ATTENTION_LABEL
    )
    assert not allowed_attention_label("scoreform", SECRET)
    assert allowed_attention_label("scoreform", GENERIC_ATTENTION_LABEL)


@pytest.mark.parametrize(
    ("owner", "code"),
    [("rogue", "review"), ("scoreform", object()),
     (object(), "review"), ("scoreform", SECRET)],
)
def test_unsupported_source_owner_or_code_stays_generic(
    owner: object, code: object
) -> None:
    assert label_for_attention_category(owner, code) == GENERIC_ATTENTION_LABEL


def test_private_label_action_class_and_work_never_print_or_repr() -> None:
    view = filter_attention_projection(
        _projection(
            code="private_student_category",
            label=SECRET,
            class_id="private_class",
            work_ref=ModuleWorkRef("scoreform", "private_class", "private_work"),
            action=ModuleOwnerActionRef("scoreform", "private_action"),
        )
    )
    text = format_attention_display(view)
    assert "Module attention item (owner count: 2)" in text
    for forbidden in (
        SECRET, "private_class", "private_work", "private_action",
        "private_student_category",
    ):
        assert forbidden not in text and forbidden not in repr(view)


def test_forged_owner_label_in_display_fails_with_static_error() -> None:
    original = filter_attention_projection(_projection())
    row = original.rows[0]
    forged = replace(
        original,
        rows=(
            replace(row, items=(AttentionDisplayItem(2, SECRET),)),
        ) + original.rows[1:],
    )
    with pytest.raises(ValueError, match="^invalid_attention_display$") as caught:
        format_attention_display(forged)
    assert SECRET not in str(caught.value)


def test_forged_foreign_owner_action_is_rejected_at_display_boundary() -> None:
    forged = _tamper_item(
        _projection(), action=ModuleOwnerActionRef("quillan", "secret_action")
    )
    with pytest.raises(ValueError, match="^invalid_attention_view$"):
        filter_attention_projection(forged)


def test_forged_foreign_work_owner_is_rejected() -> None:
    forged = _tamper_item(
        _projection(), work_ref=ModuleWorkRef("portia", "class_a", "work_1")
    )
    with pytest.raises(ValueError, match="^invalid_attention_view$"):
        filter_attention_projection(forged)


def test_forged_work_class_conflict_is_rejected() -> None:
    forged = _tamper_item(
        _projection(class_id="class_a"),
        work_ref=ModuleWorkRef("scoreform", "class_b", "work_1"),
    )
    with pytest.raises(ValueError, match="^invalid_attention_view$"):
        filter_attention_projection(forged)


def test_forged_request_class_broadening_rejected() -> None:
    forged = replace(_projection(class_id="class_a"), requested_class_id="class_b")
    with pytest.raises(ValueError, match="^invalid_attention_view$"):
        filter_attention_projection(forged)


def test_forged_evaluated_state_from_unqualified_profile_is_rejected() -> None:
    forged = _tamper_row(_projection(), profile_state="load_failed")
    with pytest.raises(ValueError, match="^invalid_attention_view$"):
        filter_attention_projection(forged)


def test_non_tuple_module_items_refused_even_with_same_entries() -> None:
    projection = _projection()
    forged = _tamper_row(projection, items=list(projection.modules[0].items))
    with pytest.raises(ValueError, match="^invalid_attention_view$"):
        filter_attention_projection(forged)


def test_forged_private_exception_object_is_redacted() -> None:
    class Poison:
        def __getattribute__(self, _: str) -> object:
            raise RuntimeError(SECRET)

    projection = _projection()
    first = replace(projection.modules[0], items=(Poison(),))
    forged = replace(projection, modules=(first,) + projection.modules[1:])
    with pytest.raises(ValueError, match="^invalid_attention_view$") as error:
        filter_attention_projection(forged)
    assert SECRET not in str(error.value)


def test_forged_display_nested_object_error_is_redacted() -> None:
    class Poison:
        def __getattribute__(self, _: str) -> object:
            raise RuntimeError(SECRET)

    view = filter_attention_projection(_projection())
    first = replace(view.rows[0], items=(Poison(),))
    forged = replace(view, rows=(first,) + view.rows[1:])
    with pytest.raises(ValueError, match="^invalid_attention_display$") as error:
        format_attention_display(forged)
    assert SECRET not in str(error.value)


def test_private_code_is_still_available_for_exact_filter_only() -> None:
    projection = _projection(code="private_student_category")
    display = filter_attention_projection(projection, code="private_student_category")
    assert display.rows[0].matching_items == 1
    text = format_attention_display(display)
    assert "Filters applied: category." in text
    assert "private_student_category" not in text


def test_nested_display_uses_only_statically_reviewed_label() -> None:
    view = filter_attention_projection(_projection())
    assert view.rows[0].items[0].category_label == GENERIC_ATTENTION_LABEL
    assert GENERIC_ATTENTION_LABEL in format_attention_display(view)
