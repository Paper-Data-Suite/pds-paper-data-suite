"""#19G4: explicitly selected local-file processing through existing Core custody.

This UI does not dispatch or retain anything itself. A local file is not an
inbox entry or an authority token. Only #18's plan, C2 fresh retention consent,
and E3B fresh installed admission and second consent can cause writes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TextIO

from paper_data_suite.returned_paper_preflight import (
    build_readonly_preflight,
    render_readonly_preflight,
)
from paper_data_suite.returned_paper_preview_contract import IntakePreview
from paper_data_suite.returned_paper_teacher_inbox import (
    _Closed,
    _input,
    _navigation,
    _page_choice,
    _workspace,
)
from paper_data_suite.returned_paper_teacher_retention import (
    WorkspaceGuard,
    _active_core_workspace_matches,
)

LocalNavigation = Literal["back", "home", "quit"]
Preview = Callable[[tuple[Path, ...]], IntakePreview]
Renderer = Callable[[IntakePreview], str]
_MAX_SOURCES = 8
_MAX_PAGES_PER_SOURCE = 64
_MAX_SELECTED = 512


class LocalPaperFlowError(ValueError):
    """Private or contradictory local-file selections are never printed."""


def _check_selection(paths: tuple[Path, ...], workspace: Path) -> None:
    """Shape and protected Core-custody refusal before source observation."""
    if (
        type(paths) is not tuple
        or not 1 <= len(paths) <= _MAX_SOURCES
        or any(
            not isinstance(p, Path)
            or not p.is_absolute()
            or ".." in p.parts
            or p.suffix.casefold() not in {".pdf", ".png", ".jpg", ".jpeg"}
            for p in paths
        )
        or len({os.path.normcase(os.fspath(p)) for p in paths}) != len(paths)
        or not workspace.is_absolute()
        or workspace == Path(workspace.anchor)
        or ".." in workspace.parts
    ):
        raise LocalPaperFlowError("selected source or workspace refused")
    protected = workspace / "scans"
    if any(p == workspace or p.is_relative_to(protected) for p in paths):
        raise LocalPaperFlowError("Core custody is not a new selected original")


def _workspace_ok(root: Path, guard: WorkspaceGuard) -> bool:
    try:
        return guard(root) is True
    except (Exception, KeyboardInterrupt):
        return False


def _fresh(
    paths: tuple[Path, ...], original: IntakePreview,
    preview: Preview, root: Path, guard: WorkspaceGuard,
) -> IntakePreview:
    """No cached read-only observation can authorize consequential review."""
    if not _workspace_ok(root, guard):
        raise LocalPaperFlowError("active Core workspace changed")
    current = preview(paths)
    if (
        not isinstance(current, IntakePreview)
        or current.processing_performed is not False
        or current != original
    ):
        raise LocalPaperFlowError("selected local source changed or unavailable")
    return current


def run_selected_local_paper_processing(
    paths: tuple[Path, ...],
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    preview: Preview = build_readonly_preflight,
    render: Renderer = render_readonly_preflight,
    workspace_guard: WorkspaceGuard = _active_core_workspace_matches,
) -> LocalNavigation:
    """One explicit local-file journey; only #18 may perform a first write.

    The caller has collected exact local file paths under a distinct menu
    choice. We never implicitly select all pages, a workspace, or consent.
    Test-only callback injection cannot grant public dispatcher authority.
    """
    if (
        not all(callable(x) for x in (show_header, preview, render, workspace_guard))
        or not callable(getattr(input_stream, "readline", None))
        or not callable(getattr(output, "write", None))
        or not callable(getattr(output, "flush", None))
    ):
        raise LocalPaperFlowError("local processing callbacks unavailable")
    show_header("Returned Papers — Select Local Sources")
    output.write(
        "\nDirect local files are not Core inbox entries.\n"
        "Choose the already active Core workspace explicitly; no fallback.\n"
        "Entering this screen and selecting pages never retains or dispatches.\n"
    )
    try:
        raw = _input(
            input_stream, output, "Active Core workspace directory (B/M/Q): ",
            4096,
        )
        navigation = _navigation(raw)
        if navigation is not None:
            return navigation
        root = _workspace(raw)
        _check_selection(paths, root)
        if not _workspace_ok(root, workspace_guard):
            output.write(
                "Active Core workspace differs or cannot be verified. "
                "No source was read or retained.\n"
            )
            return "back"
        observed = preview(paths)
        if (
            not isinstance(observed, IntakePreview)
            or observed.processing_performed is not False
            or len(observed.sources) != len(paths)
        ):
            raise LocalPaperFlowError("unqualified local source preview")
        summary = render(observed)
        show_header("Selected Local Files — Read-only Physical Pages")
        output.write("\n" + summary)
        selected: list[tuple[int, int]] = []
        candidates = 0
        unresolved = 0
        for source in observed.sources:
            if source.status != "observed":
                output.write(
                    f"Source {source.source_number}: not observed; "
                    "no physical pages selectable.\n"
                )
                continue
            if len(source.pages) > _MAX_PAGES_PER_SOURCE:
                raise LocalPaperFlowError("local source physical page cap")
            answer = _input(
                input_stream, output,
                f"Source {source.source_number}: choose physical pages 1-"
                f"{len(source.pages)} (comma list, * all, blank skip; B/M/Q): ",
                256,
            )
            navigation = _navigation(answer)
            if navigation is not None:
                return navigation
            pages = _page_choice(answer, count=len(source.pages))
            for page in pages:
                selected.append((source.source_number, page))
                if source.pages[page - 1].status == "candidate_unverified":
                    candidates += 1
                else:
                    unresolved += 1
        if not selected:
            output.write("No pages selected; no custody or dispatch.\n")
            return "back"
        if len(selected) > _MAX_SELECTED or len(set(selected)) != len(selected):
            raise LocalPaperFlowError("selected pages exceed #18 bounds")
        coordinates = tuple(selected)
        show_header("Selected Local Files — Physical Page Selection Review")
        output.write(
            f"\nSelected {len(coordinates)} physical pages from "
            f"{len(paths)} local source(s).\n"
            f"Unverified QR candidates: {candidates}; "
            f"unresolved/other pages: {unresolved}.\n"
            "Selected files stay at their original locations.\n"
            "P. Review processing plan (read-only; NO retention)\n"
        )
        reviewed = False
        while True:
            move = _input(
                input_stream, output,
                "B. Back   M. Main Menu   Q. Quit\nSelection: ", 64,
            )
            navigation = _navigation(move)
            if navigation is not None:
                return navigation
            if move.casefold() == "p":
                try:
                    current = _fresh(
                        paths, observed, preview, root, workspace_guard
                    )
                    from paper_data_suite.returned_paper_teacher_plan import (
                        review_readonly_processing_plan,
                    )

                    summary = review_readonly_processing_plan(
                        root, paths, current, coordinates
                    )
                except (Exception, KeyboardInterrupt):
                    output.write(
                        "Local processing plan refused: selected source or "
                        "active Core workspace changed. No custody.\n"
                    )
                    return "back"
                show_header("Returned Papers — Local Plan Review Only")
                output.write("\n" + summary)
                reviewed = True
                output.write(
                    "R. Request whole-source Core custody (fresh consent)\n"
                )
                continue
            if move.casefold() == "r":
                if not reviewed:
                    output.write(
                        "Review the plan with P before requesting custody. "
                        "No Core write attempted.\n"
                    )
                    continue
                try:
                    current = _fresh(
                        paths, observed, preview, root, workspace_guard
                    )
                    from paper_data_suite.returned_paper_processing_contract import (
                        build_processing_plan,
                    )

                    plan = build_processing_plan(root, paths, current, coordinates)
                except (Exception, KeyboardInterrupt):
                    output.write(
                        "Core custody refused: local source or Core workspace "
                        "changed. No retention requested.\n"
                    )
                    return "back"
                from paper_data_suite.returned_paper_teacher_retention import (
                    run_teacher_first_retention,
                )

                # One and only C2 custody attempt; C2 itself asks RETAIN.
                # Once it returns, never resubmit that plan or auto-retry.
                return run_teacher_first_retention(
                    plan, input_stream=input_stream, output=output,
                    show_header=show_header,
                )
            output.write("Choose P, R, B, M, or Q. No processing occurred.\n")
    except _Closed:
        return "quit"
    except (Exception, KeyboardInterrupt):
        # Never print private paths, original QR contents, decoder errors, or
        # producer exceptions. No first custody call was reached here.
        output.write(
            "Selected local source or workspace unavailable/stale. "
            "No Core custody requested. Return to papers menu.\n"
        )
        return "back"


__all__ = (
    "LocalNavigation", "LocalPaperFlowError", "run_selected_local_paper_processing",
)
