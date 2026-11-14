"""Suite #18 Slice 2: explicit consent and Core retain-first custody only.

No routing registry, module handler, failure writer or PDF page dispatch is used.
The selected originals remain unmodified; Core owns new retained scan bytes.
"""

from __future__ import annotations

import hashlib
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from paper_data_suite.returned_paper_preview_contract import SourcePreview
from paper_data_suite.returned_paper_processing_contract import (
    PageProcessingStatus,
    PaperProcessingPlanV1,
    PaperProcessingReportV1,
    PhysicalPageOutcomeV1,
    SourceProcessingOutcomeV1,
    SourceRetentionStatus,
)
from paper_data_suite.returned_paper_readonly_decode import (
    DecodeLimits,
    observe_selected_sources,
)

if TYPE_CHECKING:
    from pds_core.scan_retention import RetainedSourceScan

ReviewDecision = Literal["approve", "cancel"]
RetentionRunStatus = Literal[
    "cancelled", "rejected", "retained", "partial", "uncertain",
]
_MAX_READ: Final[int] = DecodeLimits().max_source_bytes
_REPARSE_POINT: Final[int] = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class RetentionBoundaryError(ValueError):
    """An unsupported or contradictory reviewed source was rejected."""


class _SourceRefused(RetentionBoundaryError):
    def __init__(self, source_number: int) -> None:
        super().__init__("selected source cannot be safely retained")
        self.source_number = source_number


@dataclass(frozen=True, slots=True, repr=False)
class RetentionReviewV1:
    """Transient explicit review: paths are available, never printed or saved."""

    workspace_root: Path
    selected_sources: tuple[int, ...]
    selected_pages: tuple[tuple[int, int], ...]
    plan_digest: str
    challenge: str
    selected_files_are_retained_whole: Literal[True] = True


@dataclass(frozen=True, slots=True, repr=False)
class RetentionDecisionV1:
    """Consent response, NOT an OS principal or reusable security token."""

    decision: ReviewDecision
    plan_digest: str
    challenge: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedRetentionResultV1:
    """Bounded observable custody result; no page dispatch was attempted."""

    status: RetentionRunStatus
    approved: bool
    report: PaperProcessingReportV1

    def __post_init__(self) -> None:
        if self.status not in {
            "cancelled", "rejected", "retained", "partial", "uncertain",
        }:
            raise RetentionBoundaryError("invalid retention status")
        if type(self.approved) is not bool:
            raise RetentionBoundaryError("approved must be a boolean")
        if not isinstance(self.report, PaperProcessingReportV1):
            raise RetentionBoundaryError("result requires a typed report")
        if self.status == "cancelled" and self.approved:
            raise RetentionBoundaryError("cancelled result cannot be approved")
        if self.status == "retained" and not self.approved:
            raise RetentionBoundaryError("retention cannot lack approval")


Observer = Callable[[tuple[Path, ...]], tuple[SourcePreview, ...]]
Retainer = Callable[[Path, Path], "RetainedSourceScan"]
Approver = Callable[[RetentionReviewV1], RetentionDecisionV1]


def _sha256(path: Path) -> str:
    """Bounded read; do not trust source metadata or content from a callback."""
    size = path.stat().st_size
    if size < 1 or size > _MAX_READ:
        raise RetentionBoundaryError("source exceeds bounded processing limits")
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as source:
        while data := source.read(min(1024 * 1024, _MAX_READ + 1 - length)):
            length += len(data)
            if length > _MAX_READ:
                raise RetentionBoundaryError("source exceeds bounded processing limits")
            digest.update(data)
    if length != size:
        raise RetentionBoundaryError("source changed during review")
    return digest.hexdigest()


