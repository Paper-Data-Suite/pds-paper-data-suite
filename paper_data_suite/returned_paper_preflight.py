"""Suite #17 Slice 4: compact, non-authorizing returned-paper preflight.

A deliberate CLI entry presents a transient observation only. Nothing here
opens an active workspace, diagnoses executable providers, retains scans, or
calls a paper-processing handler. #18/#19 own authorization and processing.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_readonly_decode import (
    observe_selected_sources,
)
from paper_data_suite.returned_paper_routing_preflight import (
    RoutingInventory,
    collect_routing_metadata,
)

_SourceObserver = Callable[[tuple[Path, ...]], tuple[SourcePreview, ...]]
_RoutingObserver = Callable[[], RoutingInventory]

_SOURCE_LABELS = {
    "observed": "observed",
    "source_unavailable": "cannot read selected source",
    "unsupported_format": "unsupported source format",
    "resource_limit": "exceeds scan safety limits",
    "backend_unavailable": "scanner dependency unavailable",
    "source_decode_failed": "source could not be decoded",
}
_PAGE_LABELS = {
    "missing_qr": "no QR decoded (may be absent or unreadable)",
    "unreadable_qr": "QR could not be read",
    "invalid_or_foreign_qr": "invalid or non-PDS2 QR",
    "ambiguous_qr": "multiple/conflicting QR observations",
    "page_decode_failed": "page decode failed",
}
_METADATA_LABELS = {
    "not_declared": "no routing declaration",
    "declared_unvalidated": "routing declared, unvalidated",
    "owner_mismatch": "routing owner mismatch",
    "ambiguous": "conflicting routing declarations",
    "invalid_metadata": "invalid routing declaration",
    "inspection_unavailable": "routing metadata unavailable",
}
_PROFILE_LABELS = {
    "not_evaluated": "profile not checked",
    "profile_valid": "profile validated only; dispatch unqualified",
    "profile_invalid": "profile invalid",
    "profile_unavailable": "profile unavailable",
    "core_incompatible": "profile/Core incompatible",
}
_REGISTRATION_LABELS = {
    "not_checked": "registration not checked",
    "workspace_unavailable": "workspace/authorization unavailable",
    "registration_not_found": "route registration not found",
    "registration_invalid": "invalid route registration",
    "registration_inactive": "inactive route registration",
    "structurally_consistent": "structural registration check only",
}

# Bound the printed physical-page details independently of scanner limits.
_MAX_PRINT_PAGES_PER_SOURCE = 16
_MAX_ISSUES_PER_SOURCE = 12


def build_readonly_preflight(
    sources: tuple[Path, ...],
    *,
    observe: _SourceObserver = observe_selected_sources,
    routing: _RoutingObserver = collect_routing_metadata,
) -> IntakePreview:
    """Discover explicit sources and provider *metadata* without processing.

    Injected observers are for tests; the defaults call only the Slice 2
    reader and Slice 3 **metadata-only** Core reader, not profile factories.
    """
    if type(sources) is not tuple or not sources:
        raise ValueError("at least one explicitly selected source is required")
    if any(not isinstance(path, Path) for path in sources):
        raise ValueError("selected sources must be Path values")
    discovered = observe(sources)
    inventory = routing()
    return IntakePreview(discovered, inventory.applications)


def _page_text(page: PagePreview) -> str:
    if page.status == "candidate_unverified":
        assert page.candidate_module_id is not None
        return (
            f"candidate {page.candidate_module_id} — "
            f"{_REGISTRATION_LABELS[page.registration_status]}"
        )
    return _PAGE_LABELS[page.status]


def _sample_pages(source: SourcePreview) -> tuple[PagePreview, ...]:
    """Show unresolved pages first but preserve physical order in display."""
    issues = [
        item for item in source.pages
        if item.status != "candidate_unverified"
        or item.registration_status not in {"not_checked", "structurally_consistent"}
    ][:_MAX_ISSUES_PER_SOURCE]
    selected = {item.page_number for item in issues}
    for page in source.pages:
        if len(selected) >= _MAX_PRINT_PAGES_PER_SOURCE:
            break
        selected.add(page.page_number)
    return tuple(page for page in source.pages if page.page_number in selected)


def render_readonly_preflight(preview: IntakePreview) -> str:
    """Bounded, path-free presentation. No raw QR, route, or student fields."""
    if (
        not isinstance(preview, IntakePreview)
        or preview.processing_performed is not False
    ):
        raise ValueError("only an unprocessed v1 preflight may be presented")
    if preview.contract_version != "1":
        raise ValueError("unsupported preview contract")
    pages = tuple(page for source in preview.sources for page in source.pages)
    observed = sum(source.status == "observed" for source in preview.sources)
    candidates = sum(page.status == "candidate_unverified" for page in pages)
    unresolved = len(pages) - candidates
    failed = len(preview.sources) - observed
    by_module: Counter[str] = Counter()
    for page in pages:
        if page.status == "candidate_unverified":
            assert page.candidate_module_id is not None
            by_module[page.candidate_module_id] += 1
    lines = [
        "Returned papers — read-only preflight",
        "",
        (
            f"Sources: {len(preview.sources)} selected, {observed} observed, "
            f"{failed} unavailable/unsupported"
        ),
        (
            f"Physical pages observed: {len(pages)}; candidate pages: "
            f"{candidates}; other pages needing attention: {unresolved}"
        ),
        "All candidate destinations are unverified; no routing or scoring occurred.",
        "",
        "Source observations:",
    ]
    for source in preview.sources:
        lines.append(
            f"  Source {source.source_number}: {_SOURCE_LABELS[source.status]}"
            + (f", {len(source.pages)} page(s)" if source.pages else "")
        )
        sample = _sample_pages(source)
        for page in sample:
            lines.append(f"    Physical page {page.page_number}: {_page_text(page)}")
        if len(source.pages) > len(sample):
            lines.append(
                f"    ... {len(source.pages) - len(sample)} additional page(s)"
                " omitted from this compact view"
            )
    lines.append("")
    lines.append("Candidate module counts (not accepted/processed):")
    if not by_module:
        lines.append("  None")
    else:
        for module_id, count in sorted(by_module.items()):
            lines.append(f"  {module_id}: {count}")
    lines.extend(["", "Routing provider metadata (not processing permission):"])
    for row in preview.routing:
        label = _METADATA_LABELS[row.metadata_status]
        profile = _PROFILE_LABELS[row.profile_status]
        lines.append(f"  {row.module_id}: {label}; {profile}")
    lines.extend([
        "",
        "Next: review unresolved pages. Actual processing requires a separate",
        "teacher-authorized, retain-first workflow (#18/#19).",
        "STOP — no scans retained, pages dispatched, results created, "
        "or grades recorded.",
    ])
    return "\n".join(lines) + "\n"


def run_readonly_papers_preview(
    sources: tuple[Path, ...],
    *,
    observe: _SourceObserver = observe_selected_sources,
    routing: _RoutingObserver = collect_routing_metadata,
    output: TextIO | None = None,
    errors: TextIO | None = None,
) -> int:
    """Explicit, safe CLI-only preflight; return 1 if inspection incomplete."""
    out = sys.stdout if output is None else output
    err = sys.stderr if errors is None else errors
    try:
        preview = build_readonly_preflight(sources, observe=observe, routing=routing)
        out.write(render_readonly_preflight(preview))
        incomplete = any(
            source.status != "observed" for source in preview.sources
        ) or any(
            row.metadata_status == "inspection_unavailable" for row in preview.routing
        )
        return 1 if incomplete else 0
    except (Exception, KeyboardInterrupt):
        # Never print user paths, QR strings, native decoder exceptions or
        # provider traceback into a teacher terminal/automation log.
        err.write(
            "Returned-paper preflight unavailable; no processing was performed.\n"
        )
        return 1


__all__ = [
    "build_readonly_preflight", "render_readonly_preflight",
    "run_readonly_papers_preview",
]
