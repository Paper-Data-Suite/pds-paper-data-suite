"""Slice 74: independently approved PLAN successor service admission only.

The service doubles simulate authorization decisions, NOT operationally
independent key custody, physical installation inspection or a live writer.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)
from paper_data_suite.evergreen_plan_service_admission import (
    IndependentServicePredecessor,
    PlanSuccessorServiceAdmissionError,
    admit_plan_successor_to_independent_service,
)
from paper_data_suite.evergreen_plan_successor_draft import PlanSuccessorDraftReview
from paper_data_suite.evergreen_witness_cas_fence import (
    WitnessCasFenceLedger,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceError,
    WitnessWriterQuiescenceGate,
)

NOW = datetime(2026, 10, 26, 22, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "authenticated-service-only-context"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        wheels,
        "3" * 64,
        "4" * 64,
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def ready(tmp_path: Path) -> dict[str, Any]:
    prior = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old-p",
        registry_envelope=b"old-r",
        lock_envelope=b"old-l",
        native_envelope=b"old-n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=4),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"new-p",
        registry_envelope=b"new-r",
        lock_envelope=b"new-l",
        native_envelope=b"new-n",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, sha(prior)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, prior, successor)
    raw = serialize_witness_commit_request(request)
    review = PlanSuccessorDraftReview(
        NEXT, INSTALL, 2, 1, 2, 1, sha(prior), sha(successor), sha(raw), raw
    )
    expected = IndependentServicePredecessor(INSTALL, WITNESS, 1, PRIOR, 1, sha(prior))
    flags: dict[str, object] = {
        "deny_operation": None,
        "approval": True,
        "expected": expected,
        "reader_error": False,
        "approve_error": False,
    }
    called = {"read": 0, "approve": 0, "authorization": 0}

    def authorize(installation: str, operation: str, context: object) -> bool:
        called["authorization"] += 1
        return (
            installation == INSTALL
            and context == CONTEXT
            and flags["deny_operation"] != operation
        )

    def read_predecessor(
        actual: WitnessCommitRequest, context: object
    ) -> IndependentServicePredecessor:
        called["read"] += 1
        if flags["reader_error"]:
            raise RuntimeError("service protected predecessor unavailable")
        assert actual == request
        assert context == CONTEXT
        return flags["expected"]  # type: ignore[return-value]

    def approve(actual: WitnessCommitRequest, context: object) -> bool:
        called["approve"] += 1
        if flags["approve_error"]:
            raise RuntimeError("operator approval infrastructure unavailable")
        return bool(flags["approval"] and actual == request and context == CONTEXT)

    file = tmp_path / "independent-service-slice74.sqlite"
    conn = sqlite3.connect(file, isolation_level=None)
    ledger = WitnessCasFenceLedger(conn, authorize=authorize)
    gate = WitnessWriterQuiescenceGate(conn, ledger=ledger, authorize=authorize)
    return dict(
        conn=conn,
        file=file,
        ledger=ledger,
        gate=gate,
        review=review,
        request=request,
        read_predecessor=read_predecessor,
        approve=approve,
        authorize=authorize,
        flags=flags,
        called=called,
    )


def admit(ready: dict[str, Any], **change: Any) -> Any:
    settings = dict(
        review=ready["review"],
        service_context=CONTEXT,
        independently_read_predecessor=ready["read_predecessor"],
        independently_approve=ready["approve"],
        ledger=ready["ledger"],
        gate=ready["gate"],
    )
    return admit_plan_successor_to_independent_service(**(settings | change))


def no_reserved_rows(ready: dict[str, Any]) -> None:
    assert ready["conn"].execute(
        "SELECT COUNT(*) FROM witness_cas_attempt_fences"
    ).fetchone() == (0,)
    assert ready["conn"].execute(
        "SELECT COUNT(*) FROM witness_writer_quiescence"
    ).fetchone() == (0,)


def test_admits_only_prepared_and_not_dispatched(ready: dict[str, Any]) -> None:
    result = admit(ready)
    assert result.installation_id == INSTALL
    assert result.transaction_id == NEXT
    assert result.request_sha256 == sha(ready["review"].serialized_request)
    assert result.predecessor_generation == 1
    assert result.successor_generation == 2
    assert result.fence_status == "PREPARED_NO_DISPATCH"
    assert result.writer_status == "ADMITTED_NOT_DISPATCHED"
    assert result.status.endswith("NO_CAS_DISPATCH")
    assert "NO_CAS_DISPATCH" in result.authority
    assert "LAUNCH" in result.authority
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
        == "PREPARED_NO_DISPATCH"
    )
    assert (
        ready["gate"].observe(ready["request"], service_context=CONTEXT).status
        == "ADMITTED_NOT_DISPATCHED"
    )
    assert ready["called"]["read"] == 1
    assert ready["called"]["approve"] == 1


def test_persistent_one_time_reservation_after_restart(ready: dict[str, Any]) -> None:
    admit(ready)
    ready["conn"].close()
    conn = sqlite3.connect(ready["file"], isolation_level=None)
    ledger = WitnessCasFenceLedger(conn, authorize=ready["authorize"])
    gate = WitnessWriterQuiescenceGate(
        conn, ledger=ledger, authorize=ready["authorize"]
    )
    assert ledger.observe(ready["request"], service_context=CONTEXT).status == (
        "PREPARED_NO_DISPATCH"
    )
    assert gate.observe(ready["request"], service_context=CONTEXT).status == (
        "ADMITTED_NOT_DISPATCHED"
    )
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, ledger=ledger, gate=gate)


def test_replay_does_not_reset_admission(ready: dict[str, Any]) -> None:
    admit(ready)
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    assert (
        ready["gate"].observe(ready["request"], service_context=CONTEXT).status
        == "ADMITTED_NOT_DISPATCHED"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_id", "d" * 32),
        ("installation_id", "d" * 32),
        ("journal_revision", 1),
        ("journal_revision", True),
        ("predecessor_generation", 7),
        ("proposed_generation", 5),
        ("witness_revision", 10),
        ("witness_revision", True),
        ("previous_receipt_sha256", "d" * 64),
        ("proposed_receipt_sha256", "d" * 64),
        ("request_sha256", "d" * 64),
        ("serialized_request", b"not canonical JSON"),
        ("status", "SERVICE_APPROVED"),
        ("authority", "CAN_COMMIT"),
        ("transaction_id", "..\\malicious"),
        ("previous_receipt_sha256", "abc"),
    ],
)
def test_forged_client_review_refused_before_service_approval(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    review = replace(ready["review"], **{field: value})
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, review=review)
    assert ready["called"]["read"] == 0
    assert ready["called"]["approve"] == 0
    no_reserved_rows(ready)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("installation_id", "d" * 32),
        ("witness_id", "other-witness"),
        ("witness_revision", 2),
        ("transaction_id", "d" * 32),
        ("generation", 99),
        ("receipt_sha256", "d" * 64),
        ("witness_revision", True),
    ],
)
def test_independent_service_predecessor_must_match(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    flags = ready["flags"]
    flags["expected"] = replace(flags["expected"], **{field: value})
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    assert ready["called"]["approve"] == 0
    no_reserved_rows(ready)


def test_service_predecessor_unavailable_refused(ready: dict[str, Any]) -> None:
    ready["flags"]["reader_error"] = True
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    no_reserved_rows(ready)


def test_service_predecessor_wrong_shape_refused(ready: dict[str, Any]) -> None:
    ready["flags"]["expected"] = "teacher forged a plausible hash"
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    no_reserved_rows(ready)


def test_missing_independent_approval_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, independently_approve=None)
    no_reserved_rows(ready)


def test_denied_independent_approval_refused(ready: dict[str, Any]) -> None:
    ready["flags"]["approval"] = False
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    no_reserved_rows(ready)


def test_error_in_independent_approval_refused(ready: dict[str, Any]) -> None:
    ready["flags"]["approve_error"] = True
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    no_reserved_rows(ready)


def test_missing_predecessor_reader_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, independently_read_predecessor=None)
    no_reserved_rows(ready)


def test_false_service_actor_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, service_context="teacher-local-context")
    no_reserved_rows(ready)


def test_reserve_denied_by_service_auth(ready: dict[str, Any]) -> None:
    ready["flags"]["deny_operation"] = "reserve"
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    no_reserved_rows(ready)


def test_same_database_and_service_ledger_required(ready: dict[str, Any]) -> None:
    other = sqlite3.connect(":memory:", isolation_level=None)
    wrong = WitnessCasFenceLedger(other, authorize=ready["authorize"])
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, ledger=wrong)
    no_reserved_rows(ready)


def test_missing_writer_gate_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready, gate=None)
    no_reserved_rows(ready)


def test_gate_failure_does_not_undo_committed_reservation(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise WitnessWriterQuiescenceError("service barrier unavailable")

    monkeypatch.setattr(ready["gate"], "admit", refused)
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
        == "PREPARED_NO_DISPATCH"
    )
    assert ready["gate"].observe(ready["request"], service_context=CONTEXT) is None
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)


def test_service_refuses_writer_admit_but_reservation_survives(
    ready: dict[str, Any],
) -> None:
    ready["flags"]["deny_operation"] = "admit"
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
        == "PREPARED_NO_DISPATCH"
    )


def test_inconsistent_fence_readback_leaves_reservation(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = ready["ledger"]
    original = ledger.observe

    def drift(*args: Any, **kwargs: Any) -> Any:
        state = original(*args, **kwargs)
        return replace(state, status="CAS_MAY_HAVE_BEEN_DISPATCHED")

    monkeypatch.setattr(ledger, "observe", drift)
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    assert ready["conn"].execute(
        "SELECT state FROM witness_cas_attempt_fences"
    ).fetchone() == ("PREPARED_NO_DISPATCH",)
    assert ready["conn"].execute(
        "SELECT COUNT(*) FROM witness_writer_quiescence"
    ).fetchone() == (0,)


def test_inconsistent_writer_readback_leaves_both_records(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = ready["gate"]
    original = gate.observe

    def drift(*args: Any, **kwargs: Any) -> Any:
        state = original(*args, **kwargs)
        return replace(state, status="STOP_REQUESTED_NO_DISPATCH")

    monkeypatch.setattr(gate, "observe", drift)
    with pytest.raises(PlanSuccessorServiceAdmissionError):
        admit(ready)
    assert ready["conn"].execute(
        "SELECT state FROM witness_cas_attempt_fences"
    ).fetchone() == ("PREPARED_NO_DISPATCH",)
    assert ready["conn"].execute(
        "SELECT state FROM witness_writer_quiescence"
    ).fetchone() == ("ADMITTED_NOT_DISPATCHED",)


def test_no_commit_dispatch_or_local_file_mutation(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sentinel = tmp_path / "classroom" / "untouched.bin"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"student work must not be touched")

    def cannot_dispatch(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("CAS DISPATCH MUST NOT OCCUR IN SLICE 74")

    monkeypatch.setattr(ready["ledger"], "dispatch_once", cannot_dispatch)
    monkeypatch.setattr(ready["gate"], "dispatch_once", cannot_dispatch)
    admit(ready)
    assert sentinel.read_bytes() == b"student work must not be touched"


def test_after_admission_writer_gate_cannot_admit_second_time(
    ready: dict[str, Any],
) -> None:
    admit(ready)
    with pytest.raises(WitnessWriterQuiescenceError):
        ready["gate"].admit(ready["request"], service_context=CONTEXT)
