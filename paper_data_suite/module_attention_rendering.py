"""Suite #20 Slice B: pure, bounded rendering of existing attention projections.

No producer is loaded or invoked, and no provider text, class/work identity,
owner action or source code string is rendered. This is NOT the #23 dashboard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS
from paper_data_suite.module_attention_projection import (
    AttentionProjection,
    AttentionState,
)

_APPROVED = tuple(item for item in APPROVED_COMPONENTS if item.launchable)
_KNOWN_STATES = frozenset(
    {
        "metadata_unavailable", "not_declared", "metadata_unqualified",
        "profile_not_checked", "profile_unqualified", "capability_absent",
        "not_evaluated", "evaluation_unavailable", "provider_failed",
        "result_invalid", "evaluated_empty", "evaluated_items",
    }
)
_STATUS_LABELS = {
    "metadata_unavailable": "Provider discovery unavailable",
    "not_declared": "Provider not declared",
    "metadata_unqualified": "Provider metadata not qualified",
    "profile_not_checked": "Provider profile not checked",
    "profile_unqualified": "Provider profile not qualified",
    "capability_absent": "Attention capability absent",
    "not_evaluated": "Attention not evaluated",
    "evaluation_unavailable": "Attention evaluation unavailable",
    "provider_failed": "Attention provider failed",
    "result_invalid": "Attention result invalid",
    "evaluated_empty": "Evaluated: no items reported",
    "evaluated_items": "Evaluated: attention reported",
}
_MAX_CORE_ITEMS = 32
_MAX_CORE_NOTICES = 16
_MAX_CORE_COUNT = 1_000_000
_MAX_FILTER_LEN = 128


@dataclass(frozen=True, slots=True)
class AttentionDisplayItem:
    """Safe presentation datum. No owner text, actions, class or work IDs."""

    owner_count: int | None


@dataclass(frozen=True, slots=True)
class AttentionDisplayRow:
    """Six fixed approved owners remain even when a module filter is applied."""

    module_id: str
    display_name: str
    state: AttentionState
    selected: bool
    reported_items: int
    matching_items: int
    hidden_matching_items: int
    items: tuple[AttentionDisplayItem, ...]
    notice_count: int


@dataclass(frozen=True, slots=True)
class AttentionDisplay:
    """Snapshot for #23 to render; neither permission nor a provider result."""

    rows: tuple[AttentionDisplayRow, ...]
    coverage: str
    evaluated_modules: int
    module_filtered: bool
    class_filtered: bool
    code_filtered: bool


def _valid_filter(value: object, *, maximum: int = _MAX_FILTER_LEN) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= maximum
        and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None
    )


def _validate_projection(projection: AttentionProjection) -> None:
    """Do not let a forged/modified projection inject labels or state claims."""
    if not isinstance(projection, AttentionProjection):
        raise ValueError("invalid_attention_view")
    if len(projection.modules) != len(_APPROVED):
        raise ValueError("invalid_attention_view")
    evaluated = 0
    for component, row in zip(_APPROVED, projection.modules, strict=True):
        if (
            row.module_id != component.component_id
            or row.display_name != component.display_name
            or row.state not in _KNOWN_STATES
            or type(row.notice_count) is not int
            or not 0 <= row.notice_count <= _MAX_CORE_NOTICES
            or len(row.items) > _MAX_CORE_ITEMS
        ):
            raise ValueError("invalid_attention_view")
        if row.state in {"evaluated_empty", "evaluated_items"}:
            evaluated += 1
            if (row.state == "evaluated_empty") != (len(row.items) == 0):
                raise ValueError("invalid_attention_view")
        elif row.items:
            raise ValueError("invalid_attention_view")
        for item in row.items:
            if (
                item.owner_id != row.module_id
                or type(item.code) is not str
                or not _valid_filter(item.code, maximum=64)
                or (
                    item.class_id is not None
                    and not _valid_filter(item.class_id)
                )
                or (
                    item.count is not None
                    and (
                        type(item.count) is not int
                        or not 0 <= item.count <= _MAX_CORE_COUNT
                    )
                )
            ):
                raise ValueError("invalid_attention_view")
    expected_coverage = (
        "complete" if evaluated == len(_APPROVED)
        else "partial" if evaluated else "none_evaluated"
    )
    if (
        type(projection.evaluated_modules) is not int
        or projection.evaluated_modules != evaluated
        or projection.coverage != expected_coverage
        or (
            projection.requested_class_id is not None
            and not _valid_filter(projection.requested_class_id)
        )
    ):
        raise ValueError("invalid_attention_view")


