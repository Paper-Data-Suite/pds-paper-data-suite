"""#19C1: nonmutating teacher review of an existing #18 processing plan.

The only plan constructor is #18's build_processing_plan. This module neither
accepts a consent answer nor imports the Core retainer/producer dispatcher.
An advisory preview, plan, or rendered summary is NEVER a custody token.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from paper_data_suite.returned_paper_preview_contract import IntakePreview
from paper_data_suite.returned_paper_processing_contract import (
    PaperProcessingPlanV1,
    ProcessingContractError,
    build_processing_plan,
)


class TeacherPlanReviewError(ValueError):
    """The selected physical pages cannot be presented as an exact #18 plan."""


def render_readonly_processing_plan(plan: PaperProcessingPlanV1) -> str:
    """Show bounded counts and custody consequences, never private paths/QRs."""
    if (
        not isinstance(plan, PaperProcessingPlanV1)
        or plan.authorized is not False
        or plan.contract_version != "1"
    ):
        raise TeacherPlanReviewError("only a nonauthorizing v1 plan is renderable")

    selected_per_source: Counter[int] = Counter(
        page.source_number for page in plan.selected_pages
    )
    candidate_count = sum(
        page.observation.status == "candidate_unverified"
        for page in plan.selected_pages
    )
    source_count = len(selected_per_source)
    selected_count = len(plan.selected_pages)
    full_page_count = sum(
        len(plan.sources[number - 1].observation.pages)
        for number in selected_per_source
    )
    lines = [
        "Returned papers - processing plan REVIEW ONLY",
        "",
        f"Selected source files: {source_count}; physical pages: {selected_count}.",
        f"Unverified QR candidates: {candidate_count}; "
        f"other/unresolved pages: {selected_count - candidate_count}.",
        f"Whole-file custody would include {full_page_count} physical pages, "
        f"including {full_page_count - selected_count} unselected page(s).",
        "",
        "Selected physical pages by source:",
    ]
    for number, source in enumerate(plan.sources, 1):
        if number not in selected_per_source:
            continue
        pages = tuple(
            entry.page_number for entry in plan.selected_pages
            if entry.source_number == number
        )
        # #18 bounds every source to <=64 physical pages and <=8 sources.
        numbers = ", ".join(str(item) for item in pages)
        lines.append(
            f"  Source {number}: pages {numbers}; "
            f"{len(source.observation.pages)} physical page(s) in original."
        )
    lines.extend((
        "",
        "IMPORTANT - if separately approved later, Core retains the ENTIRE",
        "original source file for every selected source, even when only one",
        "physical page was selected. Original files remain unchanged.",
        "Core custody can have durable effects and is not undone by returning",
        "to the menu. Producer routing/scoring would require another review.",
        "",
        "This screen is NOT a retention approval or a processing result.",
        "No Core files were retained; no producer handlers or grades were written.",
        "B. Back   M. Main Menu   Q. Quit",
    ))
    return "\n".join(lines) + "\n"


def review_readonly_processing_plan(
    workspace_root: Path,
    selected_sources: tuple[Path, ...],
    preview: IntakePreview,
    physical_pages: tuple[tuple[int, int], ...],
) -> str:
    """Reconcile selection through #18's existing plan builder and render it.

    The caller must freshly verify inbox snapshot and #17 source observations.
    The resulting #18 plan remains local to this call and cannot authorize
    retention; #19C2 must create its own fresh review, challenge and consent.
    """
    try:
        plan = build_processing_plan(
            workspace_root, selected_sources, preview, physical_pages
        )
    except (ProcessingContractError, TypeError, ValueError) as error:
        raise TeacherPlanReviewError(
            "reviewed plan could not be constructed"
        ) from error
    return render_readonly_processing_plan(plan)


__all__ = (
    "TeacherPlanReviewError",
    "render_readonly_processing_plan",
    "review_readonly_processing_plan",
)
