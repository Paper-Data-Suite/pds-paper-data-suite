"""#19G2A: fail-closed returned-paper UI, admission, recovery and privacy matrix.

No real teacher data, native producer handler or network operation is involved.
The existing #18 fixtures are Core-owned retained receipts, not fake successes.
"""

from __future__ import annotations

import hashlib
import sys
from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest
from pds_core.route_registrations import RouteRegistrationNotFoundError

from paper_data_suite import returned_paper_live_admission as policy
from paper_data_suite import returned_paper_teacher_dispatch_action as action
from paper_data_suite.returned_paper_live_admission import inspect_live_paper_admission
from paper_data_suite.returned_paper_teacher_dispatch_action import (
    run_teacher_retained_paper_dispatch,
)
from paper_data_suite.returned_paper_teacher_dispatch_menu import (
    run_post_retention_teacher_menu,
)
from paper_data_suite.returned_paper_teacher_preparation import (
    render_manual_only_followup,
)
from paper_data_suite.returned_paper_teacher_results import render_core_paper_results

_slice4 = import_module("test_issue18_slice4_ordered_dispatch")
_slice5 = import_module("test_issue18_slice5_core_review")
_f2 = import_module("test_issue19_slice19f2_manual_only_unresolved")
_menu = import_module("test_issue19_slice19e3b3_teacher_dispatch_menu")
_actiontests = import_module("test_issue19_slice19e3b2_teacher_dispatch_action")


def _files(root: Path) -> dict[str, str]:
    """Evidence-only fingerprint; never print any contents or private paths."""
    return {
        item.relative_to(root).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in root.rglob("*") if item.is_file()
    }


