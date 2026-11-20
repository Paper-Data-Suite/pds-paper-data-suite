"""#19B2: read-only Core inbox selection and physical-page review."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from io import StringIO
from pathlib import Path
from typing import Callable

import pytest

from paper_data_suite.returned_paper_inbox import InboxEntry, InboxInventory
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_teacher_inbox import (
    ReadonlyPhysicalSelectionV1,
    run_readonly_teacher_inbox,
)

_SNAPSHOT = "a" * 64


def _inventory(base: Path, *, changed: bool = False) -> InboxInventory:
    return InboxInventory((
        InboxEntry(
            1, base / "scans_inbox" / "STUDENT_SECRET.pdf", "pdf", "eligible", 42
        ),
        InboxEntry(2, base / "scans_inbox" / "another.jpg", "jpg", "eligible", 54),
        InboxEntry(3, base / "scans_inbox" / "secrets.txt", "other", "unsupported", 3),
    ), "b" * 64 if changed else _SNAPSHOT)


def _preview(paths: tuple[Path, ...]) -> IntakePreview:
    return IntakePreview(tuple(SourcePreview(
        source_number=index, status="observed", pages=(
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "missing_qr"),
            PagePreview(3, "candidate_unverified", "quillan"),
        ),
    ) for index, _ in enumerate(paths, start=1)), ())


def _drive(
    data: str, root: Path, *,
    inbox: Callable[[Path], InboxInventory] | None = None,
    preview: Callable[[tuple[Path, ...]], IntakePreview] = _preview,
    render: Callable[[IntakePreview], str] = lambda _: "SAFE PAGE REVIEW\n",
) -> tuple[str, str, list[Path], list[tuple[Path, ...]]]:
    listed: list[Path] = []
    previewed: list[tuple[Path, ...]] = []
    output = StringIO()

    def list_it(path: Path) -> InboxInventory:
        listed.append(path)
        return inbox(path) if inbox is not None else _inventory(root)

    def observe(paths: tuple[Path, ...]) -> IntakePreview:
        previewed.append(paths)
        return preview(paths)

    result = run_readonly_teacher_inbox(
        input_stream=StringIO(data), output=output,
        show_header=lambda label: output.write(f"SCREEN {label}\n"),
        list_inbox=list_it, preview=observe, render=render,
    )
    return result, output.getvalue(), listed, previewed


@pytest.mark.parametrize("choice,result", [
    ("b\n", "back"), ("m\n", "home"), ("q\n", "quit"), ("", "quit"),
])
def test_initial_navigation_does_not_enumerate_inbox(
    tmp_path: Path, choice: str, result: str,
) -> None:
    status, output, listed, previewed = _drive(choice, tmp_path)
    assert status == result
    assert not listed and not previewed
    assert "read-only" in output.lower()


@pytest.mark.parametrize("bad", [
    "relative/path", "../root", "a?b", "x*", "/tmp/../private",
    "", "\x00bad",
])
def test_invalid_workspace_never_lists_or_previews(
    tmp_path: Path, bad: str,
) -> None:
    result, output, listed, previewed = _drive(bad + "\n", tmp_path)
    assert result == "back" and not previewed and not listed
    assert "no processing" in output.lower()


def test_inbox_empty_does_not_preview(tmp_path: Path) -> None:
    result, output, listed, previews = _drive(
        f"{tmp_path}\n", tmp_path,
        inbox=lambda _: InboxInventory((), _SNAPSHOT),
    )
    assert result == "back" and len(listed) == 1 and not previews
    assert "Inbox is empty" in output


def test_inbox_inventory_exception_has_no_private_path_echo(
    tmp_path: Path,
) -> None:
    def fail(_: Path) -> InboxInventory:
        raise RuntimeError("PRIVATE_STUDENT_PATH")

    result, output, listed, previews = _drive(
        f"{tmp_path}\n", tmp_path, inbox=fail,
    )
    assert result == "back" and len(listed) == 1 and not previews
    assert "PRIVATE_STUDENT_PATH" not in output


@pytest.mark.parametrize("choice,nav", [
    ("b\n", "back"), ("m\n", "home"), ("q\n", "quit"),
])
def test_inbox_selection_navigation_never_previews(
    tmp_path: Path, choice: str, nav: str,
) -> None:
    result, _, listed, previews = _drive(
        f"{tmp_path}\n{choice}", tmp_path,
    )
    assert result == nav and len(listed) == 1 and not previews


@pytest.mark.parametrize("choice", [
    "1,1", "0", "4", "1,3", "1,2,3,4,5,6,7,8,9", "-1", "1;2", "*",
    "999999", "1,,2", "xyz", "", "1.0",
])
def test_invalid_or_ineligible_entry_selection_fails_closed(
    tmp_path: Path, choice: str,
) -> None:
    result, output, listed, previews = _drive(
        f"{tmp_path}\n{choice}\n", tmp_path,
    )
    assert result == "back" and len(listed) >= 1 and not previews
    assert "STUDENT_SECRET" not in output


def test_stale_snapshot_blocks_preview(tmp_path: Path) -> None:
    times = 0

    def changed(_: Path) -> InboxInventory:
        nonlocal times
        times += 1
        return _inventory(tmp_path, changed=times >= 2)

    status, output, calls, previewed = _drive(
        f"{tmp_path}\n1\n", tmp_path, inbox=changed,
    )
    assert status == "back" and times == 2
    assert len(calls) == 2 and not previewed
    assert "stale" in output


def test_preview_preserves_selected_inbox_position_order(
    tmp_path: Path,
) -> None:
    result, output, listed, previewed = _drive(
        f"{tmp_path}\n2,1\n*\n1,3\nb\n", tmp_path,
    )
    assert result == "back" and listed == [tmp_path, tmp_path]
    assert previewed == [(
        tmp_path / "scans_inbox" / "another.jpg",
        tmp_path / "scans_inbox" / "STUDENT_SECRET.pdf",
    )]
    assert "Selected 5 physical pages" in output
    assert "Unverified QR candidates: 4" in output
    assert "unresolved/other pages: 1" in output
    assert "STUDENT_SECRET" not in output
    assert str(tmp_path) not in output
    assert "no Core custody" in output


def test_physical_page_choice_is_not_a_processing_decision(
    tmp_path: Path,
) -> None:
    status, text, _, previewed = _drive(
        f"{tmp_path}\n1\n1,2\nm\n", tmp_path,
    )
    assert status == "home" and len(previewed) == 1
    assert "Selected 2 physical pages" in text
    assert "No processing plan or authorization" in text


@pytest.mark.parametrize("invalid", [
    "0", "4", "1,1", "3;1", "1,,2", "33", "1..3", "all", "2,3,4",
])
def test_invalid_physical_page_choice_stops_without_page_review(
    tmp_path: Path, invalid: str,
) -> None:
    status, output, _, previews = _drive(
        f"{tmp_path}\n1\n{invalid}\n", tmp_path,
    )
    assert status == "back" and len(previews) == 1
    assert "Physical Page Selection Review" not in output
    assert "no processing performed" in output


def test_blank_page_selection_does_not_claim_pages(tmp_path: Path) -> None:
    status, text, _, previewed = _drive(
        f"{tmp_path}\n1,2\n\n\n", tmp_path,
    )
    assert status == "back" and len(previewed) == 1
    assert "No physical pages selected" in text


def test_eof_after_preview_does_not_authorize_or_replay(tmp_path: Path) -> None:
    status, output, _, previewed = _drive(
        f"{tmp_path}\n1\n1\n", tmp_path,
    )
    assert status == "quit" and len(previewed) == 1
    assert "No processing plan or authorization" in output


def test_preview_exception_is_redacted(tmp_path: Path) -> None:
    def private(_: tuple[Path, ...]) -> IntakePreview:
        raise OSError("PRIVATE_NAME.pdf")

    status, output, _, previewed = _drive(
        f"{tmp_path}\n1\n", tmp_path, preview=private,
    )
    assert status == "back" and len(previewed) == 1
    assert "PRIVATE_NAME" not in output


def test_preview_incomplete_source_not_page_selectable(tmp_path: Path) -> None:
    def incomplete(_: tuple[Path, ...]) -> IntakePreview:
        return IntakePreview((SourcePreview(1, "source_unavailable"),), ())

    status, output, _, previewed = _drive(
        f"{tmp_path}\n1\n", tmp_path, preview=incomplete,
    )
    assert status == "back" and len(previewed) == 1
    assert "no physical pages selectable" in output


def test_invalid_preview_count_refused(tmp_path: Path) -> None:
    status, output, _, previewed = _drive(
        f"{tmp_path}\n1,2\n", tmp_path,
        preview=lambda _: IntakePreview((SourcePreview(1, "source_unavailable"),), ()),
    )
    assert status == "back" and len(previewed) == 1
    assert "unavailable/stale" in output


def test_no_stale_reuse_of_first_preview_after_relisting(tmp_path: Path) -> None:
    def fake(_: Path) -> InboxInventory:
        return _inventory(tmp_path)

    status, _, calls, previewed = _drive(
        f"{tmp_path}\n1\n1\nb\n", tmp_path, inbox=fake,
    )
    assert status == "back"
    assert len(calls) == 2 and len(previewed) == 1


def test_select_input_limit_rejects_long_response(tmp_path: Path) -> None:
    status, output, _, previews = _drive(
        f"{tmp_path}\n" + "1" * 270 + "\n", tmp_path,
    )
    assert status == "back" and not previews
    assert "no processing" in output


def test_immutable_advisory_positions_cannot_claim_processing() -> None:
    obj = ReadonlyPhysicalSelectionV1(_SNAPSHOT, (2, 1), ((1, 1), (2, 2)))
    assert obj.processing_performed is False
    with pytest.raises(ValueError):
        replace(obj, processing_performed=True)  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        obj.physical_pages = ()  # type: ignore[misc]


@pytest.mark.parametrize("entries,pages", [
    ((1, 1), ((1, 1),)), ((1,), ((1, 0),)), ((1,), ((1, 65),)),
    ((1,), ((2, 1),)), ((1,), ((1, 1), (1, 1))),
    ((1,), ()),
])
def test_advisory_contract_rejects_invalid_positions(
    entries: tuple[int, ...], pages: tuple[tuple[int, int], ...],
) -> None:
    with pytest.raises(ValueError):
        ReadonlyPhysicalSelectionV1(_SNAPSHOT, entries, pages)


def test_navigation_from_parent_preview_is_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_inbox as inbox_ui
    from paper_data_suite.returned_paper_teacher_preview import (
        run_readonly_teacher_papers,
    )

    visited: list[str] = []

    def injected(**_: object) -> str:
        visited.append("inbox")
        return "back"

    monkeypatch.setattr(inbox_ui, "run_readonly_teacher_inbox", injected)
    screen = StringIO()
    result = run_readonly_teacher_papers(
        input_stream=StringIO("2\nb\n"), output=screen,
        show_header=lambda title: screen.write(title + "\n"),
    )
    assert result is False and visited == ["inbox"]
    assert "Core inbox" in screen.getvalue()


@pytest.mark.parametrize("navigation,quits", [
    ("home", False), ("quit", True),
])
def test_home_and_quit_from_inbox_propagate_to_shell(
    monkeypatch: pytest.MonkeyPatch, navigation: str, quits: bool,
) -> None:
    from paper_data_suite import returned_paper_teacher_inbox as inbox_ui
    from paper_data_suite.returned_paper_teacher_preview import (
        run_readonly_teacher_papers,
    )

    monkeypatch.setattr(
        inbox_ui, "run_readonly_teacher_inbox", lambda **_: navigation
    )
    screen = StringIO()
    result = run_readonly_teacher_papers(
        input_stream=StringIO("2\n"), output=screen,
        show_header=lambda title: screen.write(title + "\n"),
    )
    assert result is quits


def test_readonly_child_never_imports_producer_factories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    initial = builtins.__import__

    def guarded(name: str, *a: object, **kw: object) -> object:
        if name.startswith(("scoreform", "quillan", "pds_core.module_profiles")):
            raise AssertionError("producer import forbidden")
        return initial(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", guarded)
    status, _, _, previews = _drive(
        f"{tmp_path}\n1\n1\nb\n", tmp_path,
    )
    assert status == "back" and len(previews) == 1
