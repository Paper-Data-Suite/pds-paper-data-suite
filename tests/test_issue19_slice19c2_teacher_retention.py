"""#19C2: fresh first teacher consent, exact #18 Core custody only."""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path
from typing import Callable

import pytest

from paper_data_suite.returned_paper_authorized_retention import (
    Approver,
    AuthorizedRetentionResultV1,
    authorize_and_retain_sources,
)
from paper_data_suite.returned_paper_inbox import InboxEntry, InboxInventory
from paper_data_suite.returned_paper_preview_contract import (
    IntakePreview,
    PagePreview,
    SourcePreview,
)
from paper_data_suite.returned_paper_processing_contract import (
    PaperProcessingPlanV1,
    build_processing_plan,
)
from paper_data_suite.returned_paper_teacher_retention import (
    render_teacher_retention_result,
    run_teacher_first_retention,
)

_SNAPSHOT = "a" * 64


def _case(
    tmp_path: Path, *, two: bool = False,
) -> tuple[PaperProcessingPlanV1, tuple[Path, ...]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inbox = workspace / "scans_inbox"
    inbox.mkdir()
    paths = (
        (inbox / "SECRET_student_1.pdf", inbox / "SECRET_student_2.pdf")
        if two else (inbox / "SECRET_student_1.pdf",)
    )
    sources = []
    for number, path in enumerate(paths, 1):
        path.write_bytes(f"%PDF-1.4\n% synthetic {number}\n".encode())
        sources.append(SourcePreview(
            number, "observed", (
                PagePreview(1, "candidate_unverified", "scoreform"),
                PagePreview(2, "missing_qr"),
            ), hashlib.sha256(path.read_bytes()).hexdigest(),
        ))
    plan = build_processing_plan(
        workspace, paths, IntakePreview(tuple(sources), ()),
        ((1, 1), (2, 1)) if two else ((1, 1),),
    )
    return plan, paths


def _observer(plan: PaperProcessingPlanV1):
    def observe(paths: tuple[Path, ...]) -> tuple[SourcePreview, ...]:
        return tuple(SourcePreview(
            next(
                index for index, row in enumerate(plan.sources, 1)
                if row.source_path == path
            ),
            "observed", plan.sources[next(
                index for index, row in enumerate(plan.sources)
                if row.source_path == path
            )].observation.pages,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ) for path in paths)
    return observe


def _drive(
    plan: PaperProcessingPlanV1, text: str, *,
    execute: Callable[
        [PaperProcessingPlanV1, Approver], AuthorizedRetentionResultV1
    ] | None = None,
) -> tuple[str, str]:
    output = StringIO()
    kwargs = {"workspace_guard": lambda _: True}
    if execute is not None:
        kwargs["execute"] = execute
    navigation = run_teacher_first_retention(
        plan, input_stream=StringIO(text), output=output,
        show_header=lambda title: output.write(f"HEADER {title}\n"),
        **kwargs,
    )
    return navigation, output.getvalue()


@pytest.mark.parametrize("answer,navigation", [
    ("CANCEL\n", "back"), ("yes\n", "back"), ("\n", "back"),
    ("b\n", "back"), ("m\n", "home"), ("q\n", "quit"),
    ("", "quit"), ("rEtAiN later\n", "back"),
    ("RETAIN\x00\n", "back"), ("x" * 70 + "\n", "back"),
])
def test_anything_other_than_exact_retain_cancels_before_custody(
    tmp_path: Path, answer: str, navigation: str,
) -> None:
    plan, _ = _case(tmp_path)
    writes: list[Path] = []

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        return authorize_and_retain_sources(
            plan, approve=approve, observe=_observer(plan),
            retain=lambda _root, path: writes.append(path),  # type: ignore[arg-type]
        )

    status, output = _drive(plan, answer, execute=execute)
    assert status == navigation
    assert "Status: cancelled." in output
    assert "No Core retention was requested" in output
    assert "SECRET_student" not in output
    assert str(tmp_path) not in output
    assert not writes
    assert not (plan.workspace_root / "scans").exists()


def test_exact_retain_creates_one_actual_core_custody_record(
    tmp_path: Path,
) -> None:
    from pds_core.scan_retention import retain_source_scan

    plan, paths = _case(tmp_path)
    writes: list[Path] = []
    original = paths[0].read_bytes()

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        def retain(root: Path, source: Path):
            writes.append(source)
            return retain_source_scan(root, source)

        return authorize_and_retain_sources(
            plan, approve=approve, observe=_observer(plan), retain=retain,
        )

    status, output = _drive(plan, "RETAIN\n", execute=execute)
    assert status == "back" and writes == [paths[0]]
    assert "ALL 2 physical pages" in output
    assert "including unselected pages" in output
    assert "Status: retained." in output
    assert "Verified Core-retained whole-file receipts: 1." in output
    assert "No producer routing, scoring, or grading" in output
    assert "SECRET_student" not in output and str(tmp_path) not in output
    assert paths[0].read_bytes() == original
    assert len(tuple((plan.workspace_root / "scans" / "source").rglob("*.pdf"))) == 1


def test_digest_and_challenge_from_exact_fresh_review_bound_to_decision(
    tmp_path: Path,
) -> None:
    plan, _ = _case(tmp_path)
    captured: list[tuple[str, str, str]] = []

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        def witness(review):
            decision = approve(review)
            captured.append((decision.decision, decision.plan_digest,
                             decision.challenge))
            return decision

        return authorize_and_retain_sources(
            plan, approve=witness, observe=_observer(plan),
            retain=lambda *_: pytest.fail("no write on cancellation"),
        )

    _, output = _drive(plan, "CANCEL\n", execute=execute)
    assert "Status: cancelled." in output
    assert len(captured) == 1
    assert captured[0][0] == "cancel"
    assert len(captured[0][1]) == 64 and len(captured[0][2]) == 32


def test_stale_source_refuses_before_requesting_confirmation(
    tmp_path: Path,
) -> None:
    plan, paths = _case(tmp_path)
    paths[0].write_bytes(b"changed bytes")

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        return authorize_and_retain_sources(
            plan, approve=approve, observe=_observer(plan),
        )

    _, output = _drive(plan, "RETAIN\n", execute=execute)
    assert "Status: rejected." in output
    assert "First Consent" not in output
    assert not (plan.workspace_root / "scans").exists()


def test_unverified_core_receipt_is_uncertain_and_not_retried(
    tmp_path: Path,
) -> None:
    plan, _ = _case(tmp_path)
    calls = 0

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        def broken(_root: Path, _source: Path):
            nonlocal calls
            calls += 1
            raise OSError("PRIVATE STUDENT DATA")

        return authorize_and_retain_sources(
            plan, approve=approve, observe=_observer(plan), retain=broken,
        )

    _, output = _drive(plan, "RETAIN\n", execute=execute)
    assert calls == 1
    assert "Status: uncertain." in output
    assert "Do not retry automatically" in output
    assert "PRIVATE" not in output


def test_partial_retention_reports_verified_and_unretained_sources(
    tmp_path: Path,
) -> None:
    from pds_core.scan_retention import retain_source_scan

    plan, paths = _case(tmp_path, two=True)
    call_count: dict[Path, int] = {}
    actual_observer = _observer(plan)

    def changed(paths_to_check: tuple[Path, ...]):
        path = paths_to_check[0]
        call_count[path] = call_count.get(path, 0) + 1
        if path == paths[1] and call_count[path] == 2:
            path.write_bytes(b"source changed after consent")
        return actual_observer(paths_to_check)

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        return authorize_and_retain_sources(
            plan, approve=approve, observe=changed, retain=retain_source_scan,
        )

    _, output = _drive(plan, "RETAIN\n", execute=execute)
    assert "Status: partial." in output
    assert "Verified Core-retained whole-file receipts: 1." in output
    assert "Do not blindly retry" in output
    assert len(tuple((plan.workspace_root / "scans" / "source").rglob("*.pdf"))) == 1


def test_unexpected_exception_after_approval_is_not_a_clean_rollback(
    tmp_path: Path,
) -> None:
    plan, _ = _case(tmp_path)

    def broken(_plan: PaperProcessingPlanV1, _approve: Approver):
        raise RuntimeError("SECRET teacher file path")

    _, output = _drive(plan, "RETAIN\n", execute=broken)
    assert "status could not be verified" in output
    assert "Do not retry" in output and "SECRET" not in output


def test_nonplan_is_refused_before_interaction() -> None:
    with pytest.raises(ValueError):
        run_teacher_first_retention(
            object(),  # type: ignore[arg-type]
            input_stream=StringIO("RETAIN\n"), output=StringIO(),
            show_header=lambda _: None,
        )


def _inbox_drive(
    tmp_path: Path, commands: str,
    *,
    list_inbox: Callable[[Path], InboxInventory] | None = None,
    preview: Callable[[tuple[Path, ...]], IntakePreview] | None = None,
) -> tuple[str, str, list[Path], list[tuple[Path, ...]]]:
    from paper_data_suite.returned_paper_teacher_inbox import (
        run_readonly_teacher_inbox,
    )

    entries = (InboxEntry(
        1, tmp_path / "scans_inbox" / "SECRET_student.pdf", "pdf", "eligible", 42,
    ),)
    standard = InboxInventory(entries, _SNAPSHOT)
    listings: list[Path] = []
    previews: list[tuple[Path, ...]] = []
    default = IntakePreview((SourcePreview(1, "observed", (
        PagePreview(1, "candidate_unverified", "scoreform"),
        PagePreview(2, "missing_qr"),
    ), "b" * 64),), ())

    def listing(root: Path):
        listings.append(root)
        return list_inbox(root) if list_inbox else standard

    def observing(paths: tuple[Path, ...]):
        previews.append(paths)
        return preview(paths) if preview else default

    output = StringIO()
    status = run_readonly_teacher_inbox(
        input_stream=StringIO(f"{tmp_path}\n1\n1\n" + commands),
        output=output, show_header=lambda title: output.write(f"HEAD {title}\n"),
        list_inbox=listing, preview=observing,
        render=lambda _: "SAFE PREVIEW\n",
    )
    return status, output.getvalue(), listings, previews


@pytest.mark.parametrize("commands", ["b\n", "m\n", "q\n", "r\nb\n"])
def test_no_successful_p_never_enters_core_retention(
    tmp_path: Path, commands: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_retention as custody

    monkeypatch.setattr(
        custody, "run_teacher_first_retention",
        lambda *a, **kw: pytest.fail("retention without P"),
    )
    status, output, _, _ = _inbox_drive(tmp_path, commands)
    assert status in {"back", "home", "quit"}
    assert "No retention attempted" in output or "retention" in output.lower()


def test_retain_after_plan_requires_fresh_snapshot_and_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_retention as custody

    calls: list[PaperProcessingPlanV1] = []

    def witness(plan: PaperProcessingPlanV1, **kwargs: object):
        calls.append(plan)
        return "back"

    monkeypatch.setattr(custody, "run_teacher_first_retention", witness)
    status, output, lists, previews = _inbox_drive(tmp_path, "p\nr\n")
    assert status == "back" and len(calls) == 1
    assert len(lists) == 4 and len(previews) == 3
    assert calls[0].authorized is False
    assert "R. Retain whole selected files" in output
    assert "SECRET_student" not in output and str(tmp_path) not in output


@pytest.mark.parametrize("changed", ["snapshot", "source"])
def test_stale_between_p_and_r_refused_before_retention(
    tmp_path: Path, changed: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_retention as custody

    monkeypatch.setattr(
        custody, "run_teacher_first_retention",
        lambda *a, **kw: pytest.fail("stale plan reached retention"),
    )
    listed = 0
    observed = 0

    def listing(root: Path):
        nonlocal listed
        listed += 1
        return InboxInventory((InboxEntry(
            1, root / "scans_inbox" / "SECRET_student.pdf", "pdf", "eligible", 42,
        ),), _SNAPSHOT if changed != "snapshot" or listed < 4 else "c" * 64)

    def preview(paths: tuple[Path, ...]):
        nonlocal observed
        observed += 1
        return IntakePreview((SourcePreview(
            1, "observed", (PagePreview(1, "missing_qr"),),
            "b" * 64 if changed != "source" or observed < 3 else "d" * 64,
        ),), ())

    status, output, _, _ = _inbox_drive(
        tmp_path, "p\nr\n", list_inbox=listing, preview=preview,
    )
    assert status == "back"
    assert "Core custody request refused" in output
    assert "SECRET" not in output


def test_p_only_still_never_imports_core_retainer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object):
        if name.startswith("paper_data_suite.returned_paper_teacher_retention"):
            pytest.fail("P imported C2 custody without R")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    status, output, _, _ = _inbox_drive(tmp_path, "p\nb\n")
    assert status == "back" and "Plan Review Only" in output


def test_render_rejects_untyped_custody_result() -> None:
    with pytest.raises(ValueError):
        render_teacher_retention_result(object())  # type: ignore[arg-type]


def test_current_core_workspace_mismatch_refuses_before_any_writer(
    tmp_path: Path,
) -> None:
    plan, _ = _case(tmp_path)
    calls = 0
    output = StringIO()

    def forbidden(_plan: PaperProcessingPlanV1, _approve: Approver):
        nonlocal calls
        calls += 1
        pytest.fail("workspace mismatch reached Core writer")

    result = run_teacher_first_retention(
        plan, input_stream=StringIO("RETAIN\n"), output=output,
        show_header=lambda _: None, execute=forbidden,
        workspace_guard=lambda _: False,
    )
    assert result == "back" and calls == 0
    assert "Active Core workspace" in output.getvalue()
    assert "No Core retention requested" in output.getvalue()


def test_active_workspace_rechecked_during_teacher_confirmation(
    tmp_path: Path,
) -> None:
    plan, _ = _case(tmp_path)
    checked = 0
    writes = 0

    def workspace_check(_: Path) -> bool:
        nonlocal checked
        checked += 1
        return checked == 1

    def execute(plan: PaperProcessingPlanV1, approve: Approver):
        def forbidden(*_: object):
            nonlocal writes
            writes += 1
            pytest.fail("Core retention ran after workspace changed")

        return authorize_and_retain_sources(
            plan, approve=approve, observe=_observer(plan),
            retain=forbidden,
        )

    output = StringIO()
    result = run_teacher_first_retention(
        plan, input_stream=StringIO("RETAIN\n"), output=output,
        show_header=lambda _: None, execute=execute,
        workspace_guard=workspace_check,
    )
    assert result == "back" and checked == 2 and writes == 0
    assert "Status: cancelled." in output.getvalue()
    assert "workspace changed during consent" in output.getvalue()


def test_default_workspace_guard_reads_current_qualified_core_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import workspace_setup
    from paper_data_suite.returned_paper_teacher_retention import (
        _active_core_workspace_matches,
    )

    root = tmp_path / "workspace"
    root.mkdir()
    matching = workspace_setup.WorkspaceObservation(
        root=root, source="saved_config", exists=True,
        is_dir=True, is_writable=True,
        config_path=tmp_path / "settings", default_root=tmp_path,
        state=workspace_setup.WorkspacePresentationState.EXISTING_DIRECTORY,
        reason="synthetic workspace",
    )
    monkeypatch.setattr(
        workspace_setup, "observe_workspace", lambda: matching,
    )
    assert _active_core_workspace_matches(root)
    assert not _active_core_workspace_matches(tmp_path / "other")
    monkeypatch.setattr(
        workspace_setup, "observe_workspace",
        lambda: workspace_setup.WorkspaceObservation(
            root=root, source="saved_config", exists=True,
            is_dir=True, is_writable=False,
            config_path=tmp_path / "settings", default_root=tmp_path,
            state=workspace_setup.WorkspacePresentationState.INVALID,
            reason="synthetic permission loss",
        ),
    )
    assert not _active_core_workspace_matches(root)
