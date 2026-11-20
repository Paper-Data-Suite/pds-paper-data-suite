"""#19E3B3: explicit post-retention Teacher Home entry to #19E3B2.

Retain-first custody is already complete before this menu is offered. V is
read-only, D is a single independent execution action, and B/M/Q navigate.
No admission is cached, no wheelhouse is inferred and no handler is retried.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TextIO

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
)

PostRetentionNavigation = Literal["back", "home", "quit"]
_MAX_CHOICE = 64
_MAX_WHEELHOUSE = 1024


class PostRetentionMenuError(ValueError):
    """No verified Core custody or usable interactive streams."""


def _read_bounded(stream: TextIO, limit: int) -> str | None:
    """No trailing overlong input may become a subsequent approval command."""
    try:
        value = stream.readline(limit + 2)
    except (EOFError, KeyboardInterrupt, OSError, UnicodeError, ValueError):
        return None
    if (
        not value
        or len(value) > limit + 1
        or any(ord(char) < 32 and char not in "\r\n" for char in value)
    ):
        return None
    return value.strip()


def _navigation(value: str) -> PostRetentionNavigation | None:
    choice = value.casefold()
    if choice == "b":
        return "back"
    if choice == "m":
        return "home"
    if choice == "q":
        return "quit"
    return None


def _wheelhouse_path(value: str) -> Path | None:
    """Validate only shape here; E3B1 does fresh, strict filesystem audits."""
    if value.startswith(("\\\\", "//")):
        return None  # Network/UNC wheels are not a local, explicit source.
    try:
        path = Path(value)
        if (
            not path.is_absolute()
            or path == Path(path.anchor)
            or ".." in path.parts
        ):
            return None
        return path
    except (OSError, ValueError, RuntimeError):
        return None


def run_post_retention_teacher_menu(
    retention: AuthorizedRetentionResultV1,
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
) -> PostRetentionNavigation:
    """Keep a single *already completed* Core receipt in local action scope.

    V may be repeated for read-only review. D is attempted at most once and
    hands the same receipt to #19E3B2. All other input returns to navigation.
    First consent is NEVER repeated in this menu, nor are handlers retried.
    """
    if (
        not isinstance(retention, AuthorizedRetentionResultV1)
        or retention.status != "retained"
        or retention.approved is not True
        or not callable(getattr(input_stream, "readline", None))
        or not callable(getattr(output, "write", None))
        or not callable(getattr(output, "flush", None))
        or not callable(show_header)
    ):
        raise PostRetentionMenuError("complete Core source receipt required")

    while True:
        output.write(
            "V. View prepared Core-retained page requests (READ ONLY)\n"
            "D. Process retained pages (separate DISPATCH consent required)\n"
            "B. Back   M. Main Menu   Q. Quit\nSelection: "
        )
        output.flush()
        response = _read_bounded(input_stream, _MAX_CHOICE)
        if response is None:
            return "back"
        navigation = _navigation(response)
        if navigation is not None:
            return navigation
        action = response.casefold()
        if action == "v":
            try:
                from paper_data_suite.returned_paper_teacher_preparation import (
                    review_core_retained_requests,
                )

                summary = review_core_retained_requests(retention)
            except (Exception, KeyboardInterrupt):
                output.write(
                    "Retained-page preparation unavailable or uncertain; "
                    "no producer handler was invoked. Reconcile Core records.\n"
                )
            else:
                show_header("Retained Core Pages - Preparation Review Only")
                output.write("\n" + summary)
            continue
        if action != "d":
            output.write("No further processing requested.\n")
            return "back"

        # A retained receipt is never a wheelhouse-selection credential. Ask
        # explicitly here; never infer a folder from the user's Downloads.
        output.write(
            "Processing may change producer-owned assessment state.\n"
            "Enter the absolute LOCAL directory holding exact official "
            "Core/ScoreForm/Quillan wheels. No scan file path is needed.\n"
            "B. Back   M. Main Menu   Q. Quit\n"
            "Official-wheel directory: "
        )
        output.flush()
        wheelhouse_input = _read_bounded(input_stream, _MAX_WHEELHOUSE)
        if wheelhouse_input is None:
            output.write("Wheelhouse selection refused; no processing requested.\n")
            return "back"
        navigation = _navigation(wheelhouse_input)
        if navigation is not None:
            return navigation
        wheelhouse = _wheelhouse_path(wheelhouse_input)
        if wheelhouse is None:
            output.write(
                "A nontraversing absolute local directory is required. "
                "No processing requested.\n"
            )
            return "back"
        try:
            # Lazy import: read-only V and normal navigation never load the
            # Core dispatch bridge. The bridge itself obtains fresh installed
            # eligibility, Core requests and independent second consent.
            from paper_data_suite.returned_paper_teacher_dispatch_action import (
                run_teacher_retained_paper_dispatch,
            )

            dispatch_result = run_teacher_retained_paper_dispatch(
                retention,
                wheelhouse,
                input_stream=input_stream,
                output=output,
                show_header=show_header,
            )
            # A Core review is an ephemeral in-session result, not a new
            # producer request or a durable Suite review queue.
            from paper_data_suite.returned_paper_teacher_dispatch_action import (
                TeacherDispatchActionResultV1,
            )

            if (
                isinstance(dispatch_result, TeacherDispatchActionResultV1)
                and dispatch_result.core_review is not None
            ):
                from paper_data_suite.returned_paper_teacher_recovery import (
                    run_teacher_core_review_menu,
                )

                return run_teacher_core_review_menu(
                    dispatch_result.core_review,
                    input_stream=input_stream,
                    output=output,
                    show_header=show_header,
                )
        except (Exception, KeyboardInterrupt):
            # The bridge may have called a handler before its failure. Never
            # report clean rollback, never call it again, never print details.
            output.write(
                "Core processing result could not be verified. Producer "
                "effects MAY have occurred. Do not retry; reconcile Core "
                "review and producer records.\n"
            )
        return "back"


__all__ = (
    "PostRetentionNavigation", "PostRetentionMenuError",
    "run_post_retention_teacher_menu",
)
