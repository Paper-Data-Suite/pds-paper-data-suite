"""Suite #18 Slice 4: explicit Core-registry dispatch of verified retained pages.

The execution review is transient and is NOT an OS-identity or replay token.
Core owns dispatch; producers own their opaque results and durable effects.
"""

from __future__ import annotations

import hashlib
import secrets
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pds_core.module_dispatch import (
    ModuleContractCompatibilityError,
    ModuleRouteHandlingError,
    RouteDispatchFailure,
    RouteDispatchOutcome,
    RouteDispatchRequest,
    RouteDispatchSuccess,
    dispatch_routes,
)
from pds_core.module_profiles import (
    ModuleRegistry,
    UnsupportedModuleError,
    build_module_registry,
)
from pds_core.pds2 import serialize_pds2_payload
from pds_core.scan_failure_metadata import routing_failure_category_for_dispatch_error

from paper_data_suite.returned_paper_authorized_retention import (
    _sha256,
    _verify_retained,
)
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
    PageDecoder,
    _read_source,
    _source_format,
    decode_with_optional_backends,
)
from paper_data_suite.returned_paper_retained_requests import (
    PreparedDispatchBatchV1,
    _observe_retained_page,
)

DispatchStatus = Literal[
    "no_requests", "cancelled", "blocked", "completed", "partial", "uncertain",
]
DispatchReason = Literal[
    "none", "no_eligible_pages", "teacher_cancelled", "retained_changed",
    "decoder_unavailable", "registry_unavailable", "core_dispatch_failed",
]
DispatchChoice = Literal["approve", "cancel"]
_MAX_REQUESTS: Final[int] = 512
# Until official installed-wheel qualification is recorded, no profile runs.
_SLICE4_ELIGIBLE: Final[frozenset[str]] = frozenset({"scoreform", "quillan"})


class OrderedDispatchError(ValueError):
    """Contradictory or unbounded attempted dispatch request."""


@dataclass(frozen=True, slots=True, repr=False)
class DispatchReviewV1:
    """Fresh review of candidate pages; never permits execution by itself."""

    workspace_root: Path
    plan_digest: str
    challenge: str
    selected_pages: tuple[tuple[int, int], ...]
    modules: tuple[tuple[str, int], ...]
    eligible_modules: tuple[str, ...]
    retained_sources_are_immutable: Literal[True] = True
    producer_handlers_may_write: Literal[True] = True


@dataclass(frozen=True, slots=True, repr=False)
class DispatchDecisionV1:
    """One explicit local approval for the presented plan and challenge."""

    decision: DispatchChoice
    plan_digest: str
    challenge: str


@dataclass(frozen=True, slots=True, repr=False)
class DispatchGroupCountV1:
    """Safe module/class/work routing aggregation, not academic publication."""

    module_id: str | None
    class_id: str | None
    work_id: str | None
    status: PageProcessingStatus
    count: int


@dataclass(frozen=True, slots=True, repr=False)
class OrderedDispatchResultV1:
    """Suite observation only; no opaque module_result or durable success log."""

    status: DispatchStatus
    reason: DispatchReason
    approved: bool
    report: PaperProcessingReportV1
    attempted_pages: int = 0
    contract_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        if self.status not in {
            "no_requests", "cancelled", "blocked", "completed", "partial",
            "uncertain",
        } or self.reason not in {
            "none", "no_eligible_pages", "teacher_cancelled", "retained_changed",
            "decoder_unavailable", "registry_unavailable", "core_dispatch_failed",
        }:
            raise OrderedDispatchError("invalid dispatch outcome vocabulary")
        if self.contract_version != "1" or type(self.approved) is not bool:
            raise OrderedDispatchError("invalid dispatch outcome contract")
        if not isinstance(self.report, PaperProcessingReportV1):
            raise OrderedDispatchError("typed processing report required")
        if (
            type(self.attempted_pages) is not int
            or not 0 <= self.attempted_pages <= 512
        ):
            raise OrderedDispatchError("invalid attempted-page count")
        if not self.approved and self.attempted_pages:
            raise OrderedDispatchError("unapproved operation cannot claim attempts")
        if self.status in {"no_requests", "cancelled", "blocked"}:
            if self.attempted_pages:
                raise OrderedDispatchError("blocked operation cannot claim attempts")


