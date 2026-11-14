"""Suite #18 Slice 5: Core v2 failure occurrences and deliberate review handoff.

A single execution captures real Core outcomes transiently; only Core's v2
writers persist failure/resolution records. No automatic replay or grade action.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal

from pds_core.module_dispatch import (
    RouteDispatchFailure,
    RouteDispatchOutcome,
    RouteDispatchRequest,
)
from pds_core.module_profiles import ModuleRegistry
from pds_core.scan_failure_metadata import (
    ROUTING_FAILURE_SCHEMA_VERSION,
    RoutingFailureMetadata,
    load_routing_failure_metadata,
    routing_failure_metadata_from_dispatch_failure,
    routing_failure_metadata_path,
    write_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import (
    create_scan_resolution_metadata,
    load_scan_resolution_metadata,
    scan_resolution_metadata_path,
    write_scan_resolution_metadata,
)

from paper_data_suite.returned_paper_authorized_retention import _no_links
from paper_data_suite.returned_paper_ordered_dispatch import (
    Approver,
    DispatchBatch,
    OrderedDispatchResultV1,
    RegistryFactory,
    _core_dispatch,
    _default_registry,
    _verify_batch,
    execute_prepared_paper_batch,
)
from paper_data_suite.returned_paper_processing_contract import PageProcessingStatus
from paper_data_suite.returned_paper_readonly_decode import (
    DecodeLimits,
    PageDecoder,
    decode_with_optional_backends,
)
from paper_data_suite.returned_paper_retained_requests import PreparedDispatchBatchV1

ReviewState = Literal[
    "not_required", "recorded", "write_uncertain", "manual_review",
]
DeferChoice = Literal["defer", "cancel"]
_MAX_FAILURES: Final[int] = 512


class CoreReviewError(ValueError):
    """Invalid, nonauthorizing or contradictory Core review request."""


@dataclass(frozen=True, slots=True, repr=False)
class ReviewPageV1:
    """Separate v2 review receipt; never overwrites a dispatch outcome."""

    source_number: int
    page_number: int
    dispatch_status: PageProcessingStatus
    review_state: ReviewState
    failure_id: str | None = None
    failure_category: str | None = None
    automatic_retry_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            type(self.source_number) is not int or self.source_number < 1
            or type(self.page_number) is not int or self.page_number < 1
            or self.review_state not in {
                "not_required", "recorded", "write_uncertain", "manual_review",
            }
        ):
            raise CoreReviewError("invalid review page state")
        if self.automatic_retry_allowed is not False:
            raise CoreReviewError("automatic producer retry is not supported")
        if (self.review_state == "recorded") != (self.failure_id is not None):
            raise CoreReviewError("recorded failure requires a verified ID")
        if self.failure_id is not None and (
            type(self.failure_id) is not str
            or re.fullmatch(r"failure_[A-Za-z0-9_-]+", self.failure_id) is None
        ):
            raise CoreReviewError("invalid Core failure ID")
        if self.review_state == "not_required" and self.failure_category is not None:
            raise CoreReviewError("unneeded review cannot claim failure category")


@dataclass(frozen=True, slots=True, repr=False)
class CoreReviewResultV1:
    """The original execution report plus separately verified Core review IDs."""

    execution: OrderedDispatchResultV1
    pages: tuple[ReviewPageV1, ...]
    contract_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        if self.contract_version != "1" or type(self.pages) is not tuple:
            raise CoreReviewError("unsupported review contract")
        if any(not isinstance(page, ReviewPageV1) for page in self.pages):
            raise CoreReviewError("review page rows must be typed")
        if not isinstance(self.execution, OrderedDispatchResultV1):
            raise CoreReviewError("Core dispatch execution result required")
        expected = tuple(
            (source.source_number, page.page_number, page.status)
            for source in self.execution.report.sources
            for page in source.pages
        )
        actual = tuple(
            (page.source_number, page.page_number, page.dispatch_status)
            for page in self.pages
        )
        if actual != expected:
            raise CoreReviewError("review must reconcile every physical page")


@dataclass(frozen=True, slots=True, repr=False)
class DeferredReviewV1:
    """Single Core failure review; no target/QR/body disclosed in UI repr."""

    failure_id: str
    challenge: str
    append_only: Literal[True] = True
    automatic_retry_allowed: Literal[False] = False


@dataclass(frozen=True, slots=True, repr=False)
class DeferDecisionV1:
    decision: DeferChoice
    failure_id: str
    challenge: str


@dataclass(frozen=True, slots=True, repr=False)
class DeferredReviewResultV1:
    state: Literal["cancelled", "appended", "write_uncertain"]
    failure_id: str
    resolution_id: str | None = None
    automatic_retry_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if self.state not in {"cancelled", "appended", "write_uncertain"}:
            raise CoreReviewError("unsupported Core resolution result")
        if (self.state == "appended") != (self.resolution_id is not None):
            raise CoreReviewError("unverified resolution cannot claim append")
        if self.automatic_retry_allowed is not False:
            raise CoreReviewError("automatic producer retry is not supported")


FailureWriter = Callable[[Path, RoutingFailureMetadata], Path]
FailureLoader = Callable[[Path, str], RoutingFailureMetadata]
FailureIdFactory = Callable[[], str]
Clock = Callable[[], str]
DeferredApprover = Callable[[DeferredReviewV1], DeferDecisionV1]


def _failure_id() -> str:
    return "failure_" + secrets.token_hex(16)


def _resolution_id() -> str:
    return "resolution_" + secrets.token_hex(16)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guard_core_review_tree(workspace: Path) -> None:
    """Refuse existing linked/reparse review ancestors before Core I/O.

    This is a best-effort safety gate, not a race-proof file-handle boundary.
    """
    _no_links(workspace)
    for folder in (
        workspace / "scans",
        workspace / "scans" / "review",
        workspace / "scans" / "review" / "resolutions",
    ):
        if folder.exists() or folder.is_symlink():
            _no_links(folder)


def _generic_failure(
    request: RouteDispatchRequest,
    *,
    failure_id: str,
    created_at: str,
    category: str,
    stage: str,
    message: str,
) -> RoutingFailureMetadata:
    """Typed Core occurrence without unsafe exception text or inferred target."""
    retained = request.retained_source
    return RoutingFailureMetadata(
        schema_version=ROUTING_FAILURE_SCHEMA_VERSION,
        failure_id=failure_id,
        scope="page",
        stage=stage,
        created_at=created_at,
        failure_category=category,
        failure_message=message,
        source_filename=retained.source_filename,
        source_scan_id=retained.source_scan_id,
        source_sha256=retained.source_sha256,
        retained_source_path=retained.retained_source_relative_path,
        review_copy_path=None,
        source_page_number=request.source_page_number,
        detected_payload=None,
        route_locator=request.locator,
        target=None,
        module_details={},
    )


def _from_actual(
    failure: RouteDispatchFailure,
    *,
    failure_id: str,
    created_at: str,
) -> RoutingFailureMetadata:
    """Use Core's own error mapping, stripping potentially sensitive messages."""
    mapped = routing_failure_metadata_from_dispatch_failure(
        failure, failure_id=failure_id, created_at=created_at,
    )
    return _generic_failure(
        failure.request,
        failure_id=failure_id,
        created_at=created_at,
        category=mapped.failure_category,
        stage=mapped.stage,
        message="Core reported a page-level routing or module failure.",
    )


