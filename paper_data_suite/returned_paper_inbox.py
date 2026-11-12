"""Bounded, opt-in inventory of Core's scans_inbox; never scan on startup.

The inventory is advisory. Position plus snapshot is *not* a custody token or
permission to retain, dispatch, score, or mutate a producer/workspace.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TextIO

InboxStatus = Literal["eligible", "unsupported", "oversize", "unsafe"]

_MAX_INBOX_ENTRIES: Final[int] = 64
_MAX_SELECTION: Final[int] = 8
_MAX_SOURCE_BYTES: Final[int] = 24 * 1024 * 1024
_ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".pdf", ".png", ".jpg", ".jpeg",
})
_REPARSE_POINT: Final[int] = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class InboxInventoryError(ValueError):
    """Inventory could not be safely enumerated; no files were processed."""


@dataclass(frozen=True, slots=True, repr=False)
class InboxEntry:
    """A transient, opaque-by-default inventory slot with private path data."""

    number: int
    source: Path
    kind: str
    status: InboxStatus
    size_bytes: int


@dataclass(frozen=True, slots=True, repr=False)
class InboxInventory:
    """One bounded snapshot; its hash is an advisory stale-list check."""

    entries: tuple[InboxEntry, ...]
    snapshot: str


def _default_preview(sources: tuple[Path, ...]) -> int:
    from paper_data_suite.returned_paper_preflight import run_readonly_papers_preview

    return run_readonly_papers_preview(sources)


def _core_inbox_dir(workspace_root: Path) -> Path:
    from pds_core.scan_routes import scans_inbox_dir

    return scans_inbox_dir(workspace_root)


def _has_link_component(path: Path) -> bool:
    """Refuse POSIX links and Windows reparse points, including junctions."""
    for component in (path, *path.parents):
        item = component.lstat()
        if stat.S_ISLNK(item.st_mode) or (
            getattr(item, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            return True
    return False


def _safe_directory(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise InboxInventoryError("an absolute workspace without traversal is required")
    try:
        if _has_link_component(path) or not stat.S_ISDIR(path.lstat().st_mode):
            raise InboxInventoryError("unsafe workspace or inbox directory")
    except (OSError, RuntimeError, ValueError) as error:
        raise InboxInventoryError(
            "workspace/inbox is missing or unavailable"
        ) from error


def _entry_status(path: Path, metadata: os.stat_result) -> InboxStatus:
    if not stat.S_ISREG(metadata.st_mode) or (
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    ):
        return "unsafe"
    if path.suffix.casefold() not in _ALLOWED_EXTENSIONS:
        return "unsupported"
    if metadata.st_size > _MAX_SOURCE_BYTES:
        return "oversize"
    return "eligible"


def list_selected_inbox(
    workspace_root: Path,
    *,
    inbox_directory: Callable[[Path], Path] = _core_inbox_dir,
) -> InboxInventory:
    """List one explicitly selected Core inbox with no file-content reads.

    All entries count toward the 64-entry bound, including unsupported and
    unsafe objects. Over-capacity directories fail closed rather than silently
    hiding candidates. No directory is created or globally selected.
    """
    if not isinstance(workspace_root, Path):
        raise InboxInventoryError("explicit workspace Path required")
    _safe_directory(workspace_root)
    try:
        inbox = inbox_directory(workspace_root)
        if not isinstance(inbox, Path) or inbox != workspace_root / "scans_inbox":
            raise InboxInventoryError("unexpected Core inbox location")
        _safe_directory(inbox)
        workspace_stat = workspace_root.lstat()
        inbox_stat = inbox.lstat()
        rows: list[tuple[Path, os.stat_result]] = []
        with os.scandir(inbox) as iterator:
            for item in iterator:
                if len(rows) >= _MAX_INBOX_ENTRIES:
                    raise InboxInventoryError(
                        "inbox exceeds the bounded inventory limit"
                    )
                rows.append((Path(item.path), item.stat(follow_symlinks=False)))
    except InboxInventoryError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise InboxInventoryError("inbox inventory unavailable") from error

    rows.sort(key=lambda row: (row[0].name.casefold(), row[0].name))
    entries: list[InboxEntry] = []
    digest = hashlib.sha256()
    # Bind to the explicit workspace and inbox identities; never print paths.
    for value in (
        os.fspath(workspace_root), os.fspath(inbox),
        str(workspace_stat.st_dev), str(workspace_stat.st_ino),
        str(inbox_stat.st_dev), str(inbox_stat.st_ino),
    ):
        digest.update(value.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
    for number, (path, metadata) in enumerate(rows, 1):
        status = _entry_status(path, metadata)
        kind = path.suffix.casefold().lstrip(".") or "other"
        if kind == "jpeg":
            kind = "jpg"
        if kind not in {"pdf", "png", "jpg"}:
            kind = "other"
        row = "|".join((
            path.name,
            str(metadata.st_dev), str(metadata.st_ino),
            str(metadata.st_mode), str(metadata.st_size),
            str(metadata.st_mtime_ns), status,
        ))
        digest.update(row.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
        entries.append(InboxEntry(number, path, kind, status, metadata.st_size))
    return InboxInventory(tuple(entries), digest.hexdigest())


def render_selected_inbox(inventory: InboxInventory) -> str:
    """No names, paths, raw QR payloads or private metadata in terminal output."""
    lines = [
        "Returned papers - selected Core scans_inbox inventory (read-only)",
        f"Entries: {len(inventory.entries)} (maximum {_MAX_INBOX_ENTRIES})",
    ]
    for row in inventory.entries:
        if row.status == "eligible":
            lines.append(
                f"  Entry {row.number}: {row.kind.upper()}, "
                f"{row.size_bytes} bytes, eligible for preview"
            )
        else:
            lines.append(f"  Entry {row.number}: {row.status}; not selectable")
    lines.extend((
        f"Snapshot: {inventory.snapshot}",
        "To inspect selected entries, repeat with --select N --snapshot DIGEST.",
        "Entry positions may change; a different snapshot requires re-listing.",
        "Snapshot is advisory, NOT proof of custody or processing authorization.",
        "STOP - no scans retained, pages dispatched, results or grades created.",
    ))
    return "\n".join(lines) + "\n"


def run_selected_inbox(
    workspace_root: Path,
    *,
    selected: tuple[int, ...] = (),
    snapshot: str | None = None,
    list_inbox: Callable[[Path], InboxInventory] = list_selected_inbox,
    preview: Callable[[tuple[Path, ...]], int] = _default_preview,
    output: TextIO | None = None,
    errors: TextIO | None = None,
) -> int:
    """Render one inventory, or deliberately preview snapshot-bound entries."""
    out = sys.stdout if output is None else output
    err = sys.stderr if errors is None else errors
    try:
        if type(selected) is not tuple or len(selected) > _MAX_SELECTION or any(
            type(index) is not int or index < 1 for index in selected
        ):
            raise InboxInventoryError("invalid selection")
        if len(set(selected)) != len(selected):
            raise InboxInventoryError("duplicate selection")
        if selected:
            if (
                not isinstance(snapshot, str) or len(snapshot) != 64
                or any(ch not in "0123456789abcdef" for ch in snapshot)
            ):
                raise InboxInventoryError("selection needs the listed snapshot")
        elif snapshot is not None:
            raise InboxInventoryError("a snapshot without selection is invalid")
        inventory = list_inbox(workspace_root)
        if not selected:
            out.write(render_selected_inbox(inventory))
            return 0
        if snapshot != inventory.snapshot:
            raise InboxInventoryError("inbox changed; re-list before selecting")
        if any(index > len(inventory.entries) for index in selected):
            raise InboxInventoryError("unknown position")
        selected_rows = tuple(inventory.entries[index - 1] for index in selected)
        if any(row.status != "eligible" for row in selected_rows):
            raise InboxInventoryError("unsafe or unsupported selection")
        out.write(f"Selected {len(selected_rows)} inbox entry/entries for preview.\n")
        return preview(tuple(row.source for row in selected_rows))
    except (Exception, KeyboardInterrupt):
        # Deliberately avoid echoing potentially sensitive path/entry names.
        err.write(
            "Selected inbox unavailable or selection stale/invalid; "
            "no processing performed.\n"
        )
        return 1


__all__ = [
    "InboxEntry", "InboxInventory", "InboxInventoryError", "list_selected_inbox",
    "render_selected_inbox", "run_selected_inbox",
]
