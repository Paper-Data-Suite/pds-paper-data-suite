"""#19F1: in-session manual page review and one Core-owned defer decision.

Only a recorded, Core-verified v2 failure from this already completed result
may be deferred. No speculative failure IDs, scan replay, producer deep link,
resolution claim or Suite-owned durable queue is created here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TextIO

from paper_data_suite.returned_paper_core_review import (
    CoreReviewResultV1,
    DeferDecisionV1,
    DeferredReviewResultV1,
    DeferredReviewV1,
    ReviewPageV1,
    append_deferred_core_resolution,
)
from paper_data_suite.returned_paper_teacher_results import (
    render_core_paper_page_detail,
)
from paper_data_suite.returned_paper_teacher_retention import (
    _active_core_workspace_matches,
)

ReviewNavigation = Literal["back", "home", "quit"]
WorkspaceGuard = Callable[[Path], bool]
_FID = re.compile(r"failure_[A-Za-z0-9_-]{1,120}\Z")
_REVIEWABLE = frozenset({
    "unresolved_qr", "module_unqualified", "dispatch_failed", "uncertain",
    "review_write_failed", "not_attempted", "retained_only", "source_rejected",
})
_MAX_INPUT = 64


class TeacherCoreRecoveryError(ValueError):
    """A result without genuine Core page review cannot be used for deferral."""


def _read(stream: TextIO) -> str | None:
    """Treat EOF, overlong input and controls as cancellation, not a token."""
    try:
        raw = stream.readline(_MAX_INPUT + 2)
    except (Exception, KeyboardInterrupt):
        return None
    if (
        not raw or len(raw) > _MAX_INPUT + 1
        or any(ord(ch) < 32 and ch not in "\r\n" for ch in raw)
    ):
        return None
    return raw.strip()


def _nav(value: str) -> ReviewNavigation | None:
    choice = value.casefold()
    if choice == "b":
        return "back"
    if choice == "m":
        return "home"
    if choice == "q":
        return "quit"
    return None


def _workspace_ok(root: Path, guard: WorkspaceGuard) -> bool:
    try:
        return guard(root) is True
    except (Exception, KeyboardInterrupt):
        return False


def _pending_pages(core: CoreReviewResultV1) -> tuple[ReviewPageV1, ...]:
    """Use only the typed, one-per-physical-page Core review snapshot."""
    if not isinstance(core, CoreReviewResultV1):
        raise TeacherCoreRecoveryError("genuine Core review required")
    rows = tuple(
        page for page in core.pages
        if page.dispatch_status in _REVIEWABLE
        or page.review_state in {"recorded", "write_uncertain", "manual_review"}
    )
    if len(rows) > 512 or any(
        page.review_state == "recorded"
        and (page.failure_id is None or _FID.fullmatch(page.failure_id) is None)
        for page in rows
    ):
        raise TeacherCoreRecoveryError("Core failure review is inconsistent")
    return rows


def run_teacher_core_review_menu(
    core: CoreReviewResultV1,
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    workspace_guard: WorkspaceGuard = _active_core_workspace_matches,
) -> ReviewNavigation:
    """Show unresolved pages, then permit at most one third-consent Core defer.

    The caller passes a genuine Core result from an already completed action.
    No producer dispatch is performed. A verified Core failure ID is required
    for deferral; absence of an ID is manual review, not implied success.
    """
    if (
        not isinstance(core, CoreReviewResultV1)
        or not callable(getattr(input_stream, "readline", None))
        or not callable(getattr(output, "write", None))
        or not callable(getattr(output, "flush", None))
        or not callable(show_header) or not callable(workspace_guard)
    ):
        raise TeacherCoreRecoveryError("review requires typed Core result and UI")
    root = core.execution.report.plan.workspace_root
    rows = _pending_pages(core)
    show_header("Returned Papers - Unresolved Page Review")
    output.write(
        f"\nPhysical pages requiring follow-up: {len(rows)}.\n"
        "This in-session view is not a saved Suite review queue.\n"
    )
    for item in rows:
        output.write(render_core_paper_page_detail(
            core, item.source_number, item.page_number,
        ))
    eligible = tuple(
        row for row in rows
        if row.review_state == "recorded" and row.failure_id is not None
    )
    if not rows:
        output.write("No pages require follow-up in this Core result.\n")
        return "back"
    output.write(
        f"Verified Core failures eligible for optional deferral: {len(eligible)}.\n"
        "Manual-review or uncertain-write pages cannot be deferred without a "
        "verified Core failure ID.\n"
        "Deferral does not resolve, rescan, retry, capture evidence, or "
        "publish grades.\n"
    )
    if not _workspace_ok(root, workspace_guard):
        output.write("Active Core workspace differs; review is read-only.\n")
        return "back"
    while True:
        output.write(
            "F. Defer one verified Core failure (separate confirmation)\n"
            "H. Help   B. Back   M. Main Menu   Q. Quit\nSelection: "
        )
        output.flush()
        selected = _read(input_stream)
        if selected is None:
            return "back"
        nav = _nav(selected)
        if nav is not None:
            return nav
        if selected.casefold() == "h":
            output.write(
                "Select F only for a recorded Core failure. "
                "Unverified and unresolved-only pages need manual review. "
                "No automatic producer retry is available.\n"
            )
            continue
        if selected.casefold() != "f":
            output.write("No Core review write requested.\n")
            return "back"
        if not eligible:
            output.write(
                "No verified failure ID exists for this result; "
                "no deferral can be written.\n"
            )
            return "back"
        output.write("Verified Core failure selections:\n")
        for index, item in enumerate(eligible, 1):
            output.write(
                f"  {index}. Source {item.source_number}, "
                f"page {item.page_number}; Core ID {item.failure_id}.\n"
            )
        output.write("Choose exactly one number (B/M/Q): ")
        output.flush()
        choice = _read(input_stream)
        if choice is None:
            return "back"
        nav = _nav(choice)
        if nav is not None:
            return nav
        if (
            not choice.isascii() or not choice.isdecimal()
            or not 1 <= int(choice) <= len(eligible)
        ):
            output.write("Invalid selection; no Core review write requested.\n")
            return "back"
        target = eligible[int(choice) - 1]
        assert target.failure_id is not None
        if not _workspace_ok(root, workspace_guard):
            output.write("Active Core workspace changed; deferral refused.\n")
            return "back"
        navigation: ReviewNavigation = "back"

        def third_consent(review: DeferredReviewV1) -> DeferDecisionV1:
            nonlocal navigation
            cancel = DeferDecisionV1("cancel", review.failure_id, review.challenge)
            if (
                not isinstance(review, DeferredReviewV1)
                or review.failure_id != target.failure_id
                or not review.challenge
                or review.append_only is not True
                or review.automatic_retry_allowed is not False
                or not _workspace_ok(root, workspace_guard)
            ):
                return cancel
            show_header("Defer Core Failure? - Third Teacher Consent")
            output.write(
                f"\nSource {target.source_number}, page {target.page_number}.\n"
                f"Verified Core failure: {target.failure_id}.\n"
                "DEFER appends a Core v2 review event. It does not resolve "
                "the failure, rerun any producer or change grades.\n"
                "Existing Core custody and failure records remain intact.\n"
                "Type DEFER to approve this one action; anything else cancels.\n"
                "B. Back   M. Main Menu   Q. Quit\nConfirmation: "
            )
            output.flush()
            answer = _read(input_stream)
            if answer is None:
                return cancel
            selected_nav = _nav(answer)
            if selected_nav is not None:
                navigation = selected_nav
                return cancel
            if answer.casefold() != "defer" or not _workspace_ok(root, workspace_guard):
                return cancel
            return DeferDecisionV1("defer", review.failure_id, review.challenge)

        try:
            written = append_deferred_core_resolution(
                root, target.failure_id, approve=third_consent,
            )
        except (Exception, KeyboardInterrupt):
            output.write(
                "Core deferral state could not be verified. A Core event may "
                "have been written. Do not retry; reconcile Core records.\n"
            )
            return navigation
        if (
            not isinstance(written, DeferredReviewResultV1)
            or written.failure_id != target.failure_id
        ):
            output.write(
                "Core deferral receipt mismatched; write effects uncertain. "
                "Do not retry; reconcile Core records.\n"
            )
            return navigation
        if written.state == "appended":
            output.write(
                "A verified append-only Core deferral event was recorded. "
                "The failure remains unresolved; no producer was retried.\n"
            )
        elif written.state == "cancelled":
            output.write("Deferral cancelled; no Core deferral authorized.\n")
        else:
            output.write(
                "Core deferral write is uncertain; an event may exist. "
                "Do not retry without reconciliation.\n"
            )
        return navigation


__all__ = (
    "ReviewNavigation", "TeacherCoreRecoveryError", "run_teacher_core_review_menu",
)
