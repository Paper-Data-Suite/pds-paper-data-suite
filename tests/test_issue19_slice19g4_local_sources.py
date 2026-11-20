"""#19G4: direct source files reach #18 only after a distinct P/R/RETAIN path."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    PaperProcessingPlanV1,
)
from paper_data_suite.returned_paper_teacher_local import (
    _check_selection,
    run_selected_local_paper_processing,
)


def _observation(digest: str = "a" * 64) -> IntakePreview:
    return IntakePreview((SourcePreview(
        1, "observed", (
            PagePreview(1, "candidate_unverified", "scoreform"),
            PagePreview(2, "candidate_unverified", "quillan"),
            PagePreview(3, "missing_qr"),
        ), digest,
    ),), ())


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "core_workspace"
    root.mkdir()
    source = tmp_path / "local_student_private.pdf"
    source.write_bytes(b"Synthetic placeholder: never a real student document")
    return root, source


def _drive(
    root: Path, source: Path, choices: str,
    *, preview=None, guard=None,
) -> tuple[str, str]:
    output = StringIO()
    result = run_selected_local_paper_processing(
        (source,), input_stream=StringIO(choices), output=output,
        show_header=lambda label: output.write("HEADER " + label + "\n"),
        preview=preview if preview is not None else lambda _: _observation(),
        render=lambda _: "SAFE READ-ONLY PHYSICAL PREVIEW\n",
        workspace_guard=guard if guard is not None else lambda root_: root_ == root,
    )
    return result, output.getvalue()


@pytest.mark.parametrize("choice,expected", [
    ("b\n", "back"), ("m\n", "home"), ("q\n", "quit"), ("", "quit"),
])
def test_workspace_menu_navigation_never_observes_or_writes(
    tmp_path: Path, choice: str, expected: str,
) -> None:
    root, source = _setup(tmp_path)
    calls: list[tuple[Path, ...]] = []
    nav, text = _drive(
        root, source, choice,
        preview=lambda paths: calls.append(paths) or _observation(),
    )
    assert nav == expected and not calls
    assert "CORE" not in text or "custody" in text.lower()


def test_only_explicit_workspace_can_preview_local_files(tmp_path: Path) -> None:
    root, source = _setup(tmp_path)
    observed: list[tuple[Path, ...]] = []
    nav, text = _drive(
        root, source, f"{root}\n1\nb\n",
        preview=lambda paths: observed.append(paths) or _observation(),
        guard=lambda _: False,
    )
    assert nav == "back" and not observed
    assert "Active Core workspace differs" in text
    assert str(source) not in text and str(root) not in text


def test_local_selects_two_of_three_physical_pages_and_plan_is_read_only(
    tmp_path: Path,
) -> None:
    root, source = _setup(tmp_path)
    calls: list[tuple[Path, ...]] = []
    nav, text = _drive(
        root, source, f"{root}\n2,1\nP\nB\n",
        preview=lambda paths: calls.append(paths) or _observation(),
    )
    assert nav == "back" and calls == [(source,), (source,)]
    assert "Selected 2 physical pages from 1 local source(s)" in text
    assert "Whole-file custody would include 3 physical pages" in text
    assert "including 1 unselected page(s)" in text
    assert "No Core files were retained" in text
    assert str(root) not in text and str(source) not in text


def test_retain_requires_plan_and_fresh_preview_then_c2_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_retention as custody

    root, source = _setup(tmp_path)
    captured: list[PaperProcessingPlanV1] = []
    calls: list[tuple[Path, ...]] = []

    def accept(plan: PaperProcessingPlanV1, **_kwargs: object) -> str:
        captured.append(plan)
        return "back"

    monkeypatch.setattr(custody, "run_teacher_first_retention", accept)
    nav, text = _drive(
        root, source, f"{root}\n1,2\nR\nP\nR\n",
        preview=lambda paths: calls.append(paths) or _observation(),
    )
    assert nav == "back" and len(calls) == 3 and len(captured) == 1
    plan = captured[0]
    assert plan.authorized is False and plan.workspace_root == root
    assert plan.sources[0].source_path == source  # Outside Core inbox.
    assert tuple((p.source_number, p.page_number) for p in plan.selected_pages) == (
        (1, 1), (1, 2)
    )
    assert "Review the plan with P" in text
    assert str(source) not in text and str(root) not in text


def test_no_authorization_when_local_preview_is_stale_at_p(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_retention as custody

    root, source = _setup(tmp_path)
    calls = 0

    def changed(_: tuple[Path, ...]) -> IntakePreview:
        nonlocal calls
        calls += 1
        return _observation("a" * 64 if calls == 1 else "b" * 64)

    monkeypatch.setattr(
        custody, "run_teacher_first_retention",
        lambda *_a, **_k: pytest.fail("stale source triggered a custody attempt"),
    )
    nav, text = _drive(root, source, f"{root}\n1\nP\n", preview=changed)
    assert nav == "back" and calls == 2
    assert "Local processing plan refused" in text


def test_no_authorization_when_local_preview_changes_after_p(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_retention as custody

    root, source = _setup(tmp_path)
    calls = 0

    def changed(_: tuple[Path, ...]) -> IntakePreview:
        nonlocal calls
        calls += 1
        return _observation("a" * 64 if calls <= 2 else "b" * 64)

    monkeypatch.setattr(
        custody, "run_teacher_first_retention",
        lambda *_a, **_k: pytest.fail("stale R triggered a custody attempt"),
    )
    nav, text = _drive(
        root, source, f"{root}\n1\nP\nR\n", preview=changed
    )
    assert nav == "back" and calls == 3
    assert "Core custody refused" in text


def test_workspace_guard_is_repeated_at_p_and_r(tmp_path: Path) -> None:
    root, source = _setup(tmp_path)
    count = 0

    def changing(_: Path) -> bool:
        nonlocal count
        count += 1
        return count < 3

    nav, text = _drive(
        root, source, f"{root}\n1\nP\nR\n", guard=changing
    )
    assert nav == "back" and count == 3
    assert "Core custody refused" in text


@pytest.mark.parametrize("bad", [
    "0", "4", "1,1", "1,,2", "1..2", "all", "99999", "1;2",
])
def test_invalid_page_selection_cannot_reach_plan(
    tmp_path: Path, bad: str,
) -> None:
    root, source = _setup(tmp_path)
    nav, text = _drive(root, source, f"{root}\n{bad}\n")
    assert nav == "back" and "processing plan REVIEW ONLY" not in text
    assert "No Core custody requested" in text


def test_blank_page_selection_is_not_implicit_all(tmp_path: Path) -> None:
    root, source = _setup(tmp_path)
    nav, text = _drive(root, source, f"{root}\n\n")
    assert nav == "back" and "No pages selected" in text


def test_direct_core_custody_source_is_forbidden_before_preview(
    tmp_path: Path,
) -> None:
    root, _ = _setup(tmp_path)
    private = root / "scans" / "source" / "already_retained.pdf"
    with pytest.raises(ValueError):
        _check_selection((private,), root)
    nav, text = _drive(
        root, private, f"{root}\n1\n",
        preview=lambda _: pytest.fail("never reobserve Core custody as original"),
    )
    assert nav == "back" and "No Core custody requested" in text
    assert str(private) not in text


def test_local_preview_only_option_1_never_enters_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_local as local
    from paper_data_suite.returned_paper_teacher_preview import (
        run_readonly_teacher_papers,
    )

    _, source = _setup(tmp_path)
    monkeypatch.setattr(
        local, "run_selected_local_paper_processing",
        lambda *_a, **_k: pytest.fail("option 1 must be preview-only"),
    )
    shown = StringIO()
    quit_shell = run_readonly_teacher_papers(
        input_stream=StringIO(f"1\n1\n{source}\nb\n"),
        output=shown, show_header=lambda _: None,
        preview=lambda _: _observation(), render=lambda _: "SAFE\n",
    )
    assert quit_shell is False and "No Core source retention" in shown.getvalue()


def test_new_option_3_selects_exact_local_source_without_preview_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_local as local
    from paper_data_suite.returned_paper_teacher_preview import (
        run_readonly_teacher_papers,
    )

    _, source = _setup(tmp_path)
    captured: list[tuple[Path, ...]] = []

    def local_flow(paths: tuple[Path, ...], **_kwargs: object) -> str:
        captured.append(paths)
        return "back"

    monkeypatch.setattr(local, "run_selected_local_paper_processing", local_flow)
    out = StringIO()
    status = run_readonly_teacher_papers(
        input_stream=StringIO(f"3\n1\n{source}\nb\n"),
        output=out, show_header=lambda _: None,
        preview=lambda _: pytest.fail("read-only test seam must not be reused"),
        render=lambda _: "SHOULD NOT DISPLAY\n",
    )
    assert status is False and captured == [(source,)]
    assert "3. Process explicitly selected local files" in out.getvalue()
    assert "SHOULD NOT DISPLAY" not in out.getvalue()


def test_g4_installed_opt_in_builds_fresh_wheel_and_executes_local_files() -> None:
    script = Path("scripts/issue19_e3a_windows_installed_acceptance.ps1").read_text(
        encoding="utf-8"
    )
    assert "[switch]$IncludeLocalFiles" in script
    assert "git archive --format=zip HEAD" in script
    assert "issue19_g4_installed_local_files.py" in script
    assert "Assert-Exit 'G4 actual installed local-file Home journey'" in script
    assert "SUITE19_G4_ACTUAL_INSTALLED_LOCAL_FILES_VERIFIED" in script
    witness = Path("scripts/issue19_g4_installed_local_files.py").read_text(
        encoding="utf-8"
    )
    assert '"9", "3", "1"' in witness
    assert '"1,2", "P", "R"' in witness
    assert "inbox_source.rename(source)" in witness
    assert "_drive_installed_cli(" in witness
    assert '"Core attempted physical pages: 2"' in witness
