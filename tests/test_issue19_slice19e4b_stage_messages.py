"""#19E4B: truthful synchronous stage messages, no invented progress."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_issue18_slice4_ordered_dispatch import (
    DecodedPage,
    _case,
    _dispatch_success,
    _registry,
)
from test_issue19_slice19e3b2_teacher_dispatch_action import _run, _wire

from paper_data_suite import returned_paper_teacher_dispatch_action as action
from paper_data_suite.returned_paper_core_review import execute_with_core_review


def test_success_has_ordered_observable_stages_without_fake_page_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    calls = _wire(monkeypatch, decoder)
    result, text, headers = _run(retention)
    assert result.status == "completed"
    markers = (
        "Stage: first teacher consent reported Core retention",
        "Stage: installed producer admission and active Core workspace verified",
        "Stage: 1 Core-retained page request(s) prepared",
        "Stage: second teacher consent pending",
        "Stage: second consent confirmed; handing the batch to Core",
        "Stage: Core returned; reporting verified page outcomes.",
    )
    indices = [text.index(marker) for marker in markers]
    assert indices == sorted(indices)
    assert len(headers) == 2
    assert calls.count("handler") == 1
    assert "Processing is synchronous; do not close this session." in text
    assert "Live per-page progress is unavailable." in text
    assert "Page 1 of" not in text and "100%" not in text
    assert "grade published" not in text.lower()
    assert str(tmp_path) not in text


@pytest.mark.parametrize("answer", ["", "CANCEL\n", "B\n", "M\n", "Q\n"])
def test_cancel_never_announces_handler_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    calls = _wire(monkeypatch, decoder)
    result, text, _ = _run(retention, answer)
    assert result.status == "cancelled"
    assert "second teacher consent pending" in text
    assert "second consent confirmed" not in text
    assert "Processing is synchronous" not in text
    assert "Stage: Core returned; reporting verified page outcomes." in text
    assert calls.count("audit") == 1
    assert "handler" not in calls


def test_initial_admission_refusal_reports_no_core_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    calls = _wire(monkeypatch, decoder, audits=(False,))
    result, text, headers = _run(retention)
    assert result.status == "admission_refused"
    assert "Stage: first teacher consent" in text
    assert "Stage: stopped without a verified Core dispatch result." in text
    assert "requests prepared" not in text
    assert "second teacher consent pending" not in text
    assert "Core returned" not in text
    assert calls == ["audit"] and len(headers) == 1


def test_no_qualified_routes_does_not_emit_second_consent_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decoder, _ = _case(tmp_path, ((DecodedPage(),),))
    calls = _wire(monkeypatch, decoder)
    result, text, _ = _run(retention)
    assert result.status == "no_dispatchable_pages"
    assert "installed producer admission and active Core workspace" in text
    assert "page request(s) prepared" not in text
    assert "second teacher consent pending" not in text
    assert "handing the batch" not in text
    assert "core" not in calls


def test_revoked_admission_after_consent_never_announces_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    calls = _wire(monkeypatch, decoder, audits=(True, False))
    result, text, _ = _run(retention)
    assert result.status == "admission_changed"
    assert "second teacher consent pending" in text
    assert "second consent confirmed; handing the batch" not in text
    assert "Processing is synchronous" not in text
    assert "Stage: Core returned; reporting verified page outcomes." in text
    assert "handler" not in calls


def test_preparation_exception_stops_before_dispatch_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    _wire(monkeypatch, decoder)

    def fail(_: object) -> object:
        raise RuntimeError("PRIVATE STUDENT NAME")

    monkeypatch.setattr(action, "prepare_retained_pds2_requests", fail)
    result, text, _ = _run(retention)
    assert result.status == "preparation_uncertain"
    assert "Core result unavailable" not in text
    assert "page request(s) prepared" not in text
    assert "PRIVATE" not in text
    assert "handing the batch" not in text


def test_post_approval_core_exception_is_uncertain_not_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    retention, decoder, _ = _case(tmp_path)
    _wire(monkeypatch, decoder)

    def unknown(batch: object, *, approve: object, qualified_modules: object) -> object:
        # A genuine synthetic Core handler returns before this exception.
        execute_with_core_review(
            batch, approve=approve, decode=decoder,
            registry_factory=_registry, dispatcher=_dispatch_success,
            qualified_modules=qualified_modules,
        )
        raise RuntimeError("SENSITIVE PERSISTED EVIDENCE")

    monkeypatch.setattr(action, "execute_with_core_review", unknown)
    result, text, _ = _run(retention)
    assert result.status == "uncertain"
    assert "Stage: Core result unavailable; producer effects may have occurred." in text
    assert "Stage: second consent confirmed; handing the batch to Core" in text
    assert "Core returned; reporting verified" not in text
    assert "SENSITIVE" not in text
    assert "no automatic retry is allowed" in text.lower()


def test_stage_messages_are_literal_and_never_progress_counters() -> None:
    source = Path(action.__file__).read_text(encoding="utf-8")
    assert "Stage: second consent confirmed; handing the batch to " in source
    assert "Live per-page progress is unavailable." in source
    assert "Stage: Core returned; reporting verified page outcomes." in source
    assert "execute_with_core_review(" in source
    assert "execute_prepared_paper_batch(" not in source
    assert "dispatch_routes(" not in source
    assert "authorize_and_retain_sources(" not in source
