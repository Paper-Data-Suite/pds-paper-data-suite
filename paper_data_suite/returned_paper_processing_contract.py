"""Suite #18 Slice 1: nonmutating plan and outcome vocabulary.

This file deliberately contains no custody writer, routing dispatcher, provider
loading, filesystem inspection, or consent implementation. Preview observations
are advisory, not durable retained-page identities or authorization tokens.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)

if TYPE_CHECKING:
    from pds_core.routing_models import RouteLocator
    from pds_core.scan_retention import RetainedSourceScan

PROCESSING_CONTRACT_VERSION: Final[str] = "1"
_MAX_SOURCES: Final[int] = 8
_MAX_PAGES_PER_SOURCE: Final[int] = 64
_MAX_SELECTED_PAGES: Final[int] = _MAX_SOURCES * _MAX_PAGES_PER_SOURCE
_SHA256: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")

PageProcessingStatus = Literal[
    "not_selected",
    "not_attempted",
    "source_rejected",
    "retained_only",
    "unresolved_qr",
    "module_unqualified",
    "dispatch_failed",
    "handler_returned",
    "uncertain",
    "review_write_failed",
]
SourceRetentionStatus = Literal[
    "not_retained", "retained", "retention_failed", "uncertain"
]

_PAGE_STATUSES: Final[frozenset[str]] = frozenset({
    "not_selected", "not_attempted", "source_rejected", "retained_only",
    "unresolved_qr", "module_unqualified", "dispatch_failed",
    "handler_returned", "uncertain", "review_write_failed",
})
_RETENTION_STATUSES: Final[frozenset[str]] = frozenset({
    "not_retained", "retained", "retention_failed", "uncertain",
})


class ProcessingContractError(ValueError):
    """Invalid, contradictory or non-bounded #18 planning/result record."""


