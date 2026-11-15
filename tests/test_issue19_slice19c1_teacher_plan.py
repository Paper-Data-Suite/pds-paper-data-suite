"""#19C1: nonmutating #18 plan review after fresh B2 inbox/preview checks."""

from __future__ import annotations

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
    run_readonly_teacher_inbox,
)
from paper_data_suite.returned_paper_teacher_plan import (
    TeacherPlanReviewError,
    review_readonly_processing_plan,
)

_SNAPSHOT = "a" * 64


def _observed(*, digest: str = "b" * 64) -> IntakePreview:
    return IntakePreview((
        SourcePreview(1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "missing_qr"),
            PagePreview(3, "candidate_unverified", "quillan"),
        ), sha256_advisory=digest),
    ), ())


def _paths(tmp_path: Path) -> tuple[Path, ...]:
    return (tmp_path / "opaque-private.pdf",)


def _review(tmp_path: Path, *, pages: tuple[tuple[int, int], ...]) -> str:
    return review_readonly_processing_plan(
        tmp_path, _paths(tmp_path), _observed(), pages
    )


def test_one_selected_page_discloses_whole_file_retention(tmp_path: Path) -> None:
    text = _review(tmp_path, pages=((1, 1),))
    assert "Selected source files: 1; physical pages: 1" in text
    assert "Whole-file custody would include 3 physical pages" in text
    assert "including 2 unselected page(s)" in text
    assert "candidate" in text.lower()
    assert "ENTIRE" in text
    assert "No Core files were retained" in text
    assert str(tmp_path) not in text
    assert "opaque-private" not in text


def test_selected_pages_preserve_order_and_unresolved_counts(
    tmp_path: Path,
) -> None:
    text = _review(tmp_path, pages=((1, 3), (1, 2)))
    assert "pages 3, 2" in text
    assert "physical pages: 2" in text
    assert "Unverified QR candidates: 1" in text
    assert "other/unresolved pages: 1" in text
    assert "including 1 unselected page(s)" in text


@pytest.mark.parametrize("pages", [
    (), ((1, 0),), ((1, 4),), ((2, 1),),
    ((1, 1), (1, 1)), ((1, -1),), ((1, 1, 2),),
])
def test_unqualified_physical_selections_never_build_a_review(
    tmp_path: Path, pages: tuple[tuple[int, ...], ...],
) -> None:
    with pytest.raises(TeacherPlanReviewError):
        review_readonly_processing_plan(
            tmp_path, _paths(tmp_path), _observed(), pages  # type: ignore[arg-type]
        )


def test_no_observation_fingerprint_refuses_plan(tmp_path: Path) -> None:
    before = _observed()
    without_digest = IntakePreview((
        SourcePreview(1, "observed", before.sources[0].pages),
    ), ())
    with pytest.raises(TeacherPlanReviewError):
        review_readonly_processing_plan(
            tmp_path, _paths(tmp_path), without_digest, ((1, 1),)
        )


def test_mismatched_source_list_refuses_plan(tmp_path: Path) -> None:
    with pytest.raises(TeacherPlanReviewError):
        review_readonly_processing_plan(tmp_path, (), _observed(), ((1, 1),))


def test_relative_workspace_refuses_plan(tmp_path: Path) -> None:
    with pytest.raises(TeacherPlanReviewError):
        review_readonly_processing_plan(
            Path("relative"), _paths(tmp_path), _observed(), ((1, 1),)
        )


def test_observation_is_not_modified_or_persisted(tmp_path: Path) -> None:
    observed = _observed()
    chosen = _paths(tmp_path)
    before = sorted(tmp_path.rglob("*"))
    text = review_readonly_processing_plan(
        tmp_path, chosen, observed, ((1, 1),)
    )
    assert observed == _observed()
    assert sorted(tmp_path.rglob("*")) == before
    assert "review" in text.lower()


def _inbox_driven(
    tmp_path: Path,
    commands: str,
    *,
    list_inbox: Callable[[Path], InboxInventory] | None = None,
    preview: Callable[[tuple[Path, ...]], IntakePreview] | None = None,
) -> tuple[str, str]:
    inbox_entry = InboxEntry(
        1, tmp_path / "scans_inbox" / "private.pdf", "pdf", "eligible", 1234
    )
    standard = InboxInventory((inbox_entry,), _SNAPSHOT)
    output = StringIO()
    result = run_readonly_teacher_inbox(
        input_stream=StringIO(f"{tmp_path}\n1\n1\n" + commands),
        output=output,
        show_header=lambda title: output.write(f"HEADER {title}\n"),
        list_inbox=list_inbox if list_inbox is not None else lambda _: standard,
        preview=preview if preview is not None else lambda _: _observed(),
        render=lambda _: "PATH-FREE PREVIEW\n",
    )
    return result, output.getvalue()


