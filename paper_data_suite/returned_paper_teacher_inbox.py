"""#19B2: explicit Core inbox choice and physical-page review, read-only.

A position/snapshot and selected physical page number are *advisory only*.
They are never an authorization, a Core custody record, or a dispatch plan.
Core #17 owns inventory and preflight; this module only collects choices.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from paper_data_suite.returned_paper_inbox import (
    InboxInventory,
    list_selected_inbox,
    render_selected_inbox,
)
from paper_data_suite.returned_paper_preflight import (
    build_readonly_preflight,
    render_readonly_preflight,
)
from paper_data_suite.returned_paper_preview_contract import IntakePreview

InboxNavigation = Literal["back", "home", "quit"]
_MAX_INPUT = 4096
_MAX_SELECTION_INPUT = 256
_MAX_SOURCES = 8
_MAX_PAGES = 512
_MAX_PER_SOURCE = 64


class _Closed(Exception):
    """Input interrupted/EOF; never infer teacher approval."""


class _Invalid(Exception):
    """Invalid input or an unavailable/stale read-only observation."""


@dataclass(frozen=True, slots=True, repr=False)
class ReadonlyPhysicalSelectionV1:
    """Transient physical positions only; NEVER a processing/custody token."""

    inbox_snapshot: str
    selected_entries: tuple[int, ...]
    physical_pages: tuple[tuple[int, int], ...]
    contract_version: Literal["1"] = "1"
    processing_performed: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            type(self.inbox_snapshot) is not str
            or len(self.inbox_snapshot) != 64
            or any(char not in "0123456789abcdef" for char in self.inbox_snapshot)
            or type(self.selected_entries) is not tuple
            or not 1 <= len(self.selected_entries) <= _MAX_SOURCES
            or any(type(item) is not int or not 1 <= item <= 64
                   for item in self.selected_entries)
            or len(set(self.selected_entries)) != len(self.selected_entries)
            or type(self.physical_pages) is not tuple
            or not 1 <= len(self.physical_pages) <= _MAX_PAGES
            or any(
                type(pair) is not tuple or len(pair) != 2
                or type(pair[0]) is not int or type(pair[1]) is not int
                or not 1 <= pair[0] <= len(self.selected_entries)
                or not 1 <= pair[1] <= _MAX_PER_SOURCE
                for pair in self.physical_pages
            )
            or len(set(self.physical_pages)) != len(self.physical_pages)
            or self.contract_version != "1"
            or self.processing_performed is not False
        ):
            raise ValueError("invalid/non-read-only physical page selection")


def _input(stream: TextIO, output: TextIO, prompt: str, limit: int) -> str:
    output.write(prompt)
    output.flush()
    try:
        raw = stream.readline(limit + 2)
    except (EOFError, KeyboardInterrupt, OSError, UnicodeError) as exc:
        raise _Closed from exc
    if not raw:
        raise _Closed
    if (
        len(raw) > limit + 1
        or (len(raw) > limit and not raw.endswith("\n"))
        or any(ord(char) < 32 and char not in "\r\n" for char in raw)
    ):
        raise _Invalid
    return raw.rstrip("\r\n").strip()


def _navigation(text: str) -> InboxNavigation | None:
    lowered = text.casefold()
    if lowered == "b":
        return "back"
    if lowered == "m":
        return "home"
    if lowered == "q":
        return "quit"
    return None


def _numbers(text: str, *, maximum: int, limit: int) -> tuple[int, ...]:
    parts = text.split(",")
    if (
        not text or len(parts) > limit or any(
            not part.strip().isascii()
            or not part.strip().isdecimal()
            or not 1 <= int(part.strip()) <= maximum
            for part in parts
        )
    ):
        raise _Invalid
    values = tuple(int(part.strip()) for part in parts)
    if len(values) != len(set(values)):
        raise _Invalid
    return values


def _workspace(text: str) -> Path:
    if (
        not text or "*" in text or "?" in text
        or any(ord(char) < 32 or ord(char) == 127 for char in text)
    ):
        raise _Invalid
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts:
        raise _Invalid
    return path


def _page_choice(text: str, *, count: int) -> tuple[int, ...]:
    if count < 1 or count > _MAX_PER_SOURCE:
        raise _Invalid
    if not text:
        return ()
    if text == "*":
        return tuple(range(1, count + 1))
    return _numbers(text, maximum=count, limit=_MAX_PER_SOURCE)


def run_readonly_teacher_inbox(
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    list_inbox: Callable[[Path], InboxInventory] = list_selected_inbox,
    preview: Callable[[tuple[Path, ...]], IntakePreview] = build_readonly_preflight,
    render: Callable[[IntakePreview], str] = render_readonly_preflight,
) -> InboxNavigation:
    """Return back to item 9, home, or quit; never process selected pages.

    Fresh #17 snapshot checked BEFORE preview. Physical-page choices are
    validated against that exact transient preview but are not persisted.
    """
    if not all(callable(value) for value in (show_header, list_inbox, preview, render)):
        raise ValueError("read-only inbox callbacks are required")
    show_header("Process Returned Papers — Core Inbox")
    output.write(
        "\nRead-only Core scans_inbox selection; no custody or dispatch.\n"
        "Enter one absolute workspace directory, not the scans_inbox path.\n"
        "B. Back   M. Main Menu   Q. Quit\n"
    )
    try:
        raw_root = _input(
            input_stream, output, "Workspace directory (B/M/Q): ", _MAX_INPUT
        )
        navigation = _navigation(raw_root)
        if navigation:
            return navigation
        root = _workspace(raw_root)
        original = list_inbox(root)
        if not isinstance(original, InboxInventory) or len(original.entries) > 64:
            raise _Invalid
        output.write("\n" + render_selected_inbox(original))
        if not original.entries:
            output.write("Inbox is empty. No files inspected.\n")
            return "back"
        text = _input(
            input_stream, output,
            "Select eligible entry numbers (comma-separated, max 8; B/M/Q): ",
            _MAX_SELECTION_INPUT,
        )
        navigation = _navigation(text)
        if navigation:
            return navigation
        selected = _numbers(
            text, maximum=len(original.entries), limit=_MAX_SOURCES
        )
        # #17 inventory does not read file contents. Re-list on *selection*,
        # never reuse an old advisory number as an authorization/custody token.
        current = list_inbox(root)
        if not isinstance(current, InboxInventory):
            raise _Invalid
        if current.snapshot != original.snapshot or len(current.entries) != len(
            original.entries
        ):
            raise _Invalid
        chosen = tuple(current.entries[index - 1] for index in selected)
        if any(row.status != "eligible" for row in chosen):
            raise _Invalid
        paths = tuple(row.source for row in chosen)
        if len(set(os.path.normcase(os.fspath(p)) for p in paths)) != len(paths):
            raise _Invalid
        observed = preview(paths)
        if (
            not isinstance(observed, IntakePreview)
            or observed.processing_performed is not False
            or len(observed.sources) != len(paths)
        ):
            raise _Invalid
        # The existing #17 renderer is responsible for redaction, status
        # vocabulary, bounded physical-page display and routing disclaimers.
        summary = render(observed)
        show_header("Core Inbox — Read-only Page Preview")
        output.write("\n" + summary)
        physical: list[tuple[int, int]] = []
        candidates = 0
        unresolved = 0
        for source in observed.sources:
            if source.status != "observed":
                output.write(
                    f"Source {source.source_number}: not observed; "
                    "no physical pages selectable.\n"
                )
                continue
            if len(source.pages) > _MAX_PER_SOURCE:
                raise _Invalid
            raw = _input(
                input_stream, output,
                f"Source {source.source_number}: choose pages 1-"
                f"{len(source.pages)} (comma list, * all, blank skip; B/M/Q): ",
                _MAX_SELECTION_INPUT,
            )
            navigation = _navigation(raw)
            if navigation:
                return navigation
            pages = _page_choice(raw, count=len(source.pages))
            for page in pages:
                physical.append((source.source_number, page))
                if source.pages[page - 1].status == "candidate_unverified":
                    candidates += 1
                else:
                    unresolved += 1
        if not physical:
            output.write(
                "No physical pages selected. No retention or dispatch.\n"
            )
            return "back"
        selection = ReadonlyPhysicalSelectionV1(
            inbox_snapshot=current.snapshot,
            selected_entries=selected,
            physical_pages=tuple(physical),
        )
        show_header("Core Inbox — Physical Page Selection Review")
        output.write(
            f"\nSelected {len(selection.physical_pages)} physical pages from "
            f"{len(selected)} selected inbox entries.\n"
            f"Unverified QR candidates: {candidates}; "
            f"unresolved/other pages: {unresolved}.\n"
            "Selection is advisory only: no Core custody, handler invocation, "
            "scoring, student records, or grades.\n"
            "No processing plan or authorization was created.\n"
        )
        output.write(
            "P. Review processing plan (read-only; NO retention)\n"
        )
        while True:
            move = _input(
                input_stream, output,
                "B. Back   M. Main Menu   Q. Quit\nSelection: ", 64,
            )
            navigation = _navigation(move)
            if navigation:
                return navigation
            if move.casefold() == "p":
                try:
                    # The B2 snapshot was advisory, not a custody token.
                    # Recheck it and the preview on EACH review request.
                    latest = list_inbox(root)
                    if (
                        not isinstance(latest, InboxInventory)
                        or latest.snapshot != current.snapshot
                        or len(latest.entries) != len(current.entries)
                        or tuple(latest.entries[i - 1].source
                                 for i in selected) != paths
                    ):
                        raise _Invalid
                    fresh = preview(paths)
                    if (
                        not isinstance(fresh, IntakePreview)
                        or fresh != observed
                        or fresh.processing_performed is not False
                    ):
                        raise _Invalid
                    from paper_data_suite.returned_paper_teacher_plan import (
                        review_readonly_processing_plan,
                    )

                    summary = review_readonly_processing_plan(
                        root, paths, fresh, selection.physical_pages
                    )
                except (Exception, KeyboardInterrupt):
                    output.write(
                        "Processing plan preview refused: inbox or source "
                        "changed/unavailable. No custody or dispatch.\n"
                    )
                    return "back"
                show_header("Returned Papers - Plan Review Only")
                output.write("\n" + summary)
                continue
            output.write(
                "Choose P, B, M, or Q. No processing occurred.\n"
            )
    except _Closed:
        return "quit"
    except (Exception, KeyboardInterrupt):
        # Never print the exception, selected path or raw QR to the terminal.
        output.write(
            "Inbox selection or page review unavailable/stale; "
            "no processing performed. Return to the preview menu.\n"
        )
        return "back"


__all__ = ("ReadonlyPhysicalSelectionV1", "run_readonly_teacher_inbox")