def _positive(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ProcessingContractError(f"{field_name} must be a positive integer")
    return value


def _absolute_safe_shape(value: object, field_name: str) -> Path:
    """Shape check only: permission, link, race and ownership checks are later."""
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        raise ProcessingContractError(
            f"{field_name} must be a nontraversing absolute Path"
        )
    if value == Path(value.anchor):
        raise ProcessingContractError(f"{field_name} cannot be a filesystem root")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class PlannedSourceV1:
    """Private selected path joined to #17's exact advisory source observation."""

    source_path: Path
    observation: SourcePreview

    def __post_init__(self) -> None:
        _absolute_safe_shape(self.source_path, "source path")
        if not isinstance(self.observation, SourcePreview):
            raise ProcessingContractError("source must use a #17 SourcePreview")
        if len(self.observation.pages) > _MAX_PAGES_PER_SOURCE:
            raise ProcessingContractError("preview exceeds maximum physical pages")


@dataclass(frozen=True, slots=True, repr=False)
class SelectedPhysicalPageV1:
    """A numbered teacher selection, not a Core RouteLocator or approval."""

    source_number: int
    page_number: int
    observation: PagePreview

    def __post_init__(self) -> None:
        _positive(self.source_number, "source number")
        _positive(self.page_number, "physical page number")
        if not isinstance(self.observation, PagePreview):
            raise ProcessingContractError("selection must use a #17 PagePreview")
        if self.observation.page_number != self.page_number:
            raise ProcessingContractError("selected physical page/preview mismatch")


@dataclass(frozen=True, slots=True, repr=False)
class PaperProcessingPlanV1:
    """A nonauthorizing, nonmutating review plan for an explicit workspace."""

    workspace_root: Path
    sources: tuple[PlannedSourceV1, ...]
    selected_pages: tuple[SelectedPhysicalPageV1, ...]
    contract_version: Literal["1"] = "1"
    authorized: Literal[False] = False

    def __post_init__(self) -> None:
        _absolute_safe_shape(self.workspace_root, "workspace")
        if self.contract_version != PROCESSING_CONTRACT_VERSION:
            raise ProcessingContractError("unsupported processing plan version")
        if self.authorized is not False:
            raise ProcessingContractError("a plan is not authorization")
        if (
            type(self.sources) is not tuple
            or not 1 <= len(self.sources) <= _MAX_SOURCES
            or any(not isinstance(x, PlannedSourceV1) for x in self.sources)
        ):
            raise ProcessingContractError("plan requires bounded source observations")
        for source_number, source in enumerate(self.sources, 1):
            if source.observation.source_number != source_number:
                raise ProcessingContractError("source positions must be one-based")
        if (
            type(self.selected_pages) is not tuple
            or not 1 <= len(self.selected_pages) <= _MAX_SELECTED_PAGES
            or any(
                not isinstance(selected, SelectedPhysicalPageV1)
                for selected in self.selected_pages
            )
        ):
            raise ProcessingContractError("plan requires bounded explicit pages")
        seen: set[tuple[int, int]] = set()
        for selected in self.selected_pages:
            key = (selected.source_number, selected.page_number)
            if key in seen:
                raise ProcessingContractError("duplicate physical page selection")
            seen.add(key)
            if selected.source_number > len(self.sources):
                raise ProcessingContractError("selected source does not exist")
            observed_source = self.sources[selected.source_number - 1].observation
            if (
                observed_source.status != "observed"
                or observed_source.sha256_advisory is None
                or selected.page_number > len(observed_source.pages)
                or (
                    observed_source.pages[selected.page_number - 1]
                    != selected.observation
                )
            ):
                raise ProcessingContractError(
                    "selected page lacks a stable observed source and advisory digest"
                )


def build_processing_plan(
    workspace_root: Path,
    paths: tuple[Path, ...],
    preview: IntakePreview,
    selected: tuple[tuple[int, int], ...],
) -> PaperProcessingPlanV1:
    """Join explicit file choices to #17 observations without reading or writing.

    The selection order is preserved; physical numbering is not synthesized.
    The returned plan cannot authorize Core retention or producer execution.
    """
    if (
        not isinstance(preview, IntakePreview)
        or preview.processing_performed is not False
    ):
        raise ProcessingContractError("an untouched #17 preview is required")
    if type(paths) is not tuple or len(paths) != len(preview.sources):
        raise ProcessingContractError("exact preview/source path mapping is required")
    if type(selected) is not tuple:
        raise ProcessingContractError("selected page coordinates must be a tuple")
    planned_sources = tuple(
        PlannedSourceV1(path, observation)
        for path, observation in zip(paths, preview.sources, strict=True)
    )
    selected_pages: list[SelectedPhysicalPageV1] = []
    for pair in selected:
        if type(pair) is not tuple or len(pair) != 2:
            raise ProcessingContractError("page selection requires (source, page)")
        source_number = _positive(pair[0], "source number")
        page_number = _positive(pair[1], "physical page number")
        if source_number > len(preview.sources):
            raise ProcessingContractError("selected source does not exist")
        source = preview.sources[source_number - 1]
        if page_number > len(source.pages):
            raise ProcessingContractError("selected page does not exist")
        selected_pages.append(
            SelectedPhysicalPageV1(
                source_number, page_number, source.pages[page_number - 1]
            )
        )
    return PaperProcessingPlanV1(
        workspace_root, planned_sources, tuple(selected_pages)
    )


@dataclass(frozen=True, slots=True, repr=False)
class PhysicalPageOutcomeV1:
    """One page-level outcome; Core locator is typed, never copied or guessed."""

    source_number: int
    page_number: int
    status: PageProcessingStatus
    route_locator: RouteLocator | None = None
    failure_category: str | None = None
    failure_id: str | None = None

    def __post_init__(self) -> None:
        _positive(self.source_number, "source number")
        _positive(self.page_number, "physical page number")
        if self.status not in _PAGE_STATUSES:
            raise ProcessingContractError("unsupported page processing status")
        if self.route_locator is not None:
            # Import only if an actual typed Core route is present.
            from pds_core.routing_models import RouteLocator, validate_route_locator

            if not isinstance(self.route_locator, RouteLocator):
                raise ProcessingContractError("route must be a real Core RouteLocator")
            try:
                validate_route_locator(self.route_locator)
            except ValueError as error:
                raise ProcessingContractError("invalid Core route locator") from error
        if self.status in {"dispatch_failed", "handler_returned"}:
            if self.route_locator is None:
                raise ProcessingContractError("dispatch state requires a Core locator")
        if self.failure_category is not None:
            if (
                type(self.failure_category) is not str
                or not _SAFE_IDENTIFIER.fullmatch(self.failure_category)
            ):
                raise ProcessingContractError("failure category must be a safe code")
        if self.failure_id is not None:
            if type(self.failure_id) is not str or not _SAFE_IDENTIFIER.fullmatch(
                self.failure_id
            ):
                raise ProcessingContractError("failure ID must be a safe Core ID")
        if self.failure_id is not None and self.failure_category is None:
            raise ProcessingContractError("failure ID requires a failure category")
        if self.status == "not_selected" and any((
            self.route_locator, self.failure_category, self.failure_id,
        )):
            raise ProcessingContractError(
                "unselected page cannot have processing proof"
            )


@dataclass(frozen=True, slots=True, repr=False)
class SourceProcessingOutcomeV1:
    """Source-level retention knowledge; a missing receipt is not no-write proof."""

    source_number: int
    retention_status: SourceRetentionStatus
    pages: tuple[PhysicalPageOutcomeV1, ...]
    retained_source: RetainedSourceScan | None = None

    def __post_init__(self) -> None:
        _positive(self.source_number, "source number")
        if self.retention_status not in _RETENTION_STATUSES:
            raise ProcessingContractError("unsupported source retention state")
        if type(self.pages) is not tuple or any(
            not isinstance(page, PhysicalPageOutcomeV1) for page in self.pages
        ):
            raise ProcessingContractError("pages must be typed immutable outcomes")
        if tuple(page.page_number for page in self.pages) != tuple(
            range(1, len(self.pages) + 1)
        ) or any(page.source_number != self.source_number for page in self.pages):
            raise ProcessingContractError("all physical pages must be represented")
        if self.retained_source is not None:
            from pds_core.scan_retention import RetainedSourceScan

            if not isinstance(self.retained_source, RetainedSourceScan):
                raise ProcessingContractError("retained source must be a Core receipt")
        if self.retention_status == "retained" and self.retained_source is None:
            raise ProcessingContractError("retained status needs a Core receipt")
        if self.retained_source is None and any(
            page.status not in {
                "not_selected", "not_attempted", "source_rejected", "uncertain",
            }
            for page in self.pages
        ):
            raise ProcessingContractError(
                "without a Core receipt, positive processing claims are forbidden"
            )
        if self.retention_status in {"not_retained", "retention_failed"}:
            if self.retained_source is not None:
                raise ProcessingContractError(
                    "unretained source cannot carry a receipt"
                )
            if any(page.status not in {
                "not_selected", "not_attempted", "source_rejected",
            } for page in self.pages):
                raise ProcessingContractError("unretained source cannot claim dispatch")


@dataclass(frozen=True, slots=True, repr=False)
class PaperProcessingReportV1:
    """Reconciled result, NOT a cross-module transaction or publication record."""

    plan: PaperProcessingPlanV1
    sources: tuple[SourceProcessingOutcomeV1, ...]
    contract_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        if self.contract_version != PROCESSING_CONTRACT_VERSION:
            raise ProcessingContractError("unsupported processing report version")
        if not isinstance(self.plan, PaperProcessingPlanV1):
            raise ProcessingContractError("report requires its original review plan")
        if (
            type(self.sources) is not tuple
            or len(self.sources) != len(self.plan.sources)
        ):
            raise ProcessingContractError("every selected source must have an outcome")
        selected = {
            (choice.source_number, choice.page_number)
            for choice in self.plan.selected_pages
        }
        for source_number, (source, planned) in enumerate(
            zip(self.sources, self.plan.sources, strict=True), 1
        ):
            if not isinstance(source, SourceProcessingOutcomeV1):
                raise ProcessingContractError("outcome source is not typed")
            if source.source_number != source_number:
                raise ProcessingContractError("outcome source order has changed")
            if len(source.pages) != len(planned.observation.pages):
                raise ProcessingContractError("all physical pages need outcomes")
            for page in source.pages:
                key = (source_number, page.page_number)
                if key not in selected and page.status != "not_selected":
                    raise ProcessingContractError(
                        "unapproved page was marked processed"
                    )
                if key in selected and page.status == "not_selected":
                    raise ProcessingContractError("selected page was silently omitted")


def count_processing_outcomes(
    report: PaperProcessingReportV1,
) -> tuple[tuple[str, int], ...]:
    """Privacy-safe exact counts, without copying module-owned result bodies."""
    if not isinstance(report, PaperProcessingReportV1):
        raise ProcessingContractError("typed #18 report required")
    counts = Counter(
        page.status for source in report.sources for page in source.pages
    )
    return tuple(sorted(counts.items()))


__all__ = [
    "PROCESSING_CONTRACT_VERSION", "ProcessingContractError",
    "PageProcessingStatus", "SourceRetentionStatus", "PlannedSourceV1",
    "SelectedPhysicalPageV1", "PaperProcessingPlanV1", "build_processing_plan",
    "PhysicalPageOutcomeV1", "SourceProcessingOutcomeV1",
    "PaperProcessingReportV1", "count_processing_outcomes",
]
