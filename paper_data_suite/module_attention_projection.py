"""Suite #20 Slice A: pure, nonauthorizing Core v1 attention projection.

The caller supplies #16 observations, an explicit Core request and already
obtained Core invocation results. This module does not discover, import or
invoke providers. It deliberately discards unreviewed labels/notices/messages.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleOperationsInvocationResult,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
    validate_module_attention_report,
    validate_module_operations_invocation_result,
    validate_module_operations_request,
    validate_module_owner_action_ref,
)
from pds_core.routing_models import ModuleWorkRef

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_operations_diagnosis import (
    ModuleOperationsProfileInventory,
    ModuleOperationsProfileRow,
)
from paper_data_suite.module_operations_inventory import (
    ModuleOperationsMetadataInventory,
    ModuleOperationsMetadataRow,
)

AttentionState = Literal[
    "metadata_unavailable",
    "not_declared",
    "metadata_unqualified",
    "profile_not_checked",
    "profile_unqualified",
    "capability_absent",
    "not_evaluated",
    "evaluation_unavailable",
    "provider_failed",
    "result_invalid",
    "evaluated_empty",
    "evaluated_items",
]
CoverageState = Literal["none_evaluated", "partial", "complete"]

_APPROVED = tuple(
    component for component in APPROVED_COMPONENTS if component.launchable
)
_METADATA_STATES = frozenset(
    {
        "not_declared", "declared_unvalidated", "owner_mismatch", "ambiguous",
        "invalid_metadata", "inspection_unavailable",
    }
)
_PROFILE_STATES = frozenset(
    {
        "not_declared", "metadata_unqualified", "diagnosis_unavailable",
        "diagnosis_missing", "ambiguous", "invalid_diagnostic", "owner_mismatch",
        "valid", "entry_point_name_invalid", "load_failed", "not_callable",
        "call_failed", "profile_invalid", "identity_mismatch",
        "core_incompatible", "identity_conflict",
    }
)


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One Core-validated item; raw owner text is intentionally discarded.

    Code, class/work context and action are inert, potentially sensitive data.
    They are stored for later *qualified* consumers, but hidden from repr and
    never formatted by this slice. No generic urgency or global count exists.
    """

    owner_id: str
    count: int | None
    code: str = field(repr=False)
    class_id: str | None = field(repr=False)
    work_ref: ModuleWorkRef | None = field(repr=False)
    action: ModuleOwnerActionRef | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class AttentionModuleRow:
    """One approved Suite module, even when attention was never evaluated."""

    module_id: str
    display_name: str
    state: AttentionState
    metadata_state: str
    profile_state: str
    items: tuple[AttentionItem, ...] = field(default=(), repr=False)
    notice_count: int = 0


@dataclass(frozen=True, slots=True)
class AttentionProjection:
    """All six approved modules; coverage never implies academic clearance."""

    modules: tuple[AttentionModuleRow, ...]
    coverage: CoverageState
    evaluated_modules: int
    unapproved_result_count: int
    requested_class_id: str | None = field(repr=False)

    def for_module(self, module_id: str) -> AttentionModuleRow | None:
        return next((row for row in self.modules if row.module_id == module_id), None)


def _metadata_rows(
    inventory: ModuleOperationsMetadataInventory,
) -> dict[str, tuple[ModuleOperationsMetadataRow, ...]]:
    grouped: dict[str, list[ModuleOperationsMetadataRow]] = {
        component.component_id: [] for component in _APPROVED
    }
    for row in inventory.applications:
        if isinstance(row, ModuleOperationsMetadataRow) and row.component_id in grouped:
            grouped[row.component_id].append(row)
    return {key: tuple(rows) for key, rows in grouped.items()}


def _profile_rows(
    inventory: ModuleOperationsProfileInventory | None,
) -> dict[str, tuple[ModuleOperationsProfileRow, ...]]:
    grouped: dict[str, list[ModuleOperationsProfileRow]] = {
        component.component_id: [] for component in _APPROVED
    }
    if inventory is not None:
        for row in inventory.applications:
            if (
                isinstance(row, ModuleOperationsProfileRow)
                and row.component_id in grouped
            ):
                grouped[row.component_id].append(row)
    return {key: tuple(rows) for key, rows in grouped.items()}


def _project_invocation(
    result: object, *, owner_id: str, request: ModuleOperationsRequest
) -> tuple[AttentionState, tuple[AttentionItem, ...], int]:
    if not isinstance(result, ModuleOperationsInvocationResult):
        return "result_invalid", (), 0
    if result.module_id != owner_id or result.capability != "attention":
        return "result_invalid", (), 0
    try:
        validate_module_operations_invocation_result(result)
        if result.code == "module_operations.provider_failed":
            return "provider_failed", (), 0
        if result.code == "module_operations.result_invalid":
            return "result_invalid", (), 0
        if result.code == "module_operations.evaluation_unavailable":
            return "evaluation_unavailable", (), 0
        if result.code != "module_operations.evaluated":
            return "result_invalid", (), 0
        report = result.report
        if not isinstance(report, ModuleAttentionReport):
            return "result_invalid", (), 0
        validate_module_attention_report(report, expected_module_id=owner_id)
        items: list[AttentionItem] = []
        for summary in report.summaries:
            # Core's invocation API normally checks requested class, but a
            # supplied/persisted result needs this second boundary check.
            if request.class_id is not None and (
                (summary.class_id is not None and summary.class_id != request.class_id)
                or (
                    summary.work_ref is not None
                    and summary.work_ref.class_id != request.class_id
                )
            ):
                return "result_invalid", (), 0
            if summary.action is not None:
                validate_module_owner_action_ref(
                    summary.action, expected_module_id=owner_id
                )
            items.append(
                AttentionItem(
                    owner_id=owner_id,
                    count=summary.count,
                    code=summary.code,
                    class_id=summary.class_id,
                    work_ref=summary.work_ref,
                    action=summary.action,
                )
            )
        return (
            "evaluated_items" if items else "evaluated_empty",
            tuple(items),
            len(report.notices),
        )
    except Exception:
        # Core validation or malicious Python objects may raise with private
        # payloads. Never include an exception string in a Suite view.
        return "result_invalid", (), 0


