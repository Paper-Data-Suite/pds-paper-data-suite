"""#19E4A: read-only, page-complete, teacher-facing Core results.

The immutable #18 execution and Core review records are the sole evidence.
This renderer neither loads a producer nor reads/writes Core files. A handler
return is not proof of evidence capture, scoring, or grade publication.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from paper_data_suite.returned_paper_core_review import (
    CoreReviewResultV1,
    ReviewPageV1,
)
from paper_data_suite.returned_paper_ordered_dispatch import (
    count_ordered_dispatch_groups,
)
from paper_data_suite.returned_paper_processing_contract import (
    PhysicalPageOutcomeV1,
)


class TeacherPaperResultsError(ValueError):
    """A non-Core, contradictory or unbounded result cannot be displayed."""


_PAGE_LABELS: Final[dict[str, str]] = {
    "not_selected": "Not selected",
    "not_attempted": "Not attempted",
    "source_rejected": "Source rejected",
    "retained_only": "Retained; not sent to a producer",
    "unresolved_qr": "QR unresolved; no producer dispatched",
    "module_unqualified": "Producer not qualified; not dispatched",
    "dispatch_failed": "Core dispatch failed",
    "handler_returned": "Producer handler returned; evidence not confirmed",
    "uncertain": "Outcome uncertain; effects may have occurred",
    "review_write_failed": "Core review write unverified",
}
_REVIEW_LABELS: Final[dict[str, str]] = {
    "not_required": "No Core failure review required",
    "recorded": "Verified Core failure record",
    "write_uncertain": "Core review write uncertain",
    "manual_review": "Manual review required",
}
_RETENTION_LABELS: Final[dict[str, str]] = {
    "not_retained": "Not retained",
    "retained": "Retained in Core custody",
    "retention_failed": "Retention failed",
    "uncertain": "Retention uncertain; reconcile before retry",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SAFE_FAILURE = re.compile(r"failure_[A-Za-z0-9_-]{1,120}\Z")
_MAX_PAGES: Final[int] = 512


def _safe_identifier(value: str | None) -> str:
    """Never echo arbitrary route/exception strings to the teacher terminal."""
    if value is None:
        return "unknown"
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        return "withheld"
    return value


def _next_action(status: str, review_state: str) -> str:
    if (
        status in {"uncertain", "review_write_failed"}
        or review_state == "write_uncertain"
    ):
        return "Reconcile Core and producer state; do not retry blindly"
    if review_state == "recorded":
        return "Inspect verified Core failure and review disposition"
    if status == "handler_returned":
        return "Check the producer for actual evidence or scoring"
    if status == "unresolved_qr":
        return "Inspect the source page and QR manually"
    if status == "module_unqualified":
        return "Use a separately qualified producer or manual workflow"
    if status in {"not_attempted", "retained_only"}:
        return "Inspect why dispatch did not occur; no automatic replay"
    if status == "dispatch_failed":
        return "Review Core routing failure before any new action"
    if status == "source_rejected":
        return "Inspect the rejected source without a blind retention retry"
    if status == "not_selected":
        return "No action requested"
    return "Review the Core processing record"


def _checked_rows(
    result: CoreReviewResultV1,
) -> tuple[tuple[PhysicalPageOutcomeV1, ReviewPageV1], ...]:
    if not isinstance(result, CoreReviewResultV1):
        raise TeacherPaperResultsError("verified Core review result required")
    pages = tuple(
        page
        for source in result.execution.report.sources
        for page in source.pages
    )
    if (
        not 1 <= len(pages) <= _MAX_PAGES
        or len(result.pages) != len(pages)
        or any(
            (row.source_number, row.page_number, row.status)
            != (review.source_number, review.page_number, review.dispatch_status)
            for row, review in zip(pages, result.pages, strict=True)
        )
    ):
        raise TeacherPaperResultsError("physical pages differ from Core review")
    return tuple(zip(pages, result.pages, strict=True))


def _page_line(page: PhysicalPageOutcomeV1, review: ReviewPageV1) -> str:
    status = _PAGE_LABELS.get(page.status)
    review_label = _REVIEW_LABELS.get(review.review_state)
    if status is None or review_label is None:
        raise TeacherPaperResultsError("unknown Core page or review state")
    text = (
        f"  Page {page.page_number}: {status}. "
        f"Review: {review_label}."
    )
    if page.route_locator is not None:
        locator = page.route_locator
        text += (
            f" Core-parsed locator: {_safe_identifier(locator.module_id)}/"
            f"{_safe_identifier(locator.class_id)}/"
            f"{_safe_identifier(locator.work_id)}."
        )
    if review.review_state == "recorded":
        if (
            isinstance(review.failure_id, str)
            and _SAFE_FAILURE.fullmatch(review.failure_id) is not None
        ):
            text += f" Core failure ID: {review.failure_id}."
        if (
            isinstance(review.failure_category, str)
            and _SAFE_ID.fullmatch(review.failure_category) is not None
        ):
            text += f" Category: {review.failure_category}."
    text += f" Next: {_next_action(page.status, review.review_state)}."
    return text


def render_core_paper_page_detail(
    result: CoreReviewResultV1, source_number: int, page_number: int,
) -> str:
    """One-based drilldown into an existing, already verified Core result."""
    rows = _checked_rows(result)
    if (
        type(source_number) is not int or type(page_number) is not int
        or source_number < 1 or page_number < 1
    ):
        raise TeacherPaperResultsError("positive physical-page number required")
    for page, review in rows:
        if (page.source_number, page.page_number) == (source_number, page_number):
            return f"Source {source_number}\n{_page_line(page, review)}\n"
    raise TeacherPaperResultsError("physical page not present in Core result")


def render_core_paper_results(result: CoreReviewResultV1) -> str:
    """Page-complete display; only Core-validated identifiers, no private paths.

    Synchronous snapshot: shows no invented in-flight progress or publication.
    The #18 contract limits execution to eight sources, 64 pages each.
    """
    rows = _checked_rows(result)
    report = result.execution.report
    counts = Counter(page.status for page, _ in rows)
    review_counts = Counter(review.review_state for _, review in rows)
    lines = [
        "Physical-paper outcomes — verified Core execution and review",
        f"Core run: {result.execution.status}.",
        f"Physical pages accounted for: {len(rows)}.",
        f"Core handler attempts: {result.execution.attempted_pages}.",
        "Page outcomes:",
    ]
    for status, count in sorted(counts.items()):
        label = _PAGE_LABELS.get(status)
        if label is None:
            raise TeacherPaperResultsError("unknown Core processing status")
        lines.append(f"  {label}: {count}")
    lines.append("Independent Core failure/review states:")
    for state, count in sorted(review_counts.items()):
        label = _REVIEW_LABELS.get(state)
        if label is None:
            raise TeacherPaperResultsError("unknown Core review status")
        lines.append(f"  {label}: {count}")
    lines.append("Core-parsed locator groups (module / class / work):")
    for group in count_ordered_dispatch_groups(result.execution):
        lines.append(
            f"  {_safe_identifier(group.module_id)} / "
            f"{_safe_identifier(group.class_id)} / "
            f"{_safe_identifier(group.work_id)} — "
            f"{_PAGE_LABELS[group.status]}: {group.count}"
        )
    lines.append("Every physical page (including unselected pages):")
    offset = 0
    for source in report.sources:
        retention = _RETENTION_LABELS.get(source.retention_status)
        if retention is None:
            raise TeacherPaperResultsError("unknown Core custody state")
        lines.append(f"Source {source.source_number}: {retention}.")
        for _ in source.pages:
            page, review = rows[offset]
            lines.append(_page_line(page, review))
            offset += 1
    lines.extend((
        "Handler returned does NOT mean response captured, scored, or graded.",
        "A Core failure record is NOT a resolution or a successful retry.",
        "No grade publication is established by this screen.",
        "Do not retry uncertain or partially processed pages automatically.",
    ))
    return "\n".join(lines) + "\n"


__all__ = (
    "TeacherPaperResultsError",
    "render_core_paper_page_detail",
    "render_core_paper_results",
)
