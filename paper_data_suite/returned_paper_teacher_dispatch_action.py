"""#19E3B2: one fresh teacher-approved retained-paper Core execution bridge.

This action never retains sources, never performs a second dispatch, and never
promotes historical synthetic evidence to live admission. It is not a Home
navigation command until the subsequent UI slice explicitly wires it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
)
from paper_data_suite.returned_paper_core_review import (
    CoreReviewResultV1,
    execute_with_core_review,
)
from paper_data_suite.returned_paper_live_admission import (
    LivePaperAdmissionV1,
    inspect_live_paper_admission,
)
from paper_data_suite.returned_paper_ordered_dispatch import (
    DispatchDecisionV1,
    DispatchReviewV1,
)
from paper_data_suite.returned_paper_retained_requests import (
    PreparedDispatchBatchV1,
    prepare_retained_pds2_requests,
)
from paper_data_suite.returned_paper_teacher_retention import (
    _active_core_workspace_matches,
)
from paper_data_suite.returned_paper_teacher_second_consent import (
    ask_teacher_second_dispatch_consent,
)

_ALLOWED = frozenset({"scoreform", "quillan"})

BridgeStatus = Literal[
    "admission_refused", "workspace_refused", "preparation_refused",
    "preparation_uncertain", "no_dispatchable_pages", "cancelled",
    "admission_changed", "completed", "partial", "blocked", "uncertain",
]


class TeacherDispatchActionError(ValueError):
    """The caller supplied a non-retained or invalid action request."""


@dataclass(frozen=True, slots=True, repr=False)
class TeacherDispatchActionResultV1:
    """Transient truthful result; never a reusable authority or grade receipt."""

    status: BridgeStatus
    core_review: CoreReviewResultV1 | None = None
    contract_version: Literal["1"] = "1"
    automatic_retry_allowed: Literal[False] = False
    grades_published: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            self.contract_version != "1"
            or self.status not in {
                "admission_refused", "workspace_refused", "preparation_refused",
                "preparation_uncertain", "no_dispatchable_pages", "cancelled",
                "admission_changed", "completed", "partial", "blocked",
                "uncertain",
            }
            or self.automatic_retry_allowed is not False
            or self.grades_published is not False
            or (self.core_review is not None and not isinstance(
                self.core_review, CoreReviewResultV1
            ))
        ):
            raise TeacherDispatchActionError("unsupported bridge result")
        if self.core_review is None:
            if self.status in {"completed", "partial", "blocked", "cancelled"}:
                raise TeacherDispatchActionError("Core outcome missing")
        else:
            expected = (
                "cancelled" if self.status == "admission_changed"
                else self.status
            )
            if (
                self.status in {
                    "admission_refused", "workspace_refused",
                    "preparation_refused", "preparation_uncertain",
                    "no_dispatchable_pages",
                }
                or self.core_review.execution.status != expected
            ):
                raise TeacherDispatchActionError("bridge contradicts Core result")


def _currently_admitted(wheelhouse: Path) -> bool:
    """Invoke the built-in E3B1 policy; no public admission injection seam."""
    try:
        report = inspect_live_paper_admission(wheelhouse)
        return (
            isinstance(report, LivePaperAdmissionV1)
            and report.status == "admitted"
            and report.qualified_modules == _ALLOWED
            and report.action_time_only is True
            and report.can_skip_second_consent is False
            and report.source_retention_authorized is False
        )
    except (Exception, KeyboardInterrupt):
        return False


def _workspace_matches(root: Path) -> bool:
    try:
        return _active_core_workspace_matches(root) is True
    except (Exception, KeyboardInterrupt):
        return False


def _matches_retention(
    retention: AuthorizedRetentionResultV1,
    prepared: PreparedDispatchBatchV1,
) -> bool:
    """Bind the fresh #18 request collection to exactly these Core receipts."""
    if (
        not isinstance(prepared, PreparedDispatchBatchV1)
        or prepared.report.plan != retention.report.plan
        or len(prepared.report.sources) != len(retention.report.sources)
    ):
        return False
    return all(
        a.source_number == b.source_number
        and a.retention_status == "retained"
        and a.retained_source == b.retained_source
        for a, b in zip(
            prepared.report.sources, retention.report.sources, strict=True
        )
    )


def render_teacher_dispatch_action(result: TeacherDispatchActionResultV1) -> str:
    """Aggregate physical pages, never expose routes, filenames or module output."""
    if not isinstance(result, TeacherDispatchActionResultV1):
        raise TeacherDispatchActionError("typed bridge result required")
    lines = [
        "Returned papers - teacher-approved Core processing",
        f"Action status: {result.status}.",
    ]
    if result.core_review is None:
        lines.append("No verified Core dispatch result is available.")
        if result.status == "uncertain":
            lines.append(
                "Effects may have occurred; reconcile Core and producer state."
            )
        else:
            lines.append("No producer handler was authorized by this action.")
    else:
        core = result.core_review
        counts = Counter(
            page.status
            for source in core.execution.report.sources
            for page in source.pages
        )
        lines.append(f"Core action: {core.execution.status}.")
        lines.append(
            f"Core attempted physical pages: {core.execution.attempted_pages}."
        )
        for status, count in sorted(counts.items()):
            lines.append(f"  {status}: {count}")
        review_counts = Counter(page.review_state for page in core.pages)
        for review_state, count in sorted(review_counts.items()):
            lines.append(f"  Core review {review_state}: {count}")
        if result.status in {"uncertain", "partial", "blocked"}:
            lines.append(
                "Review incomplete or uncertain pages; no automatic replay."
            )
        from paper_data_suite.returned_paper_teacher_results import (
            render_core_paper_results,
        )

        lines.append(render_core_paper_results(core).rstrip("\n"))
    lines.extend((
        "A handler return is NOT confirmed evidence capture or a grade.",
        "No grade publication is asserted; no automatic retry is allowed.",
        "Core custody from first consent is durable and is not repeated here.",
    ))
    return "\n".join(lines) + "\n"


