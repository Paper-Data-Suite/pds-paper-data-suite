"""Suite #18 Slice 3: prepare Core dispatch requests from retained bytes only.

No module discovery, dispatch, handler, failure writer or workspace mutation.
A #17 preview and an approval callback are not route or replay authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Literal

from pds_core.module_dispatch import RouteDispatchRequest
from pds_core.pds2 import parse_pds2_payload
from pds_core.routing_models import RouteLocator

from paper_data_suite.returned_paper_authorized_retention import (
    AuthorizedRetentionResultV1,
    _no_links,
    _sha256,
    _verify_retained,
)
from paper_data_suite.returned_paper_preview_contract import PagePreview
from paper_data_suite.returned_paper_processing_contract import (
    PageProcessingStatus,
    PaperProcessingReportV1,
    PhysicalPageOutcomeV1,
    SourceProcessingOutcomeV1,
)
from paper_data_suite.returned_paper_readonly_decode import (
    DecodedPage,
    DecodeLimits,
    DecoderBackendUnavailable,
    DecodeResourceLimit,
    DecodeSourceError,
    PageDecoder,
    _read_source,
    _source_format,
    decode_with_optional_backends,
)

PreparationStatus = Literal[
    "ready", "no_dispatchable_pages", "blocked", "uncertain",
]
PreparationReason = Literal[
    "none", "no_valid_selected_routes", "decoder_unavailable",
    "retained_unverifiable", "source_observation_changed", "decode_failed",
]
_MAX_SOURCES: Final[int] = 8


class RetainedRequestError(ValueError):
    """Source/authorization input is not eligible for retained request review."""


@dataclass(frozen=True, slots=True, repr=False)
class PreparedPageRequestV1:
    """Exactly one teacher-selected physical page and a real Core request."""

    source_number: int
    page_number: int
    request: RouteDispatchRequest

    def __post_init__(self) -> None:
        if (
            type(self.source_number) is not int
            or self.source_number < 1
            or type(self.page_number) is not int
            or self.page_number < 1
            or not isinstance(self.request, RouteDispatchRequest)
            or self.request.source_page_number != self.page_number
        ):
            raise RetainedRequestError("invalid Core page request or position")


@dataclass(frozen=True, slots=True, repr=False)
class PreparedDispatchBatchV1:
    """Ephemeral request handoff, not processing permission or durable custody."""

    status: PreparationStatus
    reason: PreparationReason
    report: PaperProcessingReportV1
    candidates: tuple[PreparedPageRequestV1, ...]
    contract_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise RetainedRequestError("unsupported request contract")
        if self.status not in {
            "ready", "no_dispatchable_pages", "blocked", "uncertain",
        } or self.reason not in {
            "none", "no_valid_selected_routes", "decoder_unavailable",
            "retained_unverifiable", "source_observation_changed", "decode_failed",
        }:
            raise RetainedRequestError("invalid preparation status")
        if not isinstance(self.report, PaperProcessingReportV1):
            raise RetainedRequestError("Core custody report is required")
        if type(self.candidates) is not tuple or len(self.candidates) > 512:
            raise RetainedRequestError("candidate count exceeds review limits")
        if (self.status == "ready") != bool(self.candidates):
            raise RetainedRequestError("ready status must match prepared requests")
        if self.status == "ready" and self.reason != "none":
            raise RetainedRequestError("ready requests cannot carry a refusal")
        if self.status == "no_dispatchable_pages" and (
            self.candidates or self.reason != "no_valid_selected_routes"
        ):
            raise RetainedRequestError("unroutable pages cannot claim requests")
        if self.status in {"blocked", "uncertain"} and self.candidates:
            raise RetainedRequestError("blocked requests must fail closed")
        selected = {
            (page.source_number, page.page_number)
            for page in self.report.plan.selected_pages
        }
        positions: list[tuple[int, int]] = []
        for candidate in self.candidates:
            if not isinstance(candidate, PreparedPageRequestV1):
                raise RetainedRequestError("candidate is not typed")
            pair = (candidate.source_number, candidate.page_number)
            if (
                candidate.source_number > len(self.report.sources)
                or pair not in selected
                or pair in positions
            ):
                raise RetainedRequestError("unselected or repeated page request")
            row = self.report.sources[candidate.source_number - 1]
            if (
                row.retained_source is None
                or row.retention_status != "retained"
                or candidate.request.retained_source != row.retained_source
                or row.pages[candidate.page_number - 1].route_locator
                != candidate.request.locator
                or row.pages[candidate.page_number - 1].status != "retained_only"
            ):
                raise RetainedRequestError("candidate contradicts Core custody")
            positions.append(pair)
        if positions != sorted(positions):
            raise RetainedRequestError("physical-page request order changed")


def _observe_retained_page(
    number: int,
    decoded: DecodedPage,
    limits: DecodeLimits,
) -> tuple[PagePreview, RouteLocator | None]:
    """Recreate #17's conservative QR decision, retaining only typed locators."""
    if decoded.failed:
        return PagePreview(number, "page_decode_failed"), None
    if decoded.truncated or len(decoded.payloads) > limits.max_codes_per_page:
        return PagePreview(number, "ambiguous_qr"), None
    unique = tuple(dict.fromkeys(decoded.payloads))
    if not unique:
        return PagePreview(number, "missing_qr"), None
    if len(unique) != 1:
        return PagePreview(number, "ambiguous_qr"), None
    value = unique[0]
    if len(value) > limits.max_code_length:
        return PagePreview(number, "invalid_or_foreign_qr"), None
    try:
        locator = parse_pds2_payload(value)
    except (ValueError, TypeError, AttributeError):
        return PagePreview(number, "invalid_or_foreign_qr"), None
    if not isinstance(locator, RouteLocator):
        raise RetainedRequestError("Core parser did not return a typed locator")
    return PagePreview(number, "candidate_unverified", locator.module_id), locator


