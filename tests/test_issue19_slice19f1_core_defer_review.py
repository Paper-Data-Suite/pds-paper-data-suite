"""#19F1: use only Core-recorded failures for an explicit third defer consent."""

from __future__ import annotations

from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest
from pds_core.route_registrations import RouteRegistrationNotFoundError
from pds_core.scan_resolution_metadata import load_scan_resolution_metadata

from paper_data_suite import returned_paper_teacher_recovery as recovery
from paper_data_suite.returned_paper_core_review import (
    DeferDecisionV1,
    DeferredReviewResultV1,
    DeferredReviewV1,
    execute_with_core_review,
)
from paper_data_suite.returned_paper_retained_requests import (
    prepare_retained_pds2_requests,
)
from paper_data_suite.returned_paper_teacher_dispatch_action import (
    TeacherDispatchActionResultV1,
)
from paper_data_suite.returned_paper_teacher_recovery import (
    TeacherCoreRecoveryError,
    run_teacher_core_review_menu,
)

_slice4 = import_module("test_issue18_slice4_ordered_dispatch")
_slice5 = import_module("test_issue18_slice5_core_review")


def _failed(root: Path):
    return _slice5._run(
        root, dispatcher=_slice5._failure_dispatch(
            RouteRegistrationNotFoundError("PRIVATE FAILURE DETAILS"),
        ),
    )


def _drive(core, value: str, *, guard=None):
    output = StringIO()
    heads: list[str] = []
    result = run_teacher_core_review_menu(
        core, input_stream=StringIO(value), output=output,
        show_header=heads.append, workspace_guard=guard or (lambda _: True),
    )
    return result, output.getvalue(), heads


def test_real_core_failure_defer_appends_one_verified_event(
    tmp_path: Path,
) -> None:
    core = _failed(tmp_path)
    root = core.execution.report.plan.workspace_root
    target = next(row for row in core.pages if row.review_state == "recorded")
    before_failure = _slice5.load_routing_failure_metadata(root, target.failure_id)
    nav, display, heads = _drive(core, "f\n1\nDEFER\n")
    assert nav == "back"
    assert len(heads) == 2 and "Third Teacher Consent" in heads[1]
    assert "deferral event was recorded" in display
    assert "remains unresolved" in display
    resolutions = tuple((root / "scans" / "review" / "resolutions").glob("*.json"))
    assert len(resolutions) == 1
    resolved = load_scan_resolution_metadata(root, resolutions[0].stem)
    assert resolved.failure_id == target.failure_id
    assert resolved.resolution_status == "deferred"
    assert (
        _slice5.load_routing_failure_metadata(root, target.failure_id)
        == before_failure
    )
    assert "PRIVATE FAILURE DETAILS" not in display
    assert str(tmp_path) not in display


@pytest.mark.parametrize(
    "reply", ["CANCEL", "NO", "RETAIN", "DISPATCH", "", "DEFER LATER"]
)
def test_third_consent_never_converts_other_reply_into_core_write(
    tmp_path: Path, reply: str,
) -> None:
    core = _failed(tmp_path)
    root = core.execution.report.plan.workspace_root
    _, text, _ = _drive(core, "F\n1\n" + reply + "\n")
    assert "Deferral cancelled" in text
    assert not (root / "scans" / "review" / "resolutions").exists()


@pytest.mark.parametrize("command,expected", [
    ("B\n", "back"), ("M\n", "home"), ("Q\n", "quit"),
    ("H\nB\n", "back"), ("F\nM\n", "home"),
    ("F\n1\nQ\n", "quit"),
])
def test_navigation_and_help_do_not_write(
    tmp_path: Path, command: str, expected: str,
) -> None:
    core = _failed(tmp_path)
    root = core.execution.report.plan.workspace_root
    nav, text, _ = _drive(core, command)
    assert nav == expected
    assert not (root / "scans" / "review" / "resolutions").exists()
    if command.startswith("H"):
        assert "No automatic producer retry" in text


def test_successful_core_pages_have_no_defer_selection(tmp_path: Path) -> None:
    core = _slice5._run(tmp_path)
    nav, text, _ = _drive(core, "F\n1\nDEFER\n")
    assert nav == "back"
    assert "No pages require follow-up" in text
    assert "failure_" not in text


