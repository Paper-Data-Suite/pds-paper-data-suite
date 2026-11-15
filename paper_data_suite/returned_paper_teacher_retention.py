"""#19C2: one explicit teacher approval for #18 whole-source Core custody.

This UI supplies a fresh digest/challenge-bound decision to #18's existing
retention boundary. It NEVER calls Core directly or authorizes producer dispatch.
Retain-first may durably write files even if a later receipt is uncertain.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TextIO

from paper_data_suite.returned_paper_authorized_retention import (
    Approver,
    AuthorizedRetentionResultV1,
    RetentionDecisionV1,
    RetentionReviewV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_processing_contract import (
    PaperProcessingPlanV1,
)

RetentionNavigation = Literal["back", "home", "quit"]
RetentionAction = Callable[
    [PaperProcessingPlanV1, Approver], AuthorizedRetentionResultV1
]
WorkspaceGuard = Callable[[Path], bool]
_MAX_ANSWER = 64


def _actual_retention(
    plan: PaperProcessingPlanV1, decision: Approver,
) -> AuthorizedRetentionResultV1:
    """The only production write seam; #18 alone owns Core retention."""
    return authorize_and_retain_sources(plan, approve=decision)


def _active_core_workspace_matches(root: Path) -> bool:
    """Fresh Core-selected workspace status, no implicit directory selection."""
    from paper_data_suite.workspace_setup import (
        WorkspacePresentationState,
        observe_workspace,
    )

    current = observe_workspace()
    return bool(
        current.root == root
        and current.exists
        and current.is_dir
        and current.is_writable
        and current.state is WorkspacePresentationState.EXISTING_DIRECTORY
    )


def render_teacher_retention_result(result: AuthorizedRetentionResultV1) -> str:
    """Report Core receipt states honestly without exposing private data."""
    if not isinstance(result, AuthorizedRetentionResultV1):
        raise ValueError("typed #18 retention outcome required")
    if result.status not in {
        "cancelled", "rejected", "retained", "partial", "uncertain"
    }:
        raise ValueError("unsupported #18 retention outcome")
    retained = sum(
        source.retention_status == "retained" and source.retained_source is not None
        for source in result.report.sources
    )
    uncertain = sum(
        source.retention_status == "uncertain"
        for source in result.report.sources
    )
    lines = [
        "Returned papers - Core source retention status",
        f"Status: {result.status}.",
        f"Verified Core-retained whole-file receipts: {retained}.",
        f"Uncertain source custody states: {uncertain}.",
    ]
    if result.status == "cancelled":
        lines.append("Teacher did not approve. No Core retention was requested.")
    elif result.status == "rejected":
        lines.append(
            "Source verification refused before a Core receipt was obtained."
        )
    elif result.status == "retained":
        lines.append(
            "Entire selected original files are now under durable Core custody."
        )
    elif result.status == "partial":
        lines.append(
            "Only some whole source files have verified Core custody. "
            "Do not blindly retry the batch."
        )
    else:
        lines.append(
            "Core custody may already have been written without a verified "
            "receipt. Do not retry automatically; reconcile first."
        )
    lines.extend((
        "The source originals remain owned by their original location; "
        "Core custody is not undone by Back or Quit.",
        "No producer routing, scoring, or grading was requested.",
    ))
    return "\n".join(lines) + "\n"


def run_teacher_first_retention(
    plan: PaperProcessingPlanV1,
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    execute: RetentionAction = _actual_retention,
    workspace_guard: WorkspaceGuard = _active_core_workspace_matches,
) -> RetentionNavigation:
    """At most one #18 action, with a new live prompt and no implicit retry.

    A source preflight may reject before this callback is even displayed.
    EOF, interrupt, invalid or navigational input all cancel the first consent.
    """
    if (
        not isinstance(plan, PaperProcessingPlanV1)
        or plan.authorized is not False
        or not callable(show_header)
        or not callable(execute)
        or not callable(workspace_guard)
    ):
        raise ValueError("a nonauthorizing #18 plan and UI callbacks are required")
    # The workspace typed at B2 is not itself an active Core selection.
    # No writer may run until Core's qualified current selection matches.
    try:
        if not workspace_guard(plan.workspace_root):
            raise ValueError("different active Core workspace")
    except (Exception, KeyboardInterrupt):
        output.write(
            "Active Core workspace could not be qualified or differs from "
            "the selected inbox. No Core retention requested.\n"
        )
        return "back"
    navigation: RetentionNavigation = "back"

    def decide(review: RetentionReviewV1) -> RetentionDecisionV1:
        nonlocal navigation
        if (
            not isinstance(review, RetentionReviewV1)
            or review.workspace_root != plan.workspace_root
            or review.selected_files_are_retained_whole is not True
            or not review.plan_digest
            or not review.challenge
        ):
            raise ValueError("invalid fresh #18 Core custody review")
        selected = set(review.selected_sources)
        whole_pages = sum(
            len(plan.sources[number - 1].observation.pages)
            for number in selected
        )
        selected_pages = len(review.selected_pages)
        if (
            not selected
            or any(not 1 <= number <= len(plan.sources) for number in selected)
            or review.selected_pages != tuple(
                (item.source_number, item.page_number)
                for item in plan.selected_pages
            )
        ):
            raise ValueError("retention review differs from the selected plan")
        show_header("Retain Selected Source Files? — First Consent")
        output.write(
            f"\nWhole source files: {len(selected)}; selected pages: "
            f"{selected_pages}.\n"
            f"Core will retain ALL {whole_pages} physical pages in those "
            "original files, including unselected pages.\n"
            "Original files are not altered. Core custody is durable and "
            "cannot be undone by Back or Quit.\n"
            "This approves source retention ONLY, not producer processing, "
            "scoring, or grading.\n"
            "Type RETAIN to authorize this one custody attempt, or CANCEL.\n"
            "B. Back   M. Main Menu   Q. Quit\nConfirmation: "
        )
        output.flush()
        try:
            answer = input_stream.readline(_MAX_ANSWER + 2)
        except (EOFError, KeyboardInterrupt, OSError, UnicodeError):
            navigation = "quit"
            answer = ""
        if not answer:
            navigation = "quit"
        if len(answer) > _MAX_ANSWER + 1 or any(
            ord(char) < 32 and char not in "\r\n" for char in answer
        ):
            answer = ""
        choice = answer.strip().casefold()
        if choice == "m":
            navigation = "home"
        elif choice == "q":
            navigation = "quit"
        elif choice == "b":
            navigation = "back"
        if choice == "retain":
            try:
                if not workspace_guard(plan.workspace_root):
                    choice = "cancel"
            except (Exception, KeyboardInterrupt):
                choice = "cancel"
            if choice == "cancel":
                output.write(
                    "Active Core workspace changed during consent; "
                    "retention refused.\n"
                )
        return RetentionDecisionV1(
            "approve" if choice == "retain" else "cancel",
            review.plan_digest, review.challenge,
        )

    try:
        # The one and only consequential Core custody boundary for this menu.
        result = execute(plan, decide)
        report = render_teacher_retention_result(result)
    except (Exception, KeyboardInterrupt):
        # Even if the callback/runner failed, do not imply a clean rollback.
        output.write(
            "Core source custody status could not be verified. A write may "
            "have occurred. Do not retry; reconcile Core records first.\n"
            "No producer dispatch was requested.\n"
        )
        return navigation
    show_header("Core Source Retention — Result")
    output.write("\n" + report)
    return navigation


__all__ = (
    "RetentionNavigation",
    "RetentionAction",
    "WorkspaceGuard",
    "render_teacher_retention_result",
    "run_teacher_first_retention",
)
