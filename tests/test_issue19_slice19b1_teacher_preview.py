"""#19B1: explicit Teacher Home file preview, never Core custody or dispatch."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Callable

import pytest

from paper_data_suite.returned_paper_preview_contract import IntakePreview
from paper_data_suite.returned_paper_teacher_preview import (
    run_readonly_teacher_papers,
)


def _drive(
    choices: str,
    *,
    preview: Callable[[tuple[Path, ...]], IntakePreview] | None = None,
    render: Callable[[IntakePreview], str] | None = None,
) -> tuple[bool, str, list[tuple[Path, ...]]]:
    calls: list[tuple[Path, ...]] = []
    output = StringIO()

    def observe(paths: tuple[Path, ...]) -> IntakePreview:
        calls.append(paths)
        if preview is not None:
            return preview(paths)
        return IntakePreview((), ())

    result = run_readonly_teacher_papers(
        input_stream=StringIO(choices),
        output=output,
        show_header=lambda title: output.write(f"SCREEN {title}\n"),
        preview=observe,
        render=render if render is not None else lambda _: "SOURCE SAFE\n",
    )
    return result, output.getvalue(), calls


@pytest.mark.parametrize("choice,quits", [
    ("b\n", False), ("m\n", False), ("q\n", True), ("", True),
])
def test_home_preview_menu_navigation_never_reads_files(
    choice: str, quits: bool,
) -> None:
    result, output, calls = _drive(choice)
    assert result is quits
    assert calls == []
    assert "read-only" in output.lower()


def test_help_is_nonmutating_and_preserves_home_return() -> None:
    result, output, calls = _drive("h\nb\n")
    assert not result and not calls
    assert "absolute PDF, PNG, or JPEG" in output
    assert "not a command" in output
    assert "Any retention or eligible dispatch needs fresh separate consent." in output


def test_explicit_absolute_source_is_only_observed_after_selection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "first.pdf"
    result, output, calls = _drive(f"1\n1\n{source}\nb\n")
    assert not result
    assert calls == [(source,)]
    assert "SOURCE SAFE" in output
    assert "No Core source retention" in output
    assert str(source) not in output


def test_two_explicit_files_preserve_order_and_are_not_enumerated(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "a.jpg", tmp_path / "b.png"
    result, output, calls = _drive(f"1\n2\n{first}\n{second}\nm\n")
    assert not result
    assert calls == [(first, second)]
    assert "Read-only Papers Preview" in output


@pytest.mark.parametrize("selection", [
    "1\n\n", "1\n1\n\n", "1\n0\n", "1\n9\n", "1\ninvalid\n",
    "1\n1\nrelative.pdf\n", "1\n1\n*.pdf\n", "1\n1\nother.csv\n",
])
def test_invalid_or_cancelled_selection_cannot_trigger_preview(
    selection: str,
) -> None:
    result, output, calls = _drive(selection + "b\n")
    assert not result
    assert not calls
    assert "selected local files" in output


def test_duplicate_paths_refused_before_preview(tmp_path: Path) -> None:
    source = tmp_path / "same.pdf"
    result, output, calls = _drive(f"1\n2\n{source}\n{source}\nb\n")
    assert not result and not calls
    assert "duplicate source selection" in output
    assert str(source) not in output


def test_source_failure_is_sanitized_and_home_remains_available(
    tmp_path: Path,
) -> None:
    def bad_preview(_: tuple[Path, ...]) -> IntakePreview:
        raise RuntimeError("PRIVATE PATH /some/teacher/student.pdf")

    result, output, calls = _drive(
        f"1\n1\n{tmp_path / 'paper.pdf'}\nb\n", preview=bad_preview,
    )
    assert not result and len(calls) == 1
    assert "Read-only preview was unavailable" in output
    assert "PRIVATE" not in output
    assert "teacher/student" not in output


def test_render_failure_is_sanitized_and_home_remains_available(
    tmp_path: Path,
) -> None:
    def broken(_: IntakePreview) -> str:
        raise ValueError("secret source content")

    result, output, calls = _drive(
        f"1\n1\n{tmp_path / 'paper.png'}\nb\n", render=broken,
    )
    assert not result and calls
    assert "secret source" not in output
    assert "Read-only preview was unavailable" in output


def test_after_preview_does_not_accept_additional_processing(tmp_path: Path) -> None:
    result, output, calls = _drive(f"1\n1\n{tmp_path / 'a.pdf'}\n1\nm\n")
    assert not result and len(calls) == 1
    assert "Choose B, M or Q" in output
    assert output.count("No Core source retention") == 1


def test_eof_during_file_selection_quits_without_preview(tmp_path: Path) -> None:
    result, _, calls = _drive(f"1\n2\n{tmp_path / 'one.pdf'}\n")
    assert result and not calls


def test_eof_after_completed_preview_quits(tmp_path: Path) -> None:
    result, _, calls = _drive(f"1\n1\n{tmp_path / 'one.pdf'}\n")
    assert result and len(calls) == 1


def test_input_exceeds_bounded_limit_without_preview() -> None:
    result, _, calls = _drive("1\n1\n" + "x" * 4100 + "\nb\n")
    assert not result and not calls


def test_unsupported_callback_is_refused_before_any_input() -> None:
    with pytest.raises(ValueError):
        run_readonly_teacher_papers(
            input_stream=StringIO(""),
            output=StringIO(),
            show_header=lambda _: None,
            preview=None,  # type: ignore[arg-type]
        )


def test_home_option_9_opens_readonly_controller_without_other_menu_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_preview as paper_ui
    from paper_data_suite.applications import ApplicationInventory
    from paper_data_suite.teacher_experience_contracts import (
        CoreTeacherContractObservation,
    )
    from paper_data_suite.teacher_home import run_teacher_home

    calls: list[str] = []
    actual = paper_ui.run_readonly_teacher_papers

    def injected(**kwargs: object) -> bool:
        calls.append("item_9")
        return actual(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(paper_ui, "run_readonly_teacher_papers", injected)
    incoming, outgoing = StringIO("9\nb\nq\n"), StringIO()
    assert run_teacher_home(
        input_stream=incoming,
        output=outgoing,
        collect_inventory=lambda: ApplicationInventory(()),
        launch=lambda _: pytest.fail("no launch from paper preview"),
        doctor=lambda: pytest.fail("no doctor from paper preview"),
        show_help=lambda: None,
        recent=lambda: (),
        observe_contract=lambda: CoreTeacherContractObservation(
            False, frozenset(), False, False
        ),
        core_importer=lambda _: None,
    ) == 0
    assert calls == ["item_9"]
    text = outgoing.getvalue()
    assert "9. Process Returned Papers — preview + consent-gated processing" in text
    assert "later slices" not in text
    assert "Notes & Tasks — not yet available" in text
    assert "Attention Needed — not yet available" in text
    assert text.count("Teacher Home") >= 2


def test_home_entry_and_early_cancel_do_not_call_source_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_preview as paper_ui
    from paper_data_suite.applications import ApplicationInventory
    from paper_data_suite.teacher_experience_contracts import (
        CoreTeacherContractObservation,
    )
    from paper_data_suite.teacher_home import run_teacher_home

    def forbidden(_: tuple[Path, ...]) -> IntakePreview:
        pytest.fail("opening item 9 or cancelling must not inspect files")

    # Function defaults are bound during definition; wrap only for this test.
    original = paper_ui.run_readonly_teacher_papers

    def guarded(**kwargs: object) -> bool:
        return original(**kwargs, preview=forbidden)  # type: ignore[arg-type]

    monkeypatch.setattr(paper_ui, "run_readonly_teacher_papers", guarded)
    output = StringIO()
    assert run_teacher_home(
        input_stream=StringIO("9\n1\n\nb\nq\n"), output=output,
        collect_inventory=lambda: ApplicationInventory(()),
        launch=lambda _: pytest.fail("unexpected launcher"),
        doctor=lambda: 0, show_help=lambda: None,
        recent=lambda: (),
        observe_contract=lambda: CoreTeacherContractObservation(
            False, frozenset(), False, False
        ),
        core_importer=lambda _: None,
    ) == 0
    assert "Preview selection cancelled" in output.getvalue()
