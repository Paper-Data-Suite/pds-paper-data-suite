"""Issue #17: selected Core inbox enumeration is bounded and read-only."""

from __future__ import annotations

import builtins
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_inbox import (
    InboxInventoryError,
    list_selected_inbox,
    render_selected_inbox,
    run_selected_inbox,
)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "scans_inbox").mkdir(parents=True)
    return root


def _inventory(root: Path):
    return list_selected_inbox(
        root,
        inbox_directory=lambda selected: selected / "scans_inbox",
    )


def test_empty_inbox_is_a_nonwriting_snapshot(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    view = _inventory(workspace)
    assert view.entries == ()
    assert len(view.snapshot) == 64
    assert "Entries: 0" in render_selected_inbox(view)
    assert not list((workspace / "scans_inbox").iterdir())


def test_inventory_is_ordered_opaque_and_never_opens_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    folder = workspace / "scans_inbox"
    (folder / "z_student_private.png").write_bytes(b"not really png")
    (folder / "B_private.PDF").write_bytes(b"%PDF-1.7")
    (folder / "notes.txt").write_bytes(b"sensitive student information")
    original_open = builtins.open

    def blocked_open(*args: object, **kwargs: object) -> object:
        raise AssertionError("no file content access during inventory")

    monkeypatch.setattr(builtins, "open", blocked_open)
    before = sorted((f.name, f.stat().st_mtime_ns) for f in folder.iterdir())
    view = _inventory(workspace)
    monkeypatch.setattr(builtins, "open", original_open)
    assert [r.status for r in view.entries] == [
        "eligible", "unsupported", "eligible",
    ]
    assert [r.kind for r in view.entries] == ["pdf", "other", "png"]
    report = render_selected_inbox(view)
    assert "student_private" not in report
    assert "B_private" not in report
    assert "notes.txt" not in report
    assert str(folder) not in report
    assert sorted((f.name, f.stat().st_mtime_ns) for f in folder.iterdir()) == before


def test_selected_positions_require_snapshot_and_recheck_it(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    folder = root / "scans_inbox"
    (folder / "a.pdf").write_bytes(b"%PDF-1.4")
    (folder / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    old = _inventory(root)
    calls: list[tuple[Path, ...]] = []

    def preview(paths: tuple[Path, ...]) -> int:
        calls.append(paths)
        return 0

    assert run_selected_inbox(
        root, selected=(2, 1), snapshot=old.snapshot,
        list_inbox=_inventory, preview=preview,
    ) == 0
    assert [p.name for p in calls[0]] == ["b.png", "a.pdf"]
    calls.clear()
    (folder / "000_new.pdf").write_bytes(b"new")
    assert run_selected_inbox(
        root, selected=(2,), snapshot=old.snapshot,
        list_inbox=_inventory, preview=preview,
    ) == 1
    assert calls == []


@pytest.mark.parametrize("selected,snapshot", [
    ((1,), None), ((1, 1), "a" * 64), ((0,), "a" * 64),
    ((-1,), "a" * 64), ((1,) * 9, "a" * 64),
    ((), "a" * 64), ((True,), "a" * 64),
    ((1,), "x" * 64),
])
def test_invalid_selections_never_call_preview(
    tmp_path: Path, selected: tuple[int, ...], snapshot: str | None,
) -> None:
    root = _workspace(tmp_path)

    def forbidden(_: tuple[Path, ...]) -> int:
        raise AssertionError("unexpected processing")

    assert run_selected_inbox(
        root, selected=selected, snapshot=snapshot,
        list_inbox=_inventory, preview=forbidden,
    ) == 1


def test_unsupported_and_oversize_entries_cannot_be_selected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    folder = root / "scans_inbox"
    (folder / "a.txt").write_bytes(b"private")
    oversized = folder / "b.pdf"
    with oversized.open("wb") as output:
        output.truncate(24 * 1024 * 1024 + 1)
    listing = _inventory(root)
    assert [row.status for row in listing.entries] == ["unsupported", "oversize"]
    for position in (1, 2):
        assert run_selected_inbox(
            root, selected=(position,), snapshot=listing.snapshot,
            list_inbox=_inventory,
            preview=lambda _: pytest.fail("cannot preview rejected entry"),
        ) == 1


def test_linked_files_and_linked_inbox_are_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = tmp_path / "other.pdf"
    source.write_bytes(b"%PDF-1.4")
    link = root / "scans_inbox" / "linked.pdf"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")
    listing = _inventory(root)
    assert listing.entries[0].status == "unsafe"
    (root / "scans_inbox").rename(root / "actual")
    try:
        (root / "scans_inbox").symlink_to(root / "actual", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink privilege unavailable")
    with pytest.raises(InboxInventoryError):
        _inventory(root)


def test_traversal_and_missing_inbox_are_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(InboxInventoryError):
        _inventory(root / ".." / "workspace")
    (root / "scans_inbox").rmdir()
    with pytest.raises(InboxInventoryError):
        _inventory(root)


def test_overfull_inbox_fails_closed_without_truncating(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    for i in range(65):
        (root / "scans_inbox" / f"{i:04d}.png").write_bytes(b"x")
    with pytest.raises(InboxInventoryError, match="bounded"):
        _inventory(root)


def test_content_metadata_change_invalidates_snapshot(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    path = root / "scans_inbox" / "one.pdf"
    path.write_bytes(b"before")
    first = _inventory(root)
    path.write_bytes(b"later with different length")
    second = _inventory(root)
    assert first.snapshot != second.snapshot


def test_core_path_contract_is_used_and_checked(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(InboxInventoryError, match="Core inbox"):
        list_selected_inbox(
            root, inbox_directory=lambda path: path / "elsewhere",
        )


def test_listing_never_invokes_preview_or_core_provider(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    report = StringIO()

    def forbidden(_: tuple[Path, ...]) -> int:
        raise AssertionError("preview may only run on explicit selections")

    assert run_selected_inbox(
        root, list_inbox=_inventory, preview=forbidden, output=report,
    ) == 0
    assert "STOP - no scans retained" in report.getvalue()


def test_cli_nested_inbox_parses_without_dropping_existing_preview() -> None:
    from paper_data_suite import cli

    parser = cli.build_parser()
    listing = parser.parse_args(("papers", "inbox", "--workspace", "/tmp/pds"))
    assert listing.command == "papers"
    assert listing.papers_command == "inbox"
    assert listing.workspace == Path("/tmp/pds")
    assert listing.select is None
    assert listing.snapshot is None
    selected = parser.parse_args((
        "papers", "inbox", "--workspace", "/tmp/pds",
        "--select", "2", "--select", "1", "--snapshot", "a" * 64,
    ))
    assert selected.select == [2, 1]
    unchanged = parser.parse_args(("papers", "preview", "--source", "one.png"))
    assert unchanged.source == [Path("one.png")]
    assert parser.parse_args(()).command is None


def test_cli_inbox_delegates_only_on_explicit_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import cli
    from paper_data_suite import returned_paper_inbox as module

    captured: list[tuple[Path, tuple[int, ...], str | None]] = []

    def delegate(
        workspace_root: Path, *, selected: tuple[int, ...], snapshot: str | None,
    ) -> int:
        captured.append((workspace_root, selected, snapshot))
        return 0

    monkeypatch.setattr(module, "run_selected_inbox", delegate)
    assert cli.main((
        "papers", "inbox", "--workspace", "/tmp/test",
        "--select", "1", "--snapshot", "b" * 64,
    )) == 0
    assert captured == [(Path("/tmp/test"), (1,), "b" * 64)]