def run_teacher_retained_paper_dispatch(
    retention: AuthorizedRetentionResultV1,
    wheelhouse: Path,
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
) -> TeacherDispatchActionResultV1:
    """One #18 execution, with genuine separate D2 consent and fresh E3B1 gates.

    No injected prepare/admission/dispatcher/qualified_modules callback exists
    in the public action. Core re-verifies retained bytes before consent,
    after consent, and before each physical-page handler attempt.
    """
    if (
        not isinstance(retention, AuthorizedRetentionResultV1)
        or retention.status != "retained"
        or retention.approved is not True
        or not isinstance(wheelhouse, Path)
        or not all(callable(getattr(stream, name, None)) for stream, name in (
            (input_stream, "readline"), (output, "write"), (output, "flush"),
        ))
        or not callable(show_header)
    ):
        raise TeacherDispatchActionError(
            "complete Core retention and explicit teacher interaction required"
        )

    def finish(
        status: BridgeStatus, core_review: CoreReviewResultV1 | None = None,
    ) -> TeacherDispatchActionResultV1:
        result = TeacherDispatchActionResultV1(status, core_review)
        show_header("Returned Papers - Core Processing Result")
        output.write("\n" + render_teacher_dispatch_action(result))
        return result

    # Never decode teacher pages or display a dispatch prompt on an unsupported
    # installed environment. Neither this nor first retention creates authority.
    if not _currently_admitted(wheelhouse):
        return finish("admission_refused")
    root = retention.report.plan.workspace_root
    if not _workspace_matches(root):
        return finish("workspace_refused")
    try:
        batch = prepare_retained_pds2_requests(retention)
    except (Exception, KeyboardInterrupt):
        return finish("preparation_uncertain")
    if not _matches_retention(retention, batch):
        return finish("preparation_uncertain")
    if batch.status == "uncertain":
        return finish("preparation_uncertain")
    if batch.status == "blocked":
        return finish("preparation_refused")
    if batch.status == "no_dispatchable_pages":
        return finish("no_dispatchable_pages")
    if batch.status != "ready" or not batch.candidates:
        return finish("preparation_refused")

    admission_changed = False

    def second_approval(review: DispatchReviewV1) -> DispatchDecisionV1:
        nonlocal admission_changed
        cancel = DispatchDecisionV1(
            "cancel", review.plan_digest, review.challenge,
        )
        # This is a Core-generated review, not a UI-supplied authorization.
        if (
            review.workspace_root != root
            or review.eligible_modules != tuple(sorted(_ALLOWED))
            or not _workspace_matches(root)
        ):
            admission_changed = True
            return cancel
        try:
            decision = ask_teacher_second_dispatch_consent(
                review,
                input_stream=input_stream,
                output=output,
                show_header=show_header,
                workspace_guard=_workspace_matches,
            )
        except (Exception, KeyboardInterrupt):
            return cancel
        if (
            not isinstance(decision, DispatchDecisionV1)
            or decision.decision != "approve"
            or decision.plan_digest != review.plan_digest
            or decision.challenge != review.challenge
        ):
            return cancel
        # Admission may be invalidated while the teacher reads the review.
        # Reinspect actual installed payload, profiles and workspace AFTER input.
        if not _currently_admitted(wheelhouse) or not _workspace_matches(root):
            admission_changed = True
            return cancel
        return decision

    try:
        core = execute_with_core_review(
            batch, approve=second_approval, qualified_modules=_ALLOWED,
        )
        if (
            not isinstance(core, CoreReviewResultV1)
            or core.execution.report.plan != retention.report.plan
            or len(core.pages) != sum(
                len(source.pages) for source in core.execution.report.sources
            )
        ):
            raise TeacherDispatchActionError("Core review result inconsistent")
    except (Exception, KeyboardInterrupt):
        # A handler or Core writer could have acted before an exception.
        # Never retry, and never claim that nothing was written.
        return finish("uncertain")
    if admission_changed and core.execution.status == "cancelled":
        return finish("admission_changed", core)
    if core.execution.status == "completed":
        return finish("completed", core)
    if core.execution.status == "partial":
        return finish("partial", core)
    if core.execution.status == "blocked":
        return finish("blocked", core)
    if core.execution.status == "cancelled":
        return finish("cancelled", core)
    if core.execution.status == "uncertain":
        return finish("uncertain", core)
    return finish("uncertain")


__all__ = (
    "TeacherDispatchActionError", "TeacherDispatchActionResultV1",
    "render_teacher_dispatch_action", "run_teacher_retained_paper_dispatch",
)