def filter_attention_projection(
    projection: AttentionProjection,
    *,
    module_id: str | None = None,
    class_id: str | None = None,
    code: str | None = None,
    per_module_limit: int = 5,
) -> AttentionDisplay:
    """Filter supplied Core results only; no input is authorization or executed.

    Classless items do not prove membership in a particular class. A filter
    cannot broaden an already class-scoped projection into another class.
    Raw owner code/class strings are never retained in the display result.
    """
    _validate_projection(projection)
    if module_id is not None and (
        type(module_id) is not str
        or module_id not in {component.component_id for component in _APPROVED}
    ):
        raise ValueError("invalid_module_filter")
    if class_id is not None:
        if not _valid_filter(class_id):
            raise ValueError("invalid_class_filter")
        if (
            projection.requested_class_id is not None
            and class_id != projection.requested_class_id
        ):
            raise ValueError("attention_scope_mismatch")
    if code is not None and not _valid_filter(code, maximum=64):
        raise ValueError("invalid_category_filter")
    if type(per_module_limit) is not int or not 1 <= per_module_limit <= 16:
        raise ValueError("invalid_display_limit")

    rows: list[AttentionDisplayRow] = []
    for original in projection.modules:
        selected = module_id is None or original.module_id == module_id
        qualifying = [
            (index, item) for index, item in enumerate(original.items)
            if selected
            and (class_id is None or item.class_id == class_id)
            and (code is None or item.code == code)
        ]
        qualifying.sort(
            key=lambda pair: (
                pair[1].class_id or "",
                pair[1].code,
                pair[0],
            )
        )
        shown = tuple(
            AttentionDisplayItem(item.count)
            for _, item in qualifying[:per_module_limit]
        )
        rows.append(
            AttentionDisplayRow(
                module_id=original.module_id,
                display_name=original.display_name,
                state=original.state,
                selected=selected,
                reported_items=len(original.items),
                matching_items=len(qualifying),
                hidden_matching_items=max(0, len(qualifying) - len(shown)),
                items=shown,
                notice_count=original.notice_count,
            )
        )
    return AttentionDisplay(
        rows=tuple(rows),
        coverage=projection.coverage,
        evaluated_modules=projection.evaluated_modules,
        module_filtered=module_id is not None,
        class_filtered=class_id is not None,
        code_filtered=code is not None,
    )


def format_attention_display(view: AttentionDisplay) -> str:
    """Accessible, deterministic, bounded text. Only internally fixed words."""
    if not isinstance(view, AttentionDisplay) or len(view.rows) != len(_APPROVED):
        raise ValueError("invalid_attention_display")
    if (
        view.coverage not in {"none_evaluated", "partial", "complete"}
        or any(
            type(flag) is not bool
            for flag in (
                view.module_filtered, view.class_filtered, view.code_filtered
            )
        )
    ):
        raise ValueError("invalid_attention_display")
    if (
        type(view.evaluated_modules) is not int
        or not 0 <= view.evaluated_modules <= 6
    ):
        raise ValueError("invalid_attention_display")
    observed_evaluated = sum(
        row.state in {"evaluated_empty", "evaluated_items"}
        for row in view.rows
    )
    expected_coverage = (
        "complete" if observed_evaluated == len(_APPROVED)
        else "partial" if observed_evaluated else "none_evaluated"
    )
    if (
        view.evaluated_modules != observed_evaluated
        or view.coverage != expected_coverage
        or (
            not view.module_filtered
            and any(not row.selected for row in view.rows)
        )
        or (
            view.module_filtered
            and sum(row.selected for row in view.rows) != 1
        )
    ):
        raise ValueError("invalid_attention_display")
    lines = [
        "ATTENTION — read-only module reports; no actions executed",
        f"Coverage: {view.evaluated_modules}/6 modules evaluated ({view.coverage}).",
        "Not evaluated, unavailable and failed are UNKNOWN, not zero.",
        "Counts are owner-supplied and are not added across modules.",
    ]
    if view.module_filtered or view.class_filtered or view.code_filtered:
        labels = (
            ("module" if view.module_filtered else ""),
            ("class" if view.class_filtered else ""),
            ("category" if view.code_filtered else ""),
        )
        active = ", ".join(label for label in labels if label)
        lines.append("Filters applied: " + active + ".")
    for component, row in zip(_APPROVED, view.rows, strict=True):
        if (
            row.module_id != component.component_id
            or row.display_name != component.display_name
            or row.state not in _STATUS_LABELS
            or type(row.selected) is not bool
            or type(row.reported_items) is not int
            or type(row.matching_items) is not int
            or type(row.hidden_matching_items) is not int
            or row.reported_items < 0
            or row.matching_items < 0
            or row.hidden_matching_items < 0
            or len(row.items) > 16
            or row.matching_items != len(row.items) + row.hidden_matching_items
            or row.matching_items > row.reported_items
            or (not row.selected and (row.matching_items or row.items))
            or (
                row.state == "evaluated_items" and row.reported_items == 0
            )
            or (
                row.state != "evaluated_items" and row.reported_items != 0
            )
            or type(row.notice_count) is not int
            or not 0 <= row.notice_count <= _MAX_CORE_NOTICES
        ):
            raise ValueError("invalid_attention_display")
        lines.append(f"{component.display_name}: {_STATUS_LABELS[row.state]}.")
        if not row.selected:
            lines.append("  Not selected by module filter.")
            continue
        if row.state == "evaluated_items":
            if not row.matching_items:
                lines.append(
                    "  No items match these filters; source still reported attention."
                )
            for item in row.items:
                if (
                    not isinstance(item, AttentionDisplayItem)
                    or (
                        item.owner_count is not None
                        and (
                            type(item.owner_count) is not int
                            or not 0 <= item.owner_count <= _MAX_CORE_COUNT
                        )
                    )
                ):
                    raise ValueError("invalid_attention_display")
                count = (
                    "count not supplied" if item.owner_count is None
                    else f"owner count: {item.owner_count}"
                )
                lines.append("  - Module attention item (" + count + ")")
            if row.hidden_matching_items:
                lines.append(
                    f"  {row.hidden_matching_items} additional matching item(s) "
                    "not shown (display limit)."
                )
        elif row.items or row.matching_items or row.hidden_matching_items:
            raise ValueError("invalid_attention_display")
        if row.notice_count:
            lines.append(
                f"  {row.notice_count} owner notice(s) omitted pending label review."
            )
    lines.append("Provider-specific labels, owner actions and My Tasks are not shown.")
    return "\n".join(lines) + "\n"
