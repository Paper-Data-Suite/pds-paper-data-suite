"""#19B1: explicit read-only file preview for the Suite Teacher Home.

This controller is imported only after the teacher selects Home item 9.
It never creates a Core scan, builds a processing plan, launches producers,
or supplies a qualified_modules argument. The #17 preflight owns observation.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from paper_data_suite.returned_paper_preflight import (
    build_readonly_preflight,
    render_readonly_preflight,
)
from paper_data_suite.returned_paper_preview_contract import IntakePreview

_MAX_FILES = 8
_MAX_INPUT_CHARS = 4096
_ALLOWED_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg"})


class _InputClosed(Exception):
    """Terminal EOF/interrupt; do not continue a partially selected task."""


def _read_line(stream: TextIO, *, limit: int) -> str:
    """Read one bounded line without echoing user-supplied paths."""
    try:
        value = stream.readline(limit + 2)
    except (EOFError, KeyboardInterrupt, OSError, UnicodeError) as error:
        raise _InputClosed from error
    if not value:
        raise _InputClosed
    if len(value) > limit + 1 or (len(value) > limit and not value.endswith("\n")):
        raise ValueError("input exceeds the bounded length")
    return value.rstrip("\r\n")


def _menu_choice(input_stream: TextIO, output: TextIO) -> str:
    output.write("Selection: ")
    output.flush()
    return _read_line(input_stream, limit=64).strip().casefold()


def _selected_paths(
    input_stream: TextIO,
    output: TextIO,
) -> tuple[Path, ...] | None:
    """Collect only precisely chosen absolute files; no enumeration or reads."""
    output.write("Number of files to preview (1-8; blank cancels): ")
    output.flush()
    count_text = _read_line(input_stream, limit=8)
    if count_text == "":
        return None
    if (
        not count_text.isascii()
        or not count_text.isdecimal()
        or not 1 <= int(count_text) <= _MAX_FILES
    ):
        raise ValueError("choose a source count between 1 and 8")

    chosen: list[Path] = []
    observed: set[str] = set()
    for number in range(1, int(count_text) + 1):
        output.write(f"Absolute filename for source {number} (blank cancels): ")
        output.flush()
        raw = _read_line(input_stream, limit=_MAX_INPUT_CHARS)
        if not raw:
            return None
        # No wildcard expansion, relative CWD fallback, shell or private path echo.
        if (
            any(ord(char) < 32 or ord(char) == 127 for char in raw)
            or "*" in raw or "?" in raw
        ):
            raise ValueError("source path contains an unsupported character")
        path = Path(raw)
        if not path.is_absolute() or path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            raise ValueError("an absolute PDF, PNG or JPEG filename is required")
        key = os.path.normcase(os.fspath(path))
        if key in observed:
            raise ValueError("the same source cannot be selected twice")
        observed.add(key)
        chosen.append(path)
    return tuple(chosen)


def _after_preview(
    *, input_stream: TextIO, output: TextIO,
    show_header: Callable[[str], None],
) -> bool:
    """Return True only to quit the entire Suite shell."""
    while True:
        output.write("\nB. Back   M. Main Menu   Q. Quit\n")
        choice = _menu_choice(input_stream, output)
        if choice in {"b", "m"}:
            return False
        if choice == "q":
            return True
        show_header("Read-only Papers Preview")
        output.write("Choose B, M or Q. No scans were retained or dispatched.\n")


def run_readonly_teacher_papers(
    *,
    input_stream: TextIO,
    output: TextIO,
    show_header: Callable[[str], None],
    preview: Callable[[tuple[Path, ...]], IntakePreview] = build_readonly_preflight,
    render: Callable[[IntakePreview], str] = render_readonly_preflight,
) -> bool:
    """Explicit opt-in preview; True means quit, False means return to Home.

    The injected preview/render callbacks are test seams, not execution paths.
    Any file failure is reported by safe category without showing private paths.
    """
    if not callable(show_header) or not callable(preview) or not callable(render):
        raise ValueError("teacher paper preview needs valid read-only callbacks")
    while True:
        show_header("Process Returned Papers — Preview")
        output.write(
            "\nOpening this menu is read-only; no source is processed.\n"
            "1. Preview explicitly selected local files (read-only)\n"
            "2. Select Core inbox entries and physical pages (initially read-only)\n"
            "Core inbox processing requires separate RETAIN and DISPATCH consents.\n"
            "Unqualified producers remain preview-only; no automatic dispatch.\n"
            "\nH. Help   B. Back   M. Main Menu   Q. Quit\n"
        )
        try:
            choice = _menu_choice(input_stream, output)
            if choice == "q":
                return True
            if choice in {"b", "m"}:
                return False
            if choice == "h":
                output.write(
                    "Choose 1 to type 1-8 absolute PDF, PNG, or JPEG filenames.\n"
                    "Choose 2 to review selected Core inbox physical pages.\n"
                    "Any retention or eligible dispatch needs fresh separate consent.\n"
                    "Individual local-file previews never process those files.\n"
                    "A file path is data, not a command. Blank cancels selection.\n"
                    "No route, score, grade or Core custody is authorized.\n"
                )
                continue
            if choice == "2":
                from paper_data_suite.returned_paper_teacher_inbox import (
                    run_readonly_teacher_inbox,
                )

                navigation = run_readonly_teacher_inbox(
                    input_stream=input_stream, output=output,
                    show_header=show_header,
                )
                if navigation == "quit":
                    return True
                if navigation == "home":
                    return False
                continue
            if choice != "1":
                output.write("Choose 1, 2, H, B, M, or Q.\n")
                continue
            paths = _selected_paths(input_stream, output)
            if paths is None:
                output.write("Preview selection cancelled; no files were read.\n")
                continue
            try:
                observed = preview(paths)
                result = render(observed)
            except (Exception, KeyboardInterrupt):
                output.write(
                    "Read-only preview was unavailable; check selected files "
                    "and optional scanner dependencies. No files were processed.\n"
                )
                continue
            show_header("Read-only Papers Preview")
            output.write("\n" + result)
            output.write(
                "No Core source retention, producer dispatch, grading, "
                "or student-record write was requested.\n"
            )
            return _after_preview(
                input_stream=input_stream, output=output, show_header=show_header,
            )
        except _InputClosed:
            # EOF/interrupt is never approval or a request to resume processing.
            return True
        except ValueError:
            output.write(
                "Invalid or duplicate source selection. "
                "No file paths were displayed or processed.\n"
            )


__all__ = ("run_readonly_teacher_papers",)