@pytest.mark.skipif(sys.platform == "win32", reason="actual non-Windows host only")
def test_actual_linux_host_cannot_admit_producer_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a real non-Windows CI host, admission must stop before disk audit."""
    def forbidden(_wheelhouse: Path) -> object:
        pytest.fail("unsupported host attempted installed producer audit")

    monkeypatch.setattr(policy, "inspect_paper_action_time_readiness", forbidden)
    decision = inspect_live_paper_admission(tmp_path)
    assert decision.status == "unsupported_runtime"
    assert decision.qualified_modules == frozenset()
    assert decision.can_skip_second_consent is False
    assert decision.source_retention_authorized is False


@pytest.mark.parametrize("barrier", ["unsupported_host", "missing_wheelhouse"])
def test_real_dispatch_bridge_denies_before_any_preparation_or_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barrier: str,
) -> None:
    receipt, _decode, _ = _slice4._case(tmp_path)
    root = receipt.report.plan.workspace_root
    before = _files(root)
    if barrier == "unsupported_host":
        monkeypatch.setattr(policy, "_action_host_supported", lambda: False)
        wheelhouse = tmp_path
    else:
        monkeypatch.setattr(policy, "_action_host_supported", lambda: True)
        wheelhouse = tmp_path / "nonexistent_wheelhouse"
    monkeypatch.setattr(
        policy, "inspect_paper_action_time_readiness",
        lambda _: pytest.fail("unqualified wheelhouse reached actual audit"),
    )
    monkeypatch.setattr(
        action, "prepare_retained_pds2_requests",
        lambda _: pytest.fail("unqualified environment prepared requests"),
    )
    monkeypatch.setattr(
        action, "execute_with_core_review",
        lambda *_a, **_k: pytest.fail("unqualified environment dispatched"),
    )
    output = StringIO()
    result = run_teacher_retained_paper_dispatch(
        receipt, wheelhouse, input_stream=StringIO("DISPATCH\n"), output=output,
        show_header=lambda _: None,
    )
    text = output.getvalue()
    assert result.status == "admission_refused" and result.core_review is None
    assert result.automatic_retry_allowed is False
    assert result.grades_published is False
    assert "Second Teacher Consent" not in text
    assert "No producer handler was authorized" in text
    assert "PDS2|" not in text and str(tmp_path) not in text
    assert _files(root) == before


@pytest.mark.parametrize("reply", [
    "DISPATCH\x00\n", "DISPATCH " * 12 + "\n", "RETAIN\n",
    "APPROVE\n", "CANCEL\n", "\n",
])
def test_malformed_second_consent_cannot_attempt_a_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str,
) -> None:
    receipt, decode, _ = _slice4._case(tmp_path)
    events = _actiontests._wire(monkeypatch, decode)
    output = StringIO()
    result = run_teacher_retained_paper_dispatch(
        receipt, tmp_path / "wheels", input_stream=StringIO(reply),
        output=output, show_header=lambda _: None,
    )
    assert result.status == "cancelled"
    assert result.core_review is not None
    assert result.core_review.execution.attempted_pages == 0
    assert "handler" not in events
    assert events.count("core") == 1
    assert "Core attempted physical pages: 0" in output.getvalue()
    assert "PDS2|" not in output.getvalue()


def test_manual_only_foreign_and_ambiguous_qr_have_no_failure_id_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, decode, _ = _f2._unroutable(tmp_path)
    batch = _f2.prepare_retained_pds2_requests(receipt, decode=decode)
    manual = render_manual_only_followup(batch)
    assert batch.candidates == () and batch.status == "no_dispatchable_pages"
    assert "Selected unresolved physical pages: 3" in manual
    assert "DEFER is unavailable" in manual
    assert "failure_" not in manual and "PRIVATE_STUDENT" not in manual
    assert "PDS2|" not in manual and str(tmp_path) not in manual
    events = _actiontests._wire(monkeypatch, decode)
    output = StringIO()
    result = run_teacher_retained_paper_dispatch(
        receipt, tmp_path / "wheels", input_stream=StringIO("DISPATCH\n"),
        output=output, show_header=lambda _: None,
    )
    assert result.status == "no_dispatchable_pages"
    assert result.core_review is None
    assert events == ["audit", "prepare"]
    assert "Second Teacher Consent" not in output.getvalue()
    resolutions = receipt.report.plan.workspace_root / "scans/review/resolutions"
    assert not resolutions.exists()


def test_unknown_producer_failure_cannot_leak_or_auto_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _menu._retained(tmp_path)
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    calls: list[int] = []
    private = "SENSITIVE_STUDENT_X PDS2|SECRET C:/private/student"

    def failing(*_args: object, **_kwargs: object) -> None:
        calls.append(1)
        raise RuntimeError(private)

    monkeypatch.setattr(action, "run_teacher_retained_paper_dispatch", failing)
    output = StringIO()
    nav = run_post_retention_teacher_menu(
        receipt,
        input_stream=StringIO(f"D\n{wheelhouse}\nD\n{wheelhouse}\n"),
        output=output, show_header=lambda _: None,
    )
    text = output.getvalue()
    assert nav == "back"
    assert calls == [1]
    assert "effects MAY have occurred" in text
    assert "Do not retry" in text
    assert "SENSITIVE_STUDENT_X" not in text
    assert "PDS2|" not in text and str(wheelhouse) not in text
    resolutions = receipt.report.plan.workspace_root / "scans/review/resolutions"
    assert not resolutions.exists()


def test_core_failure_review_never_turns_handler_return_into_grade(
    tmp_path: Path,
) -> None:
    private = "PRIVATE_STUDENT_X PDS2|SECRET C:/private/student"
    failed = _slice5._run(
        tmp_path, dispatcher=_slice5._failure_dispatch(
            RouteRegistrationNotFoundError(private),
        ),
    )
    visible = render_core_paper_results(failed)
    assert "No grade publication" in visible
    assert "automatic" in visible.lower() or "replay" in visible.lower()
    assert "PRIVATE_STUDENT_X" not in visible and "PDS2|" not in visible
    assert str(tmp_path) not in visible
    page_states = visible.lower().split("page outcomes:", 1)[-1].split(
        "independent core", 1
    )[0]
    assert "handler returned" not in page_states
