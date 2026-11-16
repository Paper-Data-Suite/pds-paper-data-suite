"""#19D1: safe review of fresh #18 Core-retained request preparation.

A complete Core custody receipt is a necessary precondition, not processing
permission. Only #18 parses genuine retained bytes into typed Core requests.
No producer profile, routing registry, dispatcher, or handler is imported here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
)
from paper_data_suite.returned_paper_retained_requests import (
    PreparedDispatchBatchV1,
    prepare_retained_pds2_requests,
)


class TeacherPreparationReviewError(ValueError):
    """Retained request evidence cannot safely support this read-only view."""


Prepare = Callable[[AuthorizedRetentionResultV1], PreparedDispatchBatchV1]


def render_retained_request_review(batch: PreparedDispatchBatchV1) -> str:
    """No private paths, Core locator details, student IDs, or raw QR output."""
    if not isinstance(batch, PreparedDispatchBatchV1):
        raise TeacherPreparationReviewError("typed #18 prepared batch required")
    if batch.contract_version != "1" or batch.status not in {
        "ready", "no_dispatchable_pages", "blocked", "uncertain",
    }:
        raise TeacherPreparationReviewError("unsupported prepared batch")
    selected = {
        (page.source_number, page.page_number)
        for page in batch.report.plan.selected_pages
    }
    statuses = Counter(
        page.status
        for source in batch.report.sources
        for page in source.pages
        if (source.source_number, page.page_number) in selected
    )
    candidates = Counter(
        item.request.locator.module_id for item in batch.candidates
    )
    verified = sum(
        source.retention_status == "retained"
        and source.retained_source is not None
        for source in batch.report.sources
    )
    lines = [
        "Returned papers - Core-retained request review ONLY",
        f"Preparation status: {batch.status}.",
        f"Reason: {batch.reason}.",
        f"Verified Core source receipts: {verified}.",
        f"Selected physical pages: {len(selected)}.",
        f"Prepared typed Core requests: {len(batch.candidates)}.",
        f"Unresolved selected physical pages: {statuses['unresolved_qr']}.",
        "Possible producer destinations from retained bytes (UNQUALIFIED):",
    ]
    if candidates:
        for module_id, count in sorted(candidates.items()):
            # No class/work/student ID or raw locator serialization.
            lines.append(f"  {module_id}: {count}")
    else:
        lines.append("  None")
    if batch.status == "ready":
        lines.append(
            "Routes are only prepared. No handler is qualified or approved."
        )
    elif batch.status == "no_dispatchable_pages":
        lines.append("No selected page produced a valid Core route request.")
    elif batch.status == "uncertain":
        lines.append(
            "Retained evidence changed or cannot be verified. "
            "Stop; reconcile Core custody before any further action."
        )
    else:
        lines.append(
            "Preparation blocked; check native decoding prerequisites. "
            "Do not infer routing or processing success."
        )
    lines.extend((
        "This is NOT second teacher consent or producer-dispatch permission.",
        "No producer handlers, grades, or student records were written here.",
        "A separately reviewed, freshly admitted second dispatch action is required.",
    ))
    return "\n".join(lines) + "\n"


def review_core_retained_requests(
    retention: AuthorizedRetentionResultV1,
    *,
    prepare: Prepare = prepare_retained_pds2_requests,
) -> str:
    """Reinspect actual Core-retained bytes on explicit request, never dispatch.

    The injected prepare callback is a test seam. The production default is
    #18's sole request-preparation authority, not preview/QR speculation.
    """
    if (
        not isinstance(retention, AuthorizedRetentionResultV1)
        or retention.status != "retained"
        or retention.approved is not True
        or not callable(prepare)
    ):
        raise TeacherPreparationReviewError(
            "complete approved Core source retention required"
        )
    try:
        batch = prepare(retention)
    except (Exception, KeyboardInterrupt) as error:
        raise TeacherPreparationReviewError(
            "retained source request preparation unavailable"
        ) from error
    if (
        not isinstance(batch, PreparedDispatchBatchV1)
        or batch.report.plan != retention.report.plan
        or len(batch.report.sources) != len(retention.report.sources)
        or any(
            source.retained_source != original.retained_source
            or source.retention_status not in (
                {"retained", "uncertain"}
                if batch.status == "uncertain" else {"retained"}
            )
            for source, original in zip(
                batch.report.sources, retention.report.sources, strict=True
            )
        )
    ):
        raise TeacherPreparationReviewError(
            "prepared request evidence differs from Core custody"
        )
    return render_retained_request_review(batch)


__all__ = (
    "TeacherPreparationReviewError",
    "render_retained_request_review",
    "review_core_retained_requests",
)