def test_p_requests_fresh_snapshot_and_observation_before_plan(
    tmp_path: Path,
) -> None:
    lists: list[Path] = []
    previews: list[tuple[Path, ...]] = []

    def listing(root: Path) -> InboxInventory:
        lists.append(root)
        return InboxInventory((InboxEntry(
            1, root / "scans_inbox" / "private.pdf", "pdf", "eligible", 1234
        ),), _SNAPSHOT)

    def observing(paths: tuple[Path, ...]) -> IntakePreview:
        previews.append(paths)
        return _observed()

    navigation, output = _inbox_driven(
        tmp_path, "p\nb\n", list_inbox=listing, preview=observing
    )
    assert navigation == "back"
    assert len(lists) == 3
    assert len(previews) == 2
    assert previews[0] == previews[1]
    assert "processing plan REVIEW ONLY" in output
    assert "No Core files were retained" in output
    assert "PRIVATE" not in output
    assert str(tmp_path) not in output


def test_changed_inbox_at_p_refuses_plan_without_repreview(
    tmp_path: Path,
) -> None:
    calls = 0
    reads = 0

    def listing(root: Path) -> InboxInventory:
        nonlocal calls
        calls += 1
        return InboxInventory((InboxEntry(
            1, root / "scans_inbox" / "private.pdf", "pdf", "eligible", 1234
        ),), _SNAPSHOT if calls < 3 else "c" * 64)

    def observing(_: tuple[Path, ...]) -> IntakePreview:
        nonlocal reads
        reads += 1
        return _observed()

    navigation, output = _inbox_driven(
        tmp_path, "p\nb\n", list_inbox=listing, preview=observing
    )
    assert navigation == "back"
    assert calls == 3 and reads == 1
    assert "Processing plan preview refused" in output
    assert "processing plan REVIEW ONLY" not in output


def test_changed_preview_at_p_refuses_plan(tmp_path: Path) -> None:
    calls = 0

    def observing(_: tuple[Path, ...]) -> IntakePreview:
        nonlocal calls
        calls += 1
        return _observed(digest="b" * 64 if calls == 1 else "d" * 64)

    navigation, output = _inbox_driven(
        tmp_path, "p\nb\n", preview=observing
    )
    assert navigation == "back"
    assert calls == 2
    assert "Processing plan preview refused" in output
    assert "processing plan REVIEW ONLY" not in output


@pytest.mark.parametrize("commands,expected", [
    ("b\n", "back"), ("m\n", "home"), ("q\n", "quit"),
    ("", "quit"),
])
def test_no_p_never_constructs_plan(
    tmp_path: Path, commands: str, expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_plan as plans

    def forbidden(*args: object, **kwargs: object) -> str:
        pytest.fail("no plan must be built without P")

    monkeypatch.setattr(plans, "review_readonly_processing_plan", forbidden)
    navigation, output = _inbox_driven(tmp_path, commands)
    assert navigation == expected
    assert "processing plan REVIEW ONLY" not in output


def test_multiple_p_reviews_require_fresh_observation_each_time(
    tmp_path: Path,
) -> None:
    lists = 0
    previews = 0

    def listing(root: Path) -> InboxInventory:
        nonlocal lists
        lists += 1
        return InboxInventory((InboxEntry(
            1, root / "scans_inbox" / "private.pdf", "pdf", "eligible", 1234
        ),), _SNAPSHOT)

    def observing(_: tuple[Path, ...]) -> IntakePreview:
        nonlocal previews
        previews += 1
        return _observed()

    navigation, output = _inbox_driven(
        tmp_path, "p\np\nb\n", list_inbox=listing, preview=observing
    )
    assert navigation == "back"
    assert lists == 4 and previews == 3
    assert output.count("processing plan REVIEW ONLY") == 2


def test_p_review_cannot_import_retainer_or_dispatcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original = builtins.__import__
    forbidden = (
        "paper_data_suite.returned_paper_authorized_retention",
        "paper_data_suite.returned_paper_ordered_dispatch",
        "pds_core.scan_retention",
    )

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(forbidden):
            pytest.fail("read-only plan tried to import mutation boundary")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    navigation, output = _inbox_driven(tmp_path, "p\nb\n")
    assert navigation == "back"
    assert "processing plan REVIEW ONLY" in output