def _from_unresolved(
    request: RouteDispatchRequest | None,
    batch: PreparedDispatchBatchV1,
    source_number: int,
    page_number: int,
    failure_id: str,
    created_at: str,
) -> RoutingFailureMetadata:
    """An unresolved selected physical page has no invented route locator."""
    if request is not None:
        raise CoreReviewError("unresolved page cannot carry a dispatch request")
    source = batch.report.sources[source_number - 1]
    receipt = source.retained_source
    if receipt is None or source.retention_status != "retained":
        raise CoreReviewError("unresolved page has no Core retained provenance")
    observed = batch.report.plan.sources[source_number - 1].observation
    status = observed.pages[page_number - 1].status
    category, stage = {
        "missing_qr": ("payload_missing", "payload"),
        "unreadable_qr": ("payload_unreadable", "payload"),
        "invalid_or_foreign_qr": ("payload_invalid", "payload"),
        "ambiguous_qr": ("route_ambiguous", "payload"),
        "page_decode_failed": ("payload_unreadable", "decoding"),
    }.get(status, ("payload_unreadable", "decoding"))
    return RoutingFailureMetadata(
        schema_version=ROUTING_FAILURE_SCHEMA_VERSION,
        failure_id=failure_id, scope="page", stage=stage,
        created_at=created_at, failure_category=category,
        failure_message="Selected retained page requires QR review.",
        source_filename=receipt.source_filename,
        source_scan_id=receipt.source_scan_id,
        source_sha256=receipt.source_sha256,
        retained_source_path=receipt.retained_source_relative_path,
        review_copy_path=None, source_page_number=page_number,
        detected_payload=None, route_locator=None, target=None, module_details={},
    )


