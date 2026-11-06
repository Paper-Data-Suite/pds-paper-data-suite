"""Slice 75: one service-side plan CAS attempt and signed recovery, no launch.

All approval/supervisor functions here are test doubles. They do not prove
separate administration, real physical installation or global OS writer fencing.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_plan_service_admission import (
    IndependentServicePredecessor,
    admit_plan_successor_to_independent_service,
)
from paper_data_suite.evergreen_plan_service_dispatch import (
    PlanSuccessorServiceDispatchError,
    dispatch_admitted_plan_successor_once,
    reconcile_admitted_plan_successor_signed_head,
)
from paper_data_suite.evergreen_plan_successor_draft import PlanSuccessorDraftReview
from paper_data_suite.evergreen_witness_cas_fence import (
    WitnessCasFenceError,
    WitnessCasFenceLedger,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceGate,
)

NOW = datetime(2026, 10, 26, 22, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "service-protected-context"


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
    predecessor = make_untrusted_active_receipt(
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
        previous=ExternallyPinnedReceiptHead(1, sha(predecessor)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, predecessor, successor)
    raw = serialize_witness_commit_request(request)
    review = PlanSuccessorDraftReview(
        NEXT,
        INSTALL,
        2,
        1,
        2,
        1,
        sha(predecessor),
        sha(successor),
        sha(raw),
        raw,
    )
    expected = IndependentServicePredecessor(
        INSTALL, WITNESS, 1, PRIOR, 1, sha(predecessor)
    )
    flags: dict[str, Any] = {
        "approve": True,
        "expected": expected,
        "deny": None,
        "supervisor": True,
        "reader_error": False,
    }
    calls: dict[str, int] = {"approve": 0, "reader": 0, "transport": 0, "supervisor": 0}

    def authorize(installation: str, operation: str, context: object) -> bool:
        return (
            installation == INSTALL
            and context == CONTEXT
            and operation != flags["deny"]
        )

    def read_predecessor(
        value: WitnessCommitRequest, context: object
    ) -> IndependentServicePredecessor:
        calls["reader"] += 1
        if flags["reader_error"]:
            raise RuntimeError("service expected predecessor inaccessible")
        assert value == request and context == CONTEXT
        return flags["expected"]

    def approve(value: WitnessCommitRequest, context: object) -> bool:
        calls["approve"] += 1
        return bool(flags["approve"] and value == request and context == CONTEXT)

    def supervisor(installation: str, digest: str, context: object) -> bool:
        calls["supervisor"] += 1
        assert installation == INSTALL and digest == sha(raw) and context == CONTEXT
        return bool(flags["supervisor"])

    signing = Ed25519PrivateKey.generate()
    public = signing.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    witness_db = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        witness_db, witness_id=WITNESS, authorize=authorize, sign=signing.sign
    )
    store.commit_receipt(INSTALL, predecessor, context=CONTEXT)

    def transport(challenge: bytes) -> bytes:
        calls["transport"] += 1
        return store.answer_challenge(challenge, context=CONTEXT, now=NOW)

    file = tmp_path / "external-cas-guard.sqlite"
    connection = sqlite3.connect(file, isolation_level=None)
    ledger = WitnessCasFenceLedger(connection, authorize=authorize)
    gate = WitnessWriterQuiescenceGate(connection, ledger=ledger, authorize=authorize)
    admission = admit_plan_successor_to_independent_service(
        review,
        service_context=CONTEXT,
        independently_read_predecessor=read_predecessor,
        independently_approve=approve,
        ledger=ledger,
        gate=gate,
    )
    return dict(
        admission=admission,
        review=review,
        request=request,
        flags=flags,
        calls=calls,
        ledger=ledger,
        gate=gate,
        connection=connection,
        file=file,
        store=store,
        public=public,
        transport=transport,
        supervisor=supervisor,
        approve=approve,
        read_predecessor=read_predecessor,
        authorize=authorize,
    )


def dispatch(ready: dict[str, Any], **override: Any) -> Any:
    args: dict[str, Any] = dict(
        review=ready["review"],
        admission=ready["admission"],
        service_context=CONTEXT,
        independently_read_predecessor=ready["read_predecessor"],
        independently_approve=ready["approve"],
        ledger=ready["ledger"],
        gate=ready["gate"],
        store=ready["store"],
        witness_transport=ready["transport"],
        pinned_public_key=ready["public"],
        now=NOW,
    )
    return dispatch_admitted_plan_successor_once(**(args | override))


def reconcile(ready: dict[str, Any], **override: Any) -> Any:
    args: dict[str, Any] = dict(
        review=ready["review"],
        admission=ready["admission"],
        service_context=CONTEXT,
        ledger=ready["ledger"],
        gate=ready["gate"],
        independently_verify_stopped=ready["supervisor"],
        witness_transport=ready["transport"],
        pinned_public_key=ready["public"],
        now=NOW,
    )
    return reconcile_admitted_plan_successor_signed_head(**(args | override))


def states(ready: dict[str, Any]) -> tuple[str, str]:
    request = ready["request"]
    return (
        ready["ledger"].observe(request, service_context=CONTEXT).status,
        ready["gate"].observe(request, service_context=CONTEXT).status,
    )


def test_one_authenticated_call_marks_both_durable_states(
    ready: dict[str, Any],
) -> None:
    result = dispatch(ready)
    assert result.installation_id == INSTALL
    assert result.transaction_id == NEXT
    assert result.request_sha256 == sha(ready["review"].serialized_request)
    assert result.status == "SERVICE_CAS_RETURNED_SIGNED_READBACK_AND_RECOVERY_REQUIRED"
    assert result.authority.startswith("NO_RETRY_ROLLBACK")
    assert states(ready) == ("CAS_MAY_HAVE_BEEN_DISPATCHED", "CAS_MAY_BE_IN_FLIGHT")
    assert ready["calls"]["approve"] == 3  # admission, dispatch precheck, CAS
    assert ready["calls"]["transport"] >= 1


def test_signed_successor_requires_forward_recovery(ready: dict[str, Any]) -> None:
    dispatch(ready)
    observed = reconcile(ready)
    assert observed.signed_receipt_sha256 == ready["request"].successor_sha256
    assert observed.witness_revision == 2
    assert observed.status == "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"
    assert observed.fence_status == "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"
    assert observed.writer_status == (
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
    )
    assert "LAUNCH" in observed.authority
    assert ready["calls"]["supervisor"] == 1
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    repeat = reconcile(ready)
    assert repeat.status == observed.status
    assert repeat.signed_receipt_sha256 == observed.signed_receipt_sha256


def test_replay_refused_after_service_cas_return(ready: dict[str, Any]) -> None:
    dispatch(ready)
    approval_calls = ready["calls"]["approve"]
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    assert ready["calls"]["approve"] == approval_calls
    assert states(ready) == ("CAS_MAY_HAVE_BEEN_DISPATCHED", "CAS_MAY_BE_IN_FLIGHT")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("installation_id", "d" * 32),
        ("transaction_id", "d" * 32),
        ("predecessor_sha256", "e" * 64),
        ("successor_sha256", "e" * 64),
        ("request_sha256", "e" * 64),
        ("predecessor_generation", True),
        ("successor_generation", 22),
        ("expected_witness_revision", 3),
        ("fence_status", "CAS_MAY_HAVE_BEEN_DISPATCHED"),
        ("writer_status", "CAS_MAY_BE_IN_FLIGHT"),
        ("status", "CAN_DISPATCH"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_forged_admission_not_a_bearer_credential(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    changed = replace(ready["admission"], **{field: value})
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready, admission=changed)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_id", "d" * 32),
        ("request_sha256", "f" * 64),
        ("serialized_request", b"forged"),
        ("status", "APPROVED"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_forged_draft_refused(ready: dict[str, Any], field: str, value: Any) -> None:
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready, review=replace(ready["review"], **{field: value}))
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_mismatched_protected_predecessor_refused(ready: dict[str, Any]) -> None:
    ready["flags"]["expected"] = replace(
        ready["flags"]["expected"], receipt_sha256="f" * 64
    )
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_missing_reader_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready, independently_read_predecessor=None)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_approval_revoked_between_admission_and_dispatch(ready: dict[str, Any]) -> None:
    ready["flags"]["approve"] = False
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_context", "client-supplied-user"),
        ("independently_approve", None),
        ("ledger", None),
        ("gate", None),
        ("store", None),
        ("pinned_public_key", b"f" * 31),
        ("pinned_public_key", "forged"),
        ("witness_transport", None),
        ("now", datetime(2026, 10, 26)),
    ],
)
def test_service_boundary_preflight_rejects_invalid_inputs(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready, **{field: value})
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_no_dispatch_without_exact_service_writer_admission(
    ready: dict[str, Any],
) -> None:
    ready["gate"].request_stop(ready["request"], service_context=CONTEXT)
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "STOP_REQUESTED_NO_DISPATCH")


def test_failed_ledger_during_dispatch_keeps_gate_possible_inflight(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(*args: Any, **kwargs: Any) -> None:
        raise WitnessCasFenceError("service CAS unavailable")

    monkeypatch.setattr(ready["ledger"], "dispatch_once", offline)
    with pytest.raises(PlanSuccessorServiceDispatchError, match="no retry"):
        dispatch(ready)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "CAS_MAY_BE_IN_FLIGHT")
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    observed = reconcile(ready)
    assert observed.fence_status == "PREPARED_NO_DISPATCH"
    assert observed.status == "SIGNED_PRIOR_UNRESOLVED_NO_ROLLBACK_GRANT"
    assert observed.writer_status == (
        "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"
    )


def test_lost_ack_after_real_cas_stays_fenced_and_recovers_forward(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ready["ledger"].dispatch_once

    def lost_ack(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise WitnessCasFenceError("commit returned but ACK disappeared")

    monkeypatch.setattr(ready["ledger"], "dispatch_once", lost_ack)
    with pytest.raises(PlanSuccessorServiceDispatchError, match="no retry"):
        dispatch(ready)
    assert states(ready) == ("CAS_MAY_HAVE_BEEN_DISPATCHED", "CAS_MAY_BE_IN_FLIGHT")
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    observed = reconcile(ready)
    assert observed.status == "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"
    assert observed.fence_status == "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"


def test_service_writer_supervisor_does_not_authorize_rollback(
    ready: dict[str, Any],
) -> None:
    dispatch(ready)
    ready["flags"]["supervisor"] = False
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready)
    assert states(ready) == (
        "CAS_MAY_HAVE_BEEN_DISPATCHED",
        "STOP_REQUESTED_MAY_BE_IN_FLIGHT",
    )
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    ready["flags"]["supervisor"] = True
    observed = reconcile(ready)
    assert observed.status == "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"


def test_fake_service_certificate_refuses_readback_and_stays_fenced(
    ready: dict[str, Any],
) -> None:
    dispatch(ready)
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready, pinned_public_key=b"z" * 32)
    assert states(ready) == (
        "CAS_MAY_HAVE_BEEN_DISPATCHED",
        "STOP_REQUESTED_MAY_BE_IN_FLIGHT",
    )


def test_service_witness_outage_keeps_stop_requested(ready: dict[str, Any]) -> None:
    dispatch(ready)

    def down(challenge: bytes) -> bytes:
        raise ConnectionError("remote witness unavailable")

    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready, witness_transport=down)
    assert states(ready) == (
        "CAS_MAY_HAVE_BEEN_DISPATCHED",
        "STOP_REQUESTED_MAY_BE_IN_FLIGHT",
    )


def test_gate_admission_refusal_stops_before_physical_commit(
    ready: dict[str, Any],
) -> None:
    ready["flags"]["deny"] = "dispatch"
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_persistent_possible_dispatch_after_service_restart(
    ready: dict[str, Any],
) -> None:
    dispatch(ready)
    ready["connection"].close()
    conn = sqlite3.connect(ready["file"], isolation_level=None)
    ledger = WitnessCasFenceLedger(conn, authorize=ready["authorize"])
    gate = WitnessWriterQuiescenceGate(
        conn, ledger=ledger, authorize=ready["authorize"]
    )
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready, ledger=ledger, gate=gate)
    observed = reconcile(ready, ledger=ledger, gate=gate)
    assert observed.status == "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"


def test_protected_service_state_cannot_be_replaced_by_other_ledger(
    ready: dict[str, Any],
) -> None:
    other = sqlite3.connect(":memory:", isolation_level=None)
    foreign = WitnessCasFenceLedger(other, authorize=ready["authorize"])
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready, ledger=foreign)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_before_possible_dispatch_reconciliation_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready)
    assert states(ready) == ("PREPARED_NO_DISPATCH", "ADMITTED_NOT_DISPATCHED")


def test_no_classroom_workspace_mutation(ready: dict[str, Any], tmp_path: Path) -> None:
    classroom = tmp_path / "classroom" / "record.bin"
    classroom.parent.mkdir()
    classroom.write_bytes(b"private learner writing, unchanged")
    dispatch(ready)
    reconcile(ready)
    assert classroom.read_bytes() == b"private learner writing, unchanged"


def test_signed_recovery_resumes_read_only_after_fence_observation_outage(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatch(ready)
    original = ready["ledger"].inspect_signed_head

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise WitnessCasFenceError("signed service read temporarily unavailable")

    monkeypatch.setattr(ready["ledger"], "inspect_signed_head", unavailable)
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready)
    assert states(ready) == (
        "CAS_MAY_HAVE_BEEN_DISPATCHED",
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
    )
    monkeypatch.setattr(ready["ledger"], "inspect_signed_head", original)
    resumed = reconcile(ready)
    assert resumed.status == "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"
    assert resumed.fence_status == "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"
    with pytest.raises(PlanSuccessorServiceDispatchError):
        dispatch(ready)


def test_read_only_terminal_observation_rechecks_supervisor(
    ready: dict[str, Any],
) -> None:
    dispatch(ready)
    reconcile(ready)
    ready["flags"]["supervisor"] = False
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready)
    assert states(ready) == (
        "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED",
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
    )


def test_reconciliation_refuses_unknown_service_identity(ready: dict[str, Any]) -> None:
    dispatch(ready)
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready, service_context="unauthenticated-user")
    assert states(ready) == ("CAS_MAY_HAVE_BEEN_DISPATCHED", "CAS_MAY_BE_IN_FLIGHT")


def test_reconciliation_rejects_forged_review_without_mutation(
    ready: dict[str, Any],
) -> None:
    dispatch(ready)
    changed = replace(ready["review"], request_sha256="f" * 64)
    with pytest.raises(PlanSuccessorServiceDispatchError):
        reconcile(ready, review=changed)
    assert states(ready) == ("CAS_MAY_HAVE_BEEN_DISPATCHED", "CAS_MAY_BE_IN_FLIGHT")
