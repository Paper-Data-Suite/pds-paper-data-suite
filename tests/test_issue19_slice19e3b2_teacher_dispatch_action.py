"""#19E3B2: real #18 review + second consent + ephemeral installed admission."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest

from paper_data_suite import returned_paper_teacher_dispatch_action as action
from paper_data_suite.returned_paper_core_review import execute_with_core_review
from paper_data_suite.returned_paper_live_admission import LivePaperAdmissionV1
from paper_data_suite.returned_paper_retained_requests import (
    prepare_retained_pds2_requests,
)
from paper_data_suite.returned_paper_teacher_dispatch_action import (
    TeacherDispatchActionError,
    TeacherDispatchActionResultV1,
    render_teacher_dispatch_action,
    run_teacher_retained_paper_dispatch,
)

# Reuse the real #18 Core retention, typed requests and registry fixtures.
_slice4 = import_module("test_issue18_slice4_ordered_dispatch")


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    decoder: object,
    *,
    audits: tuple[bool, ...] = (True, True),
    workspace_ok: bool = True,
) -> list[str]:
    observed: list[str] = []

    def inspect(_: Path) -> LivePaperAdmissionV1:
        index = sum(value == "audit" for value in observed)
        observed.append("audit")
        accepted = audits[min(index, len(audits) - 1)]
        return (
            LivePaperAdmissionV1(
                "admitted", frozenset({"scoreform", "quillan"})
            ) if accepted else LivePaperAdmissionV1("audit_refused")
        )

    def prepare(retention):
        observed.append("prepare")
        return prepare_retained_pds2_requests(retention, decode=decoder)

    def core(batch, *, approve, qualified_modules):
        observed.append("core")
        assert qualified_modules == frozenset({"scoreform", "quillan"})

        def dispatch(root, registry, requests):
            observed.append("handler")
            return _slice4._dispatch_success(root, registry, requests)

        return execute_with_core_review(
            batch, approve=approve, decode=decoder,
            registry_factory=_slice4._registry, dispatcher=dispatch,
            qualified_modules=qualified_modules,
        )

    monkeypatch.setattr(action, "inspect_live_paper_admission", inspect)
    monkeypatch.setattr(
        action, "_active_core_workspace_matches", lambda _: workspace_ok
    )
    monkeypatch.setattr(action, "prepare_retained_pds2_requests", prepare)
    monkeypatch.setattr(action, "execute_with_core_review", core)
    return observed


def _run(retention, answer: str = "DISPATCH\n"):
    out = StringIO()
    headers: list[str] = []
    result = run_teacher_retained_paper_dispatch(
        retention, Path("/synthetic/explicit-wheelhouse"),
        input_stream=StringIO(answer), output=out,
        show_header=headers.append,
    )
    return result, out.getvalue(), headers


def test_genuine_second_consent_executes_one_core_operation_per_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode)
    result, display, headers = _run(retention)
    assert result.status == "completed"
    assert result.core_review is not None
    assert result.core_review.execution.attempted_pages == 1
    assert calls.count("audit") == 2
    assert calls.count("prepare") == calls.count("core") == 1
    assert calls.count("handler") == 1
    assert len(headers) == 2
    assert "Second Teacher Consent" in headers[0]
    assert "Core Processing Result" in headers[1]
    assert "unresolved_qr: 1" in display
    assert "handler_returned: 1" in display
    assert "Core review" in display
    assert "NOT confirmed evidence capture" in display
    assert str(tmp_path) not in display
    assert "PDS2|" not in display


@pytest.mark.parametrize("answer", ["", "CANCEL\n", "B\n", "M\n", "Q\n"])
def test_cancel_never_imports_registry_or_invokes_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode)
    result, display, _ = _run(retention, answer)
    assert result.status == "cancelled"
    assert result.core_review is not None
    assert result.core_review.execution.attempted_pages == 0
    assert "handler" not in calls
    assert calls.count("audit") == 1
    assert "Core action: cancelled" in display


def test_initial_refusal_never_prepares_or_asks_second_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode, audits=(False,))
    result, display, headers = _run(retention)
    assert result.status == "admission_refused"
    assert calls == ["audit"]
    assert len(headers) == 1
    assert "No producer handler was authorized" in display


def test_active_workspace_refusal_prevents_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode, workspace_ok=False)
    result, _, headers = _run(retention)
    assert result.status == "workspace_refused"
    assert calls == ["audit"]
    assert len(headers) == 1


def test_recheck_after_dispatch_consent_cancels_without_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode, audits=(True, False))
    result, output, headers = _run(retention)
    assert result.status == "admission_changed"
    assert result.core_review is not None
    assert result.core_review.execution.status == "cancelled"
    assert result.core_review.execution.attempted_pages == 0
    assert calls.count("audit") == 2
    assert "handler" not in calls
    assert len(headers) == 2
    assert "Action status: admission_changed" in output


def test_no_requests_requires_no_second_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(
        tmp_path, ((_slice4.DecodedPage(),),)
    )
    calls = _wire(monkeypatch, decode)
    result, _, headers = _run(retention)
    assert result.status == "no_dispatchable_pages"
    assert "core" not in calls and "handler" not in calls
    assert len(headers) == 1


def test_preparation_exception_never_exposes_secret_or_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode)

    def bad(_: object) -> object:
        raise RuntimeError("SENSITIVE STUDENT NAME")

    monkeypatch.setattr(action, "prepare_retained_pds2_requests", bad)
    result, display, _ = _run(retention)
    assert result.status == "preparation_uncertain"
    assert "SENSITIVE" not in display
    assert "core" not in calls


def test_core_mutation_before_consent_blocks_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode)

    def tamper(retention):
        batch = prepare_retained_pds2_requests(retention, decode=decode)
        receipt = batch.report.sources[0].retained_source
        assert receipt is not None
        receipt.retained_source_path.write_bytes(b"%PDF-1.4\n% tampered\n")
        return batch

    monkeypatch.setattr(action, "prepare_retained_pds2_requests", tamper)
    result, display, headers = _run(retention)
    assert result.status == "blocked"
    assert result.core_review is not None
    assert result.core_review.execution.attempted_pages == 0
    assert calls.count("audit") == 1
    assert "handler" not in calls
    assert len(headers) == 1
    assert "Review incomplete or uncertain" in display


def test_unsupported_module_is_reported_as_partial_without_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(
        tmp_path, ((
            _slice4.DecodedPage((_slice4._code("scoreform", "route_001"),)),
            _slice4.DecodedPage((_slice4._code("portia", "route_002"),)),
            _slice4.DecodedPage((_slice4._code("quillan", "route_003"),)),
        ),)
    )
    calls = _wire(monkeypatch, decode)
    result, display, _ = _run(retention)
    assert result.status == "partial"
    assert result.core_review is not None
    assert result.core_review.execution.attempted_pages == 2
    assert calls.count("handler") == 2
    assert "module_unqualified: 1" in display
    assert "handler_returned: 2" in display


def test_dispatch_exception_is_uncertain_not_safe_to_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decode, _ = _slice4._case(tmp_path)
    calls = _wire(monkeypatch, decode)

    def unknown(*_: object, **__: object) -> object:
        raise RuntimeError("PRODUCER MAY HAVE WRITTEN")

    monkeypatch.setattr(action, "execute_with_core_review", unknown)
    result, display, _ = _run(retention)
    assert result.status == "uncertain"
    assert result.core_review is None
    assert "Effects may have occurred" in display
    assert "PRODUCER MAY" not in display
    assert result.automatic_retry_allowed is False
    assert "prepare" in calls


def test_invalid_retention_refused_before_any_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(monkeypatch, None)
    with pytest.raises(TeacherDispatchActionError):
        run_teacher_retained_paper_dispatch(
            object(), Path("/wheels"),  # type: ignore[arg-type]
            input_stream=StringIO("DISPATCH\n"), output=StringIO(),
            show_header=lambda _: None,
        )
    assert calls == []


def test_result_cannot_claim_grade_or_invent_core_execution() -> None:
    with pytest.raises(TeacherDispatchActionError):
        TeacherDispatchActionResultV1("completed")
    with pytest.raises(TeacherDispatchActionError):
        TeacherDispatchActionResultV1("partial")
    with pytest.raises(TeacherDispatchActionError):
        TeacherDispatchActionResultV1(  # type: ignore[arg-type]
            "admission_refused", grades_published=True
        )
    result = TeacherDispatchActionResultV1("admission_refused")
    with pytest.raises(FrozenInstanceError):
        result.status = "completed"  # type: ignore[misc]
    with pytest.raises(TeacherDispatchActionError):
        replace(result, automatic_retry_allowed=True)  # type: ignore[arg-type]
    assert "No grade publication" in render_teacher_dispatch_action(result)


def test_no_direct_route_dispatch_or_cached_eligibility() -> None:
    source = Path(action.__file__).read_text(encoding="utf-8")
    assert "execute_prepared_paper_batch(" not in source
    assert "dispatch_routes(" not in source
    assert "authorize_and_retain_sources(" not in source
    assert "qualified_modules=_ALLOWED" in source
    assert "if not _currently_admitted(wheelhouse)" in source
    assert "# Reinspect actual installed payload" in source
