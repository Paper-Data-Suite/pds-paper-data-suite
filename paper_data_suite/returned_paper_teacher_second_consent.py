"""#19D2: fresh second teacher approval callback for #18 Core dispatch.

Deliberately not wired into Teacher Home or a dispatcher by this slice.
#18 alone constructs an authentic DispatchReviewV1 at action time, then checks
its returned digest/challenge-bound decision. Even affirmative teacher consent
is NOT evidence of installed-producer qualification or Core routing permission.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from paper_data_suite.returned_paper_ordered_dispatch import (
    Approver,
    DispatchDecisionV1,
    DispatchReviewV1,
)
from paper_data_suite.returned_paper_teacher_retention import (
    WorkspaceGuard,
    _active_core_workspace_matches,
)

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_MODULE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PRODUCERS = frozenset({"scoreform", "quillan"})
_MAX_SELECTED = 512
_MAX_INPUT = 64


class SecondConsentReviewError(ValueError):
    """An untrusted or internally inconsistent dispatch review was refused."""


def _validate_review(review: DispatchReviewV1) -> tuple[int, int, int]:
    """Check review shape; only #18 may establish authentic reviewed bytes."""
    if not isinstance(review, DispatchReviewV1):
        raise SecondConsentReviewError("typed Core dispatch review required")
    root = review.workspace_root
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or root == Path(root.anchor)
        or ".." in root.parts
        or not isinstance(review.plan_digest, str)
        or not _HEX64.fullmatch(review.plan_digest)
        or not isinstance(review.challenge, str)
        or not _HEX32.fullmatch(review.challenge)
        or review.retained_sources_are_immutable is not True
        or review.producer_handlers_may_write is not True
    ):
        raise SecondConsentReviewError("invalid fresh Core dispatch review")

    pages = review.selected_pages
    if (
        type(pages) is not tuple
        or not 1 <= len(pages) <= _MAX_SELECTED
        or any(
            type(pair) is not tuple or len(pair) != 2
            or type(pair[0]) is not int or type(pair[1]) is not int
            or not 1 <= pair[0] <= 8 or not 1 <= pair[1] <= 64
            for pair in pages
        )
        or len(set(pages)) != len(pages)
    ):
        raise SecondConsentReviewError("invalid selected physical-page identities")

    groups = review.modules
    if (
        type(groups) is not tuple
        or not 1 <= len(groups) <= _MAX_SELECTED
        or any(
            type(pair) is not tuple or len(pair) != 2
            or type(pair[0]) is not str or not _MODULE.fullmatch(pair[0])
            or type(pair[1]) is not int or not 1 <= pair[1] <= _MAX_SELECTED
            for pair in groups
        )
        or len({name for name, _ in groups}) != len(groups)
    ):
        raise SecondConsentReviewError("invalid Core candidate module summary")

    eligible = review.eligible_modules
    if (
        type(eligible) is not tuple
        or len(eligible) > len(_PRODUCERS)
        or any(type(name) is not str or name not in _PRODUCERS for name in eligible)
        or len(set(eligible)) != len(eligible)
    ):
        raise SecondConsentReviewError("invalid action-time admitted module summary")
    candidate_count = sum(count for _, count in groups)
    if candidate_count > len(pages):
        raise SecondConsentReviewError("candidate requests exceed selected pages")
    eligible_count = sum(count for name, count in groups if name in eligible)
    return len(pages), candidate_count, eligible_count


def ask_teacher_second_dispatch_consent(
    review: DispatchReviewV1,
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    workspace_guard: WorkspaceGuard = _active_core_workspace_matches,
) -> DispatchDecisionV1:
    """Collect one fresh, bounded teacher decision; never invoke a handler.

    Only the future #19E approved-dispatch action may supply this callback to
    #18. The #18 caller MUST independently check installed admission and verify
    prepared Core-retained bytes before and after this callback. A forged or
    manually constructed review cannot itself cause a producer invocation.
    """
    selected_count, candidate_count, eligible_count = _validate_review(review)
    if not all(callable(v) for v in (show_header, workspace_guard)):
        raise SecondConsentReviewError("consent callbacks are unavailable")

    def cancel() -> DispatchDecisionV1:
        return DispatchDecisionV1(
            "cancel", review.plan_digest, review.challenge,
        )

    if not review.eligible_modules or not eligible_count:
        output.write(
            "No candidate pages have an admitted producer at action time. "
            "Second consent unavailable; no handlers invoked.\n"
        )
        return cancel()
    try:
        if not workspace_guard(review.workspace_root):
            raise SecondConsentReviewError("active Core workspace differs")
    except (Exception, KeyboardInterrupt):
        output.write(
            "Active Core workspace could not be verified. "
            "Second consent refused; no handlers invoked.\n"
        )
        return cancel()

    show_header("Dispatch Retained Pages? - Second Teacher Consent")
    output.write(
        f"\nSelected physical pages: {selected_count}.\n"
        f"Prepared Core route requests: {candidate_count}.\n"
        f"Requests with an admitted module candidate: {eligible_count}.\n"
        f"Requests without an admitted module: {candidate_count - eligible_count}.\n"
        f"Selected pages without a prepared route: "
        f"{selected_count - candidate_count}.\n"
        "Eligible producer IDs for this single action:\n"
    )
    for module_id in review.eligible_modules:
        count = next((n for name, n in review.modules if name == module_id), 0)
        output.write(f"  {module_id}: {count} candidate request(s)\n")
    output.write(
        "Core retained the entire original source files during first consent.\n"
        "A second approval would permit qualified producer handlers to run.\n"
        "Handlers MAY write producer-owned state, such as assessment results.\n"
        "A returned handler result is NOT a published grade or a transaction.\n"
        "Unqualified and unresolved pages will not be dispatched.\n"
        "Type DISPATCH to approve this one action-time reviewed attempt.\n"
        "Anything else, including B/M/Q, cancels.\n"
        "Confirmation: "
    )
    output.flush()
    try:
        response = input_stream.readline(_MAX_INPUT + 2)
    except (EOFError, KeyboardInterrupt, OSError, UnicodeError):
        response = ""
    if (
        not response
        or len(response) > _MAX_INPUT + 1
        or any(ord(char) < 32 and char not in "\r\n" for char in response)
        or response.strip().casefold() != "dispatch"
    ):
        output.write("Second consent cancelled; no handlers invoked.\n")
        return cancel()
    try:
        if not workspace_guard(review.workspace_root):
            raise SecondConsentReviewError("active Core workspace changed")
    except (Exception, KeyboardInterrupt):
        output.write("Active Core workspace changed; consent cancelled.\n")
        return cancel()
    # Only #18's live caller can use this decision. No action or caching here.
    return DispatchDecisionV1("approve", review.plan_digest, review.challenge)


def make_teacher_dispatch_approver(
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    workspace_guard: WorkspaceGuard = _active_core_workspace_matches,
) -> Approver:
    """Build an inert callback for the eventual #18 action-time review seam."""
    if not all(callable(v) for v in (show_header, workspace_guard)):
        raise SecondConsentReviewError("consent callbacks are unavailable")

    def approve(review: DispatchReviewV1) -> DispatchDecisionV1:
        return ask_teacher_second_dispatch_consent(
            review,
            input_stream=input_stream,
            output=output,
            show_header=show_header,
            workspace_guard=workspace_guard,
        )

    return approve


__all__ = (
    "SecondConsentReviewError",
    "ask_teacher_second_dispatch_consent",
    "make_teacher_dispatch_approver",
)