def execute_with_core_review(
    batch: PreparedDispatchBatchV1,
    *,
    approve: Approver,
    decode: PageDecoder = decode_with_optional_backends,
    limits: DecodeLimits = DecodeLimits(),
    registry_factory: RegistryFactory = _default_registry,
    dispatcher: DispatchBatch = _core_dispatch,
    qualified_modules: frozenset[str] = frozenset(),
    write_failure: FailureWriter = write_routing_failure_metadata,
    load_failure: FailureLoader = load_routing_failure_metadata,
    new_failure_id: FailureIdFactory = _failure_id,
    clock: Clock = _utc_now,
) -> CoreReviewResultV1:
    """Single explicit Core dispatch; preserve its result and write v2 failures.

    Review writes are attempted only after a genuinely approved processing run.
    A failed Core writer never triggers duplicate dispatch or a blind rewrite.
    """
    if (
        not isinstance(batch, PreparedDispatchBatchV1)
        or not callable(write_failure) or not callable(load_failure)
        or not callable(new_failure_id) or not callable(clock)
    ):
        raise CoreReviewError("typed batch and Core review services required")
    captured: dict[tuple[int, int], RouteDispatchFailure | None] = {}
    requests = {
        (x.source_number, x.page_number): x.request
        for x in batch.candidates
    }

    def capture(
        root: Path,
        registry: ModuleRegistry,
        ordered: tuple[RouteDispatchRequest, ...],
    ) -> tuple[RouteDispatchOutcome, ...]:
        if len(ordered) != 1:
            raise CoreReviewError("Core handler capture must be page-scoped")
        req = ordered[0]
        key = next(
            (key for key, value in requests.items() if value is req), None
        )
        if key is None or key in captured:
            raise CoreReviewError("unknown or repeated dispatch attempt")
        # Mark attempted before invoking producer code; exception = uncertainty.
        captured[key] = None
        result = dispatcher(root, registry, ordered)
        if (
            type(result) is tuple and len(result) == 1
            and isinstance(result[0], RouteDispatchFailure)
            and result[0].request == req
        ):
            captured[key] = result[0]
        return result

    execution = execute_prepared_paper_batch(
        batch,
        approve=approve, decode=decode, limits=limits,
        registry_factory=registry_factory, dispatcher=capture,
        qualified_modules=qualified_modules,
    )
    # A producer may have changed retained bytes after an earlier check.
    # Do not record an authoritative failure against changed custody bytes.
    post_dispatch_verified = (
        not execution.approved
        or (
            execution.status != "blocked"
            and _verify_batch(batch, decode, limits) == "none"
        )
    )
    selected = {
        (page.source_number, page.page_number)
        for page in execution.report.plan.selected_pages
    }
    rows: list[ReviewPageV1] = []
    reviewed = 0
    for source in execution.report.sources:
        for page in source.pages:
            key = (source.source_number, page.page_number)
            status = page.status
            original = captured.get(key)
            if not post_dispatch_verified and key in selected:
                rows.append(ReviewPageV1(
                    key[0], key[1], status, "manual_review",
                ))
                continue
            needed = (
                execution.approved
                and execution.status != "blocked"
                and (
                    status == "unresolved_qr"
                    or (
                        key in captured
                        and status in {
                            "dispatch_failed", "uncertain", "module_unqualified",
                        }
                    )
                )
            )
            if not needed:
                state: ReviewState = (
                    "manual_review"
                    if status in {"uncertain", "module_unqualified"}
                    else "not_required"
                )
                rows.append(ReviewPageV1(
                    source.source_number, page.page_number, status, state,
                ))
                continue
            reviewed += 1
            if reviewed > _MAX_FAILURES:
                raise CoreReviewError("review batch exceeds bounded failure count")
            failure_id = new_failure_id()
            created_at = clock()
            try:
                if status == "unresolved_qr":
                    metadata = _from_unresolved(
                        requests.get(key), batch, key[0], key[1],
                        failure_id, created_at,
                    )
                elif original is not None:
                    metadata = _from_actual(
                        original, failure_id=failure_id, created_at=created_at,
                    )
                else:
                    request = requests[key]
                    metadata = _generic_failure(
                        request, failure_id=failure_id,
                        created_at=created_at,
                        category="processing_error", stage="module_handling",
                        message="Handler outcome uncertain; manual review required.",
                    )
                _guard_core_review_tree(batch.report.plan.workspace_root)
                written = write_failure(batch.report.plan.workspace_root, metadata)
                _guard_core_review_tree(batch.report.plan.workspace_root)
                expected = routing_failure_metadata_path(
                    batch.report.plan.workspace_root, failure_id,
                )
                _no_links(expected)
                stored = load_failure(batch.report.plan.workspace_root, failure_id)
                if written != expected or stored != metadata:
                    raise CoreReviewError("Core failure receipt not verified")
            except (Exception, KeyboardInterrupt):
                # Core exclusive write may have committed before raising; no retry.
                rows.append(ReviewPageV1(
                    key[0], key[1], status, "write_uncertain",
                    failure_category=page.failure_category,
                ))
                continue
            rows.append(ReviewPageV1(
                key[0], key[1], status, "recorded", failure_id,
                metadata.failure_category,
            ))
    return CoreReviewResultV1(execution, tuple(rows))