Approver = Callable[[DispatchReviewV1], DispatchDecisionV1]
RegistryFactory = Callable[[], ModuleRegistry]
DispatchBatch = Callable[
    [Path, ModuleRegistry, tuple[RouteDispatchRequest, ...]],
    tuple[RouteDispatchOutcome, ...],
]


def _default_registry() -> ModuleRegistry:
    """No QR-named imports, diagnostics fallback or synthetic profiles."""
    return build_module_registry(discover_installed=True)


def _core_dispatch(
    root: Path,
    registry: ModuleRegistry,
    requests: tuple[RouteDispatchRequest, ...],
) -> tuple[RouteDispatchOutcome, ...]:
    return dispatch_routes(root, registry, requests)


def _batch_digest(batch: PreparedDispatchBatchV1) -> str:
    """Bind a transient review to exact workspace, Core custody and routes."""
    pieces = [str(batch.report.plan.workspace_root), batch.contract_version]
    for source in batch.report.sources:
        receipt = source.retained_source
        planned = batch.report.plan.sources[source.source_number - 1]
        pieces.extend((
            str(source.source_number), source.retention_status,
            str(planned.source_path),
            planned.observation.sha256_advisory or "missing",
        ))
        if receipt is not None:
            pieces.extend((
                receipt.source_scan_id, receipt.source_sha256,
                receipt.retained_source_relative_path,
            ))
    for choice in batch.report.plan.selected_pages:
        pieces.extend((
            str(choice.source_number), str(choice.page_number),
            choice.observation.status,
            choice.observation.candidate_module_id or "none",
        ))
    for candidate in batch.candidates:
        pieces.extend((
            str(candidate.source_number), str(candidate.page_number),
            serialize_pds2_payload(candidate.request.locator),
        ))
    digest = hashlib.sha256()
    for value in pieces:
        digest.update(value.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_batch(
    batch: PreparedDispatchBatchV1,
    decode: PageDecoder,
    limits: DecodeLimits,
) -> DispatchReason:
    """Reinspect every selected Core-retained page, including unresolved ones.

    Reinspect before/after teacher review and just before EACH handler call.
    Still no guarantee against an actively racing filesystem adversary.
    """
    report = batch.report
    selected = {
        (page.source_number, page.page_number)
        for page in report.plan.selected_pages
    }
    expected_requests = {
        (candidate.source_number, candidate.page_number): candidate
        for candidate in batch.candidates
    }
    for source_number in sorted({source for source, _ in selected}):
        planned = report.plan.sources[source_number - 1]
        row = report.sources[source_number - 1]
        receipt = row.retained_source
        if receipt is None or row.retention_status != "retained":
            return "retained_changed"
        try:
            _verify_retained(
                report.plan.workspace_root, planned.observation,
                planned.source_path, receipt,
            )
            data = _read_source(receipt.retained_source_path, limits)
            if hashlib.sha256(data).hexdigest() != receipt.source_sha256:
                return "retained_changed"
            fmt = _source_format(receipt.retained_source_path, data)
            decoded = decode(data, fmt, limits)
            if (
                type(decoded) is not tuple
                or len(decoded) != len(planned.observation.pages)
                or not 1 <= len(decoded) <= limits.max_pages
                or any(not isinstance(page, DecodedPage) for page in decoded)
            ):
                return "retained_changed"
            for number, page in enumerate(decoded, 1):
                observed, locator = _observe_retained_page(number, page, limits)
                expected = planned.observation.pages[number - 1]
                if (observed.status, observed.candidate_module_id) != (
                    expected.status, expected.candidate_module_id
                ):
                    return "retained_changed"
                key = (source_number, number)
                if key not in selected:
                    continue
                old = row.pages[number - 1]
                candidate = expected_requests.get(key)
                if candidate is None:
                    if old.status != "unresolved_qr" or locator is not None:
                        return "retained_changed"
                elif (
                    old.status != "retained_only"
                    or old.route_locator != locator
                    or candidate.request.locator != locator
                    or candidate.request.retained_source != receipt
                    or candidate.request.source_page_number != number
                ):
                    return "retained_changed"
            if _sha256(receipt.retained_source_path) != receipt.source_sha256:
                return "retained_changed"
        except DecoderBackendUnavailable:
            return "decoder_unavailable"
        except (Exception, KeyboardInterrupt):
            return "retained_changed"
    return "none"


def _with_page_changes(
    report: PaperProcessingReportV1,
    changes: dict[tuple[int, int], tuple[PageProcessingStatus, str | None]],
) -> PaperProcessingReportV1:
    rows: list[SourceProcessingOutcomeV1] = []
    for source in report.sources:
        pages: list[PhysicalPageOutcomeV1] = []
        for page in source.pages:
            state, category = changes.get(
                (source.source_number, page.page_number), (page.status, None)
            )
            pages.append(PhysicalPageOutcomeV1(
                source.source_number, page.page_number, state,
                route_locator=page.route_locator,
                failure_category=category,
            ))
        rows.append(SourceProcessingOutcomeV1(
            source.source_number, source.retention_status,
            tuple(pages), source.retained_source,
        ))
    return PaperProcessingReportV1(report.plan, tuple(rows))




def _not_attempted(
    batch: PreparedDispatchBatchV1,
    updates: dict[tuple[int, int], tuple[PageProcessingStatus, str | None]],
) -> PaperProcessingReportV1:
    """Mark every uninvoked handler explicitly, not as retained-only progress."""
    final = dict(updates)
    for candidate in batch.candidates:
        final.setdefault(
            (candidate.source_number, candidate.page_number),
            ("not_attempted", None),
        )
    return _with_page_changes(batch.report, final)


def _count_groups(report: PaperProcessingReportV1) -> tuple[DispatchGroupCountV1, ...]:
    """Reconcile all physical pages, including unknown/unrouted pages."""
    counter: Counter[
        tuple[str | None, str | None, str | None, PageProcessingStatus]
    ] = Counter()
    for source in report.sources:
        for page in source.pages:
            locator = page.route_locator
            group = (
                locator.module_id if locator is not None else None,
                locator.class_id if locator is not None else None,
                locator.work_id if locator is not None else None,
                page.status,
            )
            counter[group] += 1
    return tuple(
        DispatchGroupCountV1(*group, count)
        for group, count in sorted(counter.items(), key=lambda x: (
            x[0][0] or "", x[0][1] or "", x[0][2] or "", x[0][3]
        ))
    )


def count_ordered_dispatch_groups(
    result: OrderedDispatchResultV1,
) -> tuple[DispatchGroupCountV1, ...]:
    if not isinstance(result, OrderedDispatchResultV1):
        raise OrderedDispatchError("typed dispatch outcome required")
    return _count_groups(result.report)


def _safe_failure_category(error: Exception) -> str:
    try:
        return routing_failure_category_for_dispatch_error(error)
    except (Exception, KeyboardInterrupt):
        return "processing_error"


def execute_prepared_paper_batch(
    batch: PreparedDispatchBatchV1,
    *,
    approve: Approver,
    decode: PageDecoder = decode_with_optional_backends,
    limits: DecodeLimits = DecodeLimits(),
    registry_factory: RegistryFactory = _default_registry,
    dispatcher: DispatchBatch = _core_dispatch,
    qualified_modules: frozenset[str] = frozenset(),
) -> OrderedDispatchResultV1:
    """Explicitly approve and Core-dispatch verified pages one at a time.

    No handler replay, producer-result serialization, or cross-repo rollback.
    Empty qualified_modules is a deliberate no-execution default.
    Expected Core failures are per-page. Unexpected in-flight errors stop.
    """
    if (
        not isinstance(batch, PreparedDispatchBatchV1)
        or not callable(approve)
        or not callable(decode)
        or not isinstance(limits, DecodeLimits)
        or not callable(registry_factory)
        or not callable(dispatcher)
        or type(qualified_modules) is not frozenset
        or any(
            type(name) is not str or name not in _SLICE4_ELIGIBLE
            for name in qualified_modules
        )
    ):
        raise OrderedDispatchError("typed batch and explicit execution seam required")
    if batch.status == "no_dispatchable_pages":
        return OrderedDispatchResultV1(
            "no_requests", "no_eligible_pages", False, batch.report,
        )
    if batch.status != "ready" or not 1 <= len(batch.candidates) <= _MAX_REQUESTS:
        raise OrderedDispatchError("only a ready Core-retained batch may execute")
    initial = _verify_batch(batch, decode, limits)
    if initial != "none":
        return OrderedDispatchResultV1(
            "blocked", initial, False, _not_attempted(batch, {}),
        )
    modules = Counter(x.request.locator.module_id for x in batch.candidates)
    review = DispatchReviewV1(
        workspace_root=batch.report.plan.workspace_root,
        plan_digest=_batch_digest(batch),
        challenge=secrets.token_hex(16),
        selected_pages=tuple(
            (x.source_number, x.page_number)
            for x in batch.report.plan.selected_pages
        ),
        modules=tuple(sorted(modules.items())),
        eligible_modules=tuple(sorted(qualified_modules)),
    )
    try:
        decision = approve(review)
    except (Exception, KeyboardInterrupt):
        decision = None
    if (
        not isinstance(decision, DispatchDecisionV1)
        or decision.decision != "approve"
        or decision.plan_digest != review.plan_digest
        or decision.challenge != review.challenge
    ):
        return OrderedDispatchResultV1(
            "cancelled", "teacher_cancelled", False, _not_attempted(batch, {}),
        )
    before_registry = _verify_batch(batch, decode, limits)
    if before_registry != "none":
        return OrderedDispatchResultV1(
            "blocked", before_registry, True, _not_attempted(batch, {}),
        )
    try:
        registry = registry_factory()
        if not isinstance(registry, ModuleRegistry):
            raise OrderedDispatchError("Core registry factory returned invalid object")
    except (Exception, KeyboardInterrupt):
        return OrderedDispatchResultV1(
            "blocked", "registry_unavailable", True, _not_attempted(batch, {}),
        )
    updates: dict[
        tuple[int, int], tuple[PageProcessingStatus, str | None]
    ] = {}
    attempted = 0
    stopped = False
    for candidate in batch.candidates:
        if _verify_batch(batch, decode, limits) != "none":
            # Other producer effects may already have happened. Do not replay.
            stopped = True
            break
        key = (candidate.source_number, candidate.page_number)
        if candidate.request.locator.module_id not in qualified_modules:
            updates[key] = ("module_unqualified", None)
            continue
        attempted += 1
        try:
            outcomes = dispatcher(
                batch.report.plan.workspace_root, registry, (candidate.request,)
            )
            if type(outcomes) is not tuple or len(outcomes) != 1:
                raise OrderedDispatchError("Core outcome cardinality mismatch")
            outcome = outcomes[0]
            if not isinstance(outcome, (RouteDispatchSuccess, RouteDispatchFailure)):
                raise OrderedDispatchError("Core dispatch result is not typed")
            if outcome.request != candidate.request:
                raise OrderedDispatchError("Core dispatch returned another request")
            if isinstance(outcome, RouteDispatchSuccess):
                if (
                    outcome.profile.module_id != candidate.request.locator.module_id
                    or outcome.resolution.locator != candidate.request.locator
                ):
                    raise OrderedDispatchError("Core dispatch identity mismatch")
                updates[key] = ("handler_returned", None)
            else:
                if isinstance(outcome.error, ModuleRouteHandlingError):
                    status: PageProcessingStatus = "uncertain"
                elif isinstance(outcome.error, (
                    UnsupportedModuleError, ModuleContractCompatibilityError,
                )):
                    status = "module_unqualified"
                else:
                    status = "dispatch_failed"
                updates[key] = (status, _safe_failure_category(outcome.error))
        except (Exception, KeyboardInterrupt):
            updates[key] = ("uncertain", "processing_error")
            stopped = True
            break
    report = _not_attempted(batch, updates) if stopped else (
        _with_page_changes(batch.report, updates)
    )
    if stopped:
        return OrderedDispatchResultV1(
            "uncertain", "core_dispatch_failed", True, report, attempted,
        )
    statuses = [status for status, _ in updates.values()]
    if any(status == "uncertain" for status in statuses):
        outcome_status: DispatchStatus = "uncertain"
    elif any(status != "handler_returned" for status in statuses):
        outcome_status = "partial"
    else:
        outcome_status = "completed"
    return OrderedDispatchResultV1(
        outcome_status, "none", True, report, attempted,
    )


__all__ = [
    "OrderedDispatchError", "DispatchReviewV1", "DispatchDecisionV1",
    "DispatchGroupCountV1", "OrderedDispatchResultV1",
    "count_ordered_dispatch_groups", "execute_prepared_paper_batch",
]