def _report_with_statuses(
    existing: PaperProcessingReportV1,
    updates: dict[
        tuple[int, int], tuple[PageProcessingStatus, RouteLocator | None]
    ],
    *,
    uncertain_source: int | None = None,
) -> PaperProcessingReportV1:
    sources: list[SourceProcessingOutcomeV1] = []
    for source in existing.sources:
        pages: list[PhysicalPageOutcomeV1] = []
        for page in source.pages:
            status, locator = updates.get(
                (source.source_number, page.page_number),
                (page.status, page.route_locator),
            )
            if uncertain_source == source.source_number and (
                page.status != "not_selected"
            ):
                status, locator = "uncertain", None
            pages.append(PhysicalPageOutcomeV1(
                source.source_number,
                page.page_number,
                status,
                route_locator=locator,
            ))
        sources.append(SourceProcessingOutcomeV1(
            source.source_number,
            "uncertain" if source.source_number == uncertain_source
            else source.retention_status,
            tuple(pages),
            source.retained_source,
        ))
    return PaperProcessingReportV1(existing.plan, tuple(sources))


def prepare_retained_pds2_requests(
    retention: AuthorizedRetentionResultV1,
    *,
    decode: PageDecoder = decode_with_optional_backends,
    limits: DecodeLimits = DecodeLimits(),
) -> PreparedDispatchBatchV1:
    """Reinspect all approved Core bytes and construct, never execute, requests.

    Requires a fully retained approval batch. On any byte/QR inconsistency the
    *entire* request collection is refused; no partial speculative dispatch.
    """
    if (
        not isinstance(retention, AuthorizedRetentionResultV1)
        or not retention.approved
        or retention.status != "retained"
        or not callable(decode)
        or not isinstance(limits, DecodeLimits)
    ):
        raise RetainedRequestError("complete approved Core retention is required")
    report = retention.report
    if len(report.sources) > _MAX_SOURCES:
        raise RetainedRequestError("source count exceeds review limit")
    selected = {
        (page.source_number, page.page_number)
        for page in report.plan.selected_pages
    }
    selected_sources = {source_number for source_number, _ in selected}
    for index in sorted(selected_sources):
        row = report.sources[index - 1]
        if (
            row.retention_status != "retained"
            or row.retained_source is None
            or any(
                page.status != "retained_only"
                for page in row.pages
                if (index, page.page_number) in selected
            )
        ):
            raise RetainedRequestError("retention report is not ready for review")

    prepared: list[PreparedPageRequestV1] = []
    updates: dict[
        tuple[int, int], tuple[PageProcessingStatus, RouteLocator | None]
    ] = {}
    for index in sorted(selected_sources):
        planned = report.plan.sources[index - 1]
        receipt = report.sources[index - 1].retained_source
        assert receipt is not None
        try:
            _verify_retained(
                report.plan.workspace_root, planned.observation,
                planned.source_path, receipt,
            )
            _no_links(receipt.retained_source_path)
            data = _read_source(receipt.retained_source_path, limits)
            if hashlib.sha256(data).hexdigest() != receipt.source_sha256:
                raise RetainedRequestError("retained copy digest differs")
            fmt = _source_format(receipt.retained_source_path, data)
        except (Exception, KeyboardInterrupt):
            return PreparedDispatchBatchV1(
                "uncertain", "retained_unverifiable",
                _report_with_statuses(report, updates, uncertain_source=index), (),
            )
        try:
            decoded = decode(data, fmt, limits)
        except DecoderBackendUnavailable:
            return PreparedDispatchBatchV1(
                "blocked", "decoder_unavailable", report, (),
            )
        except (DecodeResourceLimit, DecodeSourceError):
            return PreparedDispatchBatchV1(
                "blocked", "decode_failed", report, (),
            )
        except (Exception, KeyboardInterrupt):
            return PreparedDispatchBatchV1(
                "blocked", "decode_failed", report, (),
            )
        if (
            type(decoded) is not tuple
            or len(decoded) != len(planned.observation.pages)
            or not 1 <= len(decoded) <= limits.max_pages
            or any(not isinstance(item, DecodedPage) for item in decoded)
        ):
            return PreparedDispatchBatchV1(
                "uncertain", "source_observation_changed",
                _report_with_statuses(report, updates, uncertain_source=index), (),
            )
        local_requests: list[PreparedPageRequestV1] = []
        local_updates: dict[
            tuple[int, int], tuple[PageProcessingStatus, RouteLocator | None]
        ] = {}
        try:
            for number, item in enumerate(decoded, 1):
                observed, locator = _observe_retained_page(number, item, limits)
                expected = planned.observation.pages[number - 1]
                if (observed.status, observed.candidate_module_id) != (
                    expected.status, expected.candidate_module_id
                ):
                    raise RetainedRequestError("observed QR differs from review")
                if (index, number) not in selected:
                    continue
                if locator is None:
                    local_updates[(index, number)] = ("unresolved_qr", None)
                else:
                    local_updates[(index, number)] = ("retained_only", locator)
                    local_requests.append(PreparedPageRequestV1(
                        index, number, RouteDispatchRequest(
                            locator=locator, retained_source=receipt,
                            source_page_number=number,
                        ),
                    ))
            if _sha256(receipt.retained_source_path) != receipt.source_sha256:
                raise RetainedRequestError("retained source changed during decode")
        except (Exception, KeyboardInterrupt):
            return PreparedDispatchBatchV1(
                "uncertain", "source_observation_changed",
                _report_with_statuses(report, updates, uncertain_source=index), (),
            )
        prepared.extend(local_requests)
        updates.update(local_updates)

    final_report = _report_with_statuses(report, updates)
    if not prepared:
        return PreparedDispatchBatchV1(
            "no_dispatchable_pages", "no_valid_selected_routes",
            final_report, (),
        )
    return PreparedDispatchBatchV1(
        "ready", "none", final_report, tuple(sorted(
            prepared, key=lambda request: (request.source_number, request.page_number)
        )),
    )


__all__ = [
    "RetainedRequestError", "PreparationStatus", "PreparationReason",
    "PreparedPageRequestV1", "PreparedDispatchBatchV1",
    "prepare_retained_pds2_requests",
]