def append_deferred_core_resolution(
    workspace: Path,
    failure_id: str,
    *,
    approve: DeferredApprover,
    clock: Clock = _utc_now,
    new_resolution_id: FailureIdFactory = _resolution_id,
) -> DeferredReviewResultV1:
    """Append only an explicitly approved *deferred* Core v2 review event.

    Resolving, rescanning, grading and producer replay are deliberately absent.
    Core validates canonical failure linkage and immutable provenance.
    """
    if not isinstance(workspace, Path) or not callable(approve):
        raise CoreReviewError("explicit workspace and review callback required")
    _guard_core_review_tree(workspace)
    _no_links(routing_failure_metadata_path(workspace, failure_id))
    failure = load_routing_failure_metadata(workspace, failure_id)
    review = DeferredReviewV1(failure.failure_id, secrets.token_hex(16))
    try:
        decision = approve(review)
    except (Exception, KeyboardInterrupt):
        decision = None
    if (
        not isinstance(decision, DeferDecisionV1)
        or decision.decision != "defer"
        or decision.failure_id != review.failure_id
        or decision.challenge != review.challenge
    ):
        return DeferredReviewResultV1("cancelled", failure_id)
    resolution_id = new_resolution_id()
    try:
        # Re-read canonical failure after interaction, before mutation.
        current = load_routing_failure_metadata(workspace, failure_id)
        if current != failure:
            raise CoreReviewError("linked Core failure changed during review")
        _guard_core_review_tree(workspace)
        resolution = create_scan_resolution_metadata(
            current,
            resolution_id=resolution_id,
            resolution_status="deferred",
            resolution_action="deferred",
            resolved_at=clock(),
            resolution_message="Teacher deferred review; no processing replay.",
        )
        written = write_scan_resolution_metadata(workspace, resolution)
        _guard_core_review_tree(workspace)
        _no_links(scan_resolution_metadata_path(workspace, resolution_id))
        if (
            written != scan_resolution_metadata_path(workspace, resolution_id)
            or load_scan_resolution_metadata(workspace, resolution_id) != resolution
        ):
            raise CoreReviewError("Core resolution receipt not verified")
    except (Exception, KeyboardInterrupt):
        return DeferredReviewResultV1("write_uncertain", failure_id)
    return DeferredReviewResultV1("appended", failure_id, resolution_id)


__all__ = [
    "CoreReviewError", "ReviewPageV1", "CoreReviewResultV1",
    "DeferredReviewV1", "DeferDecisionV1", "DeferredReviewResultV1",
    "execute_with_core_review", "append_deferred_core_resolution",
]