def _no_links(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise RetentionBoundaryError("absolute, nontraversing path required")
    for component in (path, *path.parents):
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise RetentionBoundaryError("linked paths are not supported")


def _verify_workspace(workspace: Path) -> None:
    _no_links(workspace)
    if not stat.S_ISDIR(workspace.lstat().st_mode):
        raise RetentionBoundaryError("workspace is not a directory")


def _selected_source_numbers(plan: PaperProcessingPlanV1) -> tuple[int, ...]:
    return tuple(sorted({page.source_number for page in plan.selected_pages}))


def _same_observation(expected: SourcePreview, fresh: SourcePreview) -> bool:
    if (
        fresh.status != "observed"
        or expected.status != fresh.status
        or expected.sha256_advisory != fresh.sha256_advisory
        or len(expected.pages) != len(fresh.pages)
    ):
        return False
    # Registration check is not a page-decoding capability/authorization claim.
    return all(
        (a.status, a.candidate_module_id) == (b.status, b.candidate_module_id)
        for a, b in zip(expected.pages, fresh.pages, strict=True)
    )


def _inspect_one(
    plan: PaperProcessingPlanV1,
    source_number: int,
    observer: Observer,
) -> None:
    chosen = plan.sources[source_number - 1]
    try:
        _verify_workspace(plan.workspace_root)
        _no_links(chosen.source_path)
        if not stat.S_ISREG(chosen.source_path.lstat().st_mode):
            raise RetentionBoundaryError("source is not a regular file")
        if chosen.source_path.suffix.casefold() not in {
            ".pdf", ".png", ".jpg", ".jpeg",
        }:
            raise RetentionBoundaryError("unsupported source format")
        expected = chosen.observation
        digest = _sha256(chosen.source_path)
        if digest != expected.sha256_advisory:
            raise RetentionBoundaryError("source differs from reviewed content")
        fresh = observer((chosen.source_path,))
        if (
            type(fresh) is not tuple
            or len(fresh) != 1
            or not isinstance(fresh[0], SourcePreview)
            or not _same_observation(expected, fresh[0])
        ):
            raise RetentionBoundaryError("physical pages differ from review")
        if _sha256(chosen.source_path) != digest:
            raise RetentionBoundaryError("source changed while observed")
    except (Exception, KeyboardInterrupt) as error:
        raise _SourceRefused(source_number) from error


def _review_digest(plan: PaperProcessingPlanV1) -> str:
    digest = hashlib.sha256()
    values = [str(plan.workspace_root), plan.contract_version]
    for index, source in enumerate(plan.sources, 1):
        values.extend((
            str(index), str(source.source_path),
            source.observation.sha256_advisory or "missing",
        ))
    for page in plan.selected_pages:
        values.extend((str(page.source_number), str(page.page_number)))
    for value in values:
        digest.update(value.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_retained(
    workspace: Path, expected: SourcePreview, path: Path,
    receipt: RetainedSourceScan,
) -> None:
    from pds_core.scan_retention import RetainedSourceScan

    if not isinstance(receipt, RetainedSourceScan):
        raise RetentionBoundaryError("Core retention did not return a receipt")
    _no_links(receipt.retained_source_path)
    if receipt.source_filename != path.name:
        raise RetentionBoundaryError("retained source filename mismatch")
    if receipt.source_sha256 != expected.sha256_advisory:
        raise RetentionBoundaryError("retained source digest mismatch")
    relative = receipt.retained_source_path.relative_to(workspace)
    if (
        relative.as_posix() != receipt.retained_source_relative_path
        or relative.parts[:2] != ("scans", "source")
        or len(relative.parts) != 4
        or not receipt.source_scan_id
    ):
        raise RetentionBoundaryError("retained source path is not Core custody")
    if _sha256(receipt.retained_source_path) != receipt.source_sha256:
        raise RetentionBoundaryError("retained Core bytes failed verification")


def _report(
    plan: PaperProcessingPlanV1,
    statuses: dict[int, PageProcessingStatus],
    receipts: dict[int, RetainedSourceScan],
) -> PaperProcessingReportV1:
    selected = {
        (page.source_number, page.page_number) for page in plan.selected_pages
    }
    rows: list[SourceProcessingOutcomeV1] = []
    for number, source in enumerate(plan.sources, 1):
        state = statuses.get(number, "not_attempted")
        retention_state: SourceRetentionStatus = (
            "retained" if state == "retained_only"
            else "uncertain" if state == "uncertain"
            else "not_retained"
        )
        pages = tuple(
            PhysicalPageOutcomeV1(
                number, page.page_number,
                (
                    "not_selected" if (number, page.page_number) not in selected
                    else state
                ),
            )
            for page in source.observation.pages
        )
        rows.append(SourceProcessingOutcomeV1(
            number, retention_state, pages, receipts.get(number),
        ))
    return PaperProcessingReportV1(plan, tuple(rows))


def authorize_and_retain_sources(
    plan: PaperProcessingPlanV1,
    *,
    approve: Approver,
    observe: Observer = observe_selected_sources,
    retain: Retainer | None = None,
) -> AuthorizedRetentionResultV1:
    """Freshly inspect, request consent, then Core-retain whole selected sources.

    The approval callback is trusted local teacher interaction, not identity
    verification. A returned Core receipt is verified, never constructed here.
    After any uncertain custody/IO operation, stop; no automatic replay.
    """
    if not isinstance(plan, PaperProcessingPlanV1) or not callable(approve):
        raise RetentionBoundaryError("typed plan and explicit approval required")
    selected_sources = _selected_source_numbers(plan)
    if not selected_sources:
        raise RetentionBoundaryError("no explicitly selected sources")
    states: dict[int, PageProcessingStatus] = {}
    receipts: dict[int, RetainedSourceScan] = {}
    for number in selected_sources:
        try:
            _inspect_one(plan, number, observe)
        except _SourceRefused:
            states[number] = "source_rejected"
            return AuthorizedRetentionResultV1(
                "rejected", False, _report(plan, states, receipts)
            )

    review = RetentionReviewV1(
        workspace_root=plan.workspace_root,
        selected_sources=selected_sources,
        selected_pages=tuple(
            (page.source_number, page.page_number) for page in plan.selected_pages
        ),
        plan_digest=_review_digest(plan),
        challenge=secrets.token_hex(16),
    )
    try:
        decision = approve(review)
    except (Exception, KeyboardInterrupt):
        decision = None
    if (
        not isinstance(decision, RetentionDecisionV1)
        or decision.decision != "approve"
        or decision.plan_digest != review.plan_digest
        or decision.challenge != review.challenge
    ):
        return AuthorizedRetentionResultV1(
            "cancelled", False, _report(plan, states, receipts)
        )

    if retain is None:
        from pds_core.scan_retention import retain_source_scan

        retain = retain_source_scan
    for number in selected_sources:
        try:
            _inspect_one(plan, number, observe)
        except _SourceRefused:
            states[number] = "source_rejected"
            return AuthorizedRetentionResultV1(
                "partial" if receipts else "rejected",
                True, _report(plan, states, receipts),
            )
        chosen = plan.sources[number - 1]
        try:
            receipt = retain(plan.workspace_root, chosen.source_path)
            _verify_retained(
                plan.workspace_root, chosen.observation, chosen.source_path,
                receipt,
            )
        except (Exception, KeyboardInterrupt):
            # Retention may have written before raising: absence of a verified
            # receipt cannot be used to claim zero writes or safe automatic retry.
            states[number] = "uncertain"
            return AuthorizedRetentionResultV1(
                "uncertain", True, _report(plan, states, receipts)
            )
        receipts[number] = receipt
        states[number] = "retained_only"
    return AuthorizedRetentionResultV1(
        "retained", True, _report(plan, states, receipts)
    )


__all__ = [
    "RetentionBoundaryError", "RetentionReviewV1", "RetentionDecisionV1",
    "AuthorizedRetentionResultV1", "authorize_and_retain_sources",
]