def test_unresolved_without_verified_record_cannot_be_deferred(
    tmp_path: Path,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    batch = prepare_retained_pds2_requests(retention, decode=decode)
    core = execute_with_core_review(
        batch, approve=_slice4._approve, decode=decode,
        registry_factory=_slice4._registry,
        dispatcher=_slice4._dispatch_success,
        qualified_modules=frozenset({"scoreform", "quillan"}),
        write_failure=lambda *_: (_ for _ in ()).throw(OSError("blocked")),
    )
    assert any(row.review_state == "write_uncertain" for row in core.pages)
    nav, text, _ = _drive(core, "F\n")
    assert nav == "back"
    assert "cannot be deferred" in text or "No verified failure ID" in text
    assert "Core review write uncertain" in text
    assert not (
        core.execution.report.plan.workspace_root / "scans/review/resolutions"
    ).exists()


def test_workspace_mismatch_blocks_eligible_failure_before_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _failed(tmp_path)
    monkeypatch.setattr(
        recovery, "append_deferred_core_resolution",
        lambda *_a, **_kw: pytest.fail("unexpected Core writer"),
    )
    nav, text, heads = _drive(core, "F\n1\nDEFER\n", guard=lambda _: False)
    assert nav == "back"
    assert len(heads) == 1 and "workspace differs" in text


def test_workspace_change_at_third_confirmation_cancels(
    tmp_path: Path,
) -> None:
    core = _failed(tmp_path)
    root = core.execution.report.plan.workspace_root
    checks = 0

    def guard(_: Path) -> bool:
        nonlocal checks
        checks += 1
        return checks < 4

    _, text, _ = _drive(core, "F\n1\nDEFER\n", guard=guard)
    assert "Deferral cancelled" in text
    assert not (root / "scans/review/resolutions").exists()


def test_unknown_write_effects_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _failed(tmp_path)
    attempts = 0

    def uncertain(*_a: object, **_kw: object) -> DeferredReviewResultV1:
        nonlocal attempts
        attempts += 1
        return DeferredReviewResultV1("write_uncertain", core.pages[0].failure_id)

    monkeypatch.setattr(recovery, "append_deferred_core_resolution", uncertain)
    _, text, _ = _drive(core, "F\n1\nDEFER\nF\n1\nDEFER\n")
    assert attempts == 1
    assert "write is uncertain" in text
    assert "Do not retry" in text


def test_core_error_after_possible_write_never_reports_clean_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _failed(tmp_path)
    count = 0

    def error(*_a: object, **_kw: object) -> DeferredReviewResultV1:
        nonlocal count
        count += 1
        raise RuntimeError("PRIVATE student")

    monkeypatch.setattr(recovery, "append_deferred_core_resolution", error)
    _, text, _ = _drive(core, "F\n1\nDEFER\n")
    assert count == 1 and "may have been written" in text
    assert "PRIVATE" not in text


def test_invalid_index_does_not_call_core_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _failed(tmp_path)
    monkeypatch.setattr(
        recovery, "append_deferred_core_resolution",
        lambda *_a, **_kw: pytest.fail("invalid index reached writer"),
    )
    nav, text, _ = _drive(core, "F\n999\nDEFER\n")
    assert nav == "back"
    assert "Invalid selection" in text


def test_non_core_object_is_not_a_recovery_credential() -> None:
    with pytest.raises(TeacherCoreRecoveryError):
        _drive(object(), "F\n1\nDEFER\n")


def test_invalid_defer_callback_review_cannot_be_teacher_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _failed(tmp_path)
    seen: list[DeferDecisionV1] = []

    def untrusted(_root: Path, _id: str, *, approve):
        review = DeferredReviewV1("failure_wrong", "f" * 32)
        seen.append(approve(review))
        return DeferredReviewResultV1("cancelled", core.pages[0].failure_id)

    monkeypatch.setattr(recovery, "append_deferred_core_resolution", untrusted)
    _, _, _ = _drive(core, "F\n1\nDEFER\n")
    assert seen and seen[0].decision == "cancel"


def test_teacher_home_dispatch_result_opens_review_without_second_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_data_suite import returned_paper_teacher_dispatch_action as action
    from paper_data_suite import returned_paper_teacher_dispatch_menu as menu

    failure_root = tmp_path / "failure_case"
    failure_root.mkdir()
    core = _failed(failure_root)
    result = TeacherDispatchActionResultV1(core.execution.status, core)
    retention_root = tmp_path / "retention_case"
    retention_root.mkdir()
    retention, _, _ = _slice4._case(retention_root)
    calls: list[object] = []

    monkeypatch.setattr(
        action, "run_teacher_retained_paper_dispatch",
        lambda *_a, **_kw: calls.append("bridge") or result,
    )
    monkeypatch.setattr(
        recovery, "run_teacher_core_review_menu",
        lambda value, **_kw: calls.append(value) or "home",
    )
    output = StringIO()
    navigation = menu.run_post_retention_teacher_menu(
        retention,
        input_stream=StringIO("D\n" + str(tmp_path) + "\n"),
        output=output,
        show_header=lambda _: None,
    )
    assert navigation == "home"
    assert calls == ["bridge", core]
    assert "RETAIN" not in output.getvalue()