def project_module_attention(
    *,
    metadata_inventory: ModuleOperationsMetadataInventory,
    profile_inventory: ModuleOperationsProfileInventory | None,
    request: ModuleOperationsRequest,
    invocation_results: Iterable[object] = (),
) -> AttentionProjection:
    """Project supplied Core v1 results; execute no provider or workspace I/O.

    Invalid or duplicate per-owner input fails closed for that owner without
    dropping other approved modules. Unapproved results cannot add an owner.
    A metadata/profile census or a valid profile is never an evaluation.
    """
    if not isinstance(metadata_inventory, ModuleOperationsMetadataInventory):
        raise TypeError("invalid_metadata_inventory")
    if profile_inventory is not None and not isinstance(
        profile_inventory, ModuleOperationsProfileInventory
    ):
        raise TypeError("invalid_profile_inventory")
    try:
        validate_module_operations_request(request)
    except Exception:
        raise ValueError("invalid_attention_request") from None

    approved_by_id = {component.component_id: component for component in _APPROVED}
    metadata_by_id = _metadata_rows(metadata_inventory)
    profile_by_id = _profile_rows(profile_inventory)
    results_by_id: dict[str, list[object]] = {key: [] for key in approved_by_id}
    unapproved_count = 0
    for index, result in enumerate(invocation_results):
        # A Core report has an intrinsic maximum, but the *input* list could
        # be an infinite generator. Bound evaluation before any side effect.
        if index >= 512:
            raise ValueError("attention_input_limit")
        try:
            owner = getattr(result, "module_id", None)
        except Exception:
            owner = None
        if type(owner) is str and owner in results_by_id:
            results_by_id[owner].append(result)
        else:
            unapproved_count += 1

    rows: list[AttentionModuleRow] = []
    for component in _APPROVED:
        owner = component.component_id
        metadata_rows = metadata_by_id[owner]
        profile_rows = profile_by_id[owner]
        metadata_state = "inspection_unavailable"
        profile_state = "not_checked"
        state: AttentionState
        if not metadata_inventory.inspection_available:
            state = "metadata_unavailable"
        elif len(metadata_rows) != 1:
            state = "metadata_unqualified"
        else:
            meta = metadata_rows[0]
            metadata_state = (
                meta.metadata_state if meta.metadata_state in _METADATA_STATES
                else "invalid_metadata"
            )
            if (
                meta.expected_distribution != component.distribution
                or meta.display_name != component.display_name
                or metadata_state not in {"declared_unvalidated", "not_declared"}
            ):
                state = "metadata_unqualified"
            elif metadata_state == "not_declared":
                state = "not_declared"
            elif profile_inventory is None:
                state = "profile_not_checked"
            elif not profile_inventory.diagnosis_available or len(profile_rows) != 1:
                state = "profile_unqualified"
            else:
                prof = profile_rows[0]
                profile_state = (
                    prof.profile_state if prof.profile_state in _PROFILE_STATES
                    else "invalid_diagnostic"
                )
                if (
                    prof.component_id != owner
                    or prof.expected_distribution != component.distribution
                    or prof.display_name != component.display_name
                    or prof.metadata_state != meta.metadata_state
                    or profile_state != "valid"
                    or type(prof.attention_declared) is not bool
                ):
                    state = "profile_unqualified"
                elif prof.attention_declared is False:
                    state = "capability_absent"
                else:
                    state = "not_evaluated"

        items: tuple[AttentionItem, ...] = ()
        notice_count = 0
        supplied = results_by_id[owner]
        if supplied:
            if len(supplied) != 1:
                state = "result_invalid"
            elif state == "not_evaluated":
                state, items, notice_count = _project_invocation(
                    supplied[0], owner_id=owner, request=request
                )
            elif state == "capability_absent":
                supplied_result = supplied[0]
                try:
                    if (
                        isinstance(supplied_result, ModuleOperationsInvocationResult)
                        and supplied_result.module_id == owner
                        and supplied_result.capability == "attention"
                        and supplied_result.code
                        == "module_operations.capability_absent"
                    ):
                        validate_module_operations_invocation_result(supplied_result)
                    else:
                        state = "result_invalid"
                except Exception:
                    state = "result_invalid"
            else:
                # An invocation cannot retroactively validate metadata,
                # profile identity or a missing declared capability.
                state = "result_invalid"
        rows.append(
            AttentionModuleRow(
                module_id=owner,
                display_name=component.display_name,
                state=state,
                metadata_state=metadata_state,
                profile_state=profile_state,
                items=items,
                notice_count=notice_count,
            )
        )

    evaluated = sum(
        row.state in {"evaluated_empty", "evaluated_items"} for row in rows
    )
    coverage: CoverageState = (
        "complete" if evaluated == len(_APPROVED)
        else "partial" if evaluated else "none_evaluated"
    )
    return AttentionProjection(
        modules=tuple(rows),
        coverage=coverage,
        evaluated_modules=evaluated,
        unapproved_result_count=unapproved_count,
        requested_class_id=request.class_id,
    )
