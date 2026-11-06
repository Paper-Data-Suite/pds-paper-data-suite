"""Slice 45: one-shot service CAS gate and fail-closed quiescence observations."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_successor_receipt_draft import (
    WitnessBoundSuccessorDraft,
)
from paper_data_suite.evergreen_witness_cas_fence import WitnessCasFenceLedger
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    make_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceError,
    WitnessWriterQuiescenceGate,
)

NOW = datetime(2026, 10, 21, 20, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "independently-authenticated-service"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
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
        _candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old-p",
        registry_envelope=b"old-r",
        lock_envelope=b"old-l",
        native_envelope=b"old-n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=4),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        _candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"new-p",
        registry_envelope=b"new-r",
        lock_envelope=b"new-l",
        native_envelope=b"new-n",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, _sha(prior)),
    )
    draft = WitnessBoundSuccessorDraft(
        NEXT, 1, 2, _sha(prior), 1, _sha(successor), successor
    )
    request = make_witness_commit_request(
        draft,
        installation_id=INSTALL,
        witness_id=WITNESS,
        previous_receipt_bytes=prior,
    )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    calls: dict[str, int] = {"approve": 0, "transport": 0, "supervisor": 0}

    def authorize(installation: str, operation: str, context: object) -> bool:
        return installation == INSTALL and context == CONTEXT

    witness_conn = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        witness_conn, witness_id=WITNESS, authorize=authorize, sign=key.sign
    )
    store.commit_receipt(INSTALL, prior, context=CONTEXT)

    def transport(challenge: bytes) -> bytes:
        calls["transport"] += 1
        return store.answer_challenge(challenge, context=CONTEXT, now=NOW)

    def approve(candidate: WitnessCommitRequest, context: object) -> bool:
        calls["approve"] += 1
        return candidate == request and context == CONTEXT

    def supervisor(installation: str, digest: str, context: object) -> bool:
        calls["supervisor"] += 1
        return installation == INSTALL and len(digest) == 64 and context == CONTEXT

    path = tmp_path / "service.sqlite"
    connection = sqlite3.connect(path, isolation_level=None)
    ledger = WitnessCasFenceLedger(connection, authorize=authorize)
    gate = WitnessWriterQuiescenceGate(connection, ledger=ledger, authorize=authorize)
    return {
        "gate": gate,
        "ledger": ledger,
        "connection": connection,
        "path": path,
        "store": store,
        "request": request,
        "prior": prior,
        "successor": successor,
        "public": public,
        "transport": transport,
        "approve": approve,
        "authorize": authorize,
        "supervisor": supervisor,
        "calls": calls,
    }


def _admit(ready: dict[str, Any]) -> Any:
    return ready["gate"].admit(ready["request"], service_context=CONTEXT)


def _stop(ready: dict[str, Any]) -> Any:
    return ready["gate"].request_stop(ready["request"], service_context=CONTEXT)


def _dispatch(ready: dict[str, Any]) -> Any:
    return ready["gate"].dispatch_once(
        ready["request"],
        service_context=CONTEXT,
        store=ready["store"],
        independently_approve=ready["approve"],
        witness_transport=ready["transport"],
        pinned_public_key=ready["public"],
        now=NOW,
    )


def _certify(ready: dict[str, Any], **kwargs: Any) -> Any:
    args: dict[str, Any] = {
        "service_context": CONTEXT,
        "independently_verify_stopped": ready["supervisor"],
        "witness_transport": ready["transport"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["gate"].certify_stopped_and_observe(
        ready["request"], **{**args, **kwargs}
    )


def test_requires_fence_reservation_before_admission(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessWriterQuiescenceError, match="reservation"):
        _admit(ready)
    assert ready["gate"].observe(ready["request"], service_context=CONTEXT) is None


def test_admitted_requires_explicit_dispatch(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    result = _admit(ready)
    assert result.status == "ADMITTED_NOT_DISPATCHED"
    assert result.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    assert ready["calls"]["transport"] == 0
    assert not hasattr(result, "launch") and not hasattr(result, "rollback")
    with pytest.raises(WitnessWriterQuiescenceError, match="already"):
        _admit(ready)


def test_close_before_dispatch_prevents_cas_and_can_observe_prior(
    ready: dict[str, Any],
) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    stopping = _stop(ready)
    assert stopping.status == "STOP_REQUESTED_NO_DISPATCH"
    with pytest.raises(WitnessWriterQuiescenceError, match="stop requested"):
        _dispatch(ready)
    result = _certify(ready)
    assert result.status == "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"
    assert result.signed_revision == 1
    assert result.signed_head_sha256 == _sha(ready["prior"])
    assert result.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    assert _stop(ready) == result
    assert ready["calls"]["approve"] == 0


def test_dispatch_and_signed_successor_never_clear_fence(
    ready: dict[str, Any],
) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    running = _dispatch(ready)
    assert running.status == "CAS_MAY_BE_IN_FLIGHT"
    with pytest.raises(WitnessWriterQuiescenceError, match="admitted"):
        _dispatch(ready)
    assert _stop(ready).status == "STOP_REQUESTED_MAY_BE_IN_FLIGHT"
    result = _certify(ready)
    assert result.status == "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
    assert result.signed_revision == 2
    assert result.signed_head_sha256 == _sha(ready["successor"])
    assert ready["calls"]["approve"] == 1
    with pytest.raises(WitnessWriterQuiescenceError, match="stop requested"):
        _dispatch(ready)


def test_crash_before_cas_remains_marked_possibly_in_flight(
    ready: dict[str, Any],
) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    with patch.object(
        ready["ledger"], "dispatch_once", side_effect=KeyboardInterrupt("crash")
    ):
        with pytest.raises(KeyboardInterrupt, match="crash"):
            _dispatch(ready)
    observed = ready["gate"].observe(ready["request"], service_context=CONTEXT)
    assert observed is not None and observed.status == "CAS_MAY_BE_IN_FLIGHT"
    with pytest.raises(WitnessWriterQuiescenceError):
        _dispatch(ready)
    _stop(ready)
    assert _certify(ready).status == "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"


def test_supervisor_denial_keeps_stop_pending(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)
    with pytest.raises(WitnessWriterQuiescenceError, match="still be in flight"):
        _certify(ready, independently_verify_stopped=lambda *_: False)
    assert ready["calls"]["transport"] == 0
    assert _stop(ready).status == "STOP_REQUESTED_NO_DISPATCH"


def test_supervisor_exception_keeps_pending(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)

    def bad_supervisor(*args: object) -> bool:
        raise ConnectionError("service supervisor down")

    with pytest.raises(WitnessWriterQuiescenceError, match="not verified"):
        _certify(ready, independently_verify_stopped=bad_supervisor)
    assert _stop(ready).status == "STOP_REQUESTED_NO_DISPATCH"


def test_witness_outage_does_not_seal_gate(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)

    def offline(_challenge: bytes) -> bytes:
        raise ConnectionError("offline")

    with pytest.raises(WitnessWriterQuiescenceError, match="signed head unknown"):
        _certify(ready, witness_transport=offline)
    assert _stop(ready).status == "STOP_REQUESTED_NO_DISPATCH"


def test_wrong_signer_refuses_quiescence_observation(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)
    with pytest.raises(WitnessWriterQuiescenceError):
        _certify(ready, pinned_public_key=b"0" * 32)
    assert _stop(ready).status == "STOP_REQUESTED_NO_DISPATCH"


def test_certificate_before_stop_is_refused(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    with pytest.raises(WitnessWriterQuiescenceError, match="stop request"):
        _certify(ready)
    assert ready["calls"]["supervisor"] == 0


def test_service_identity_is_required_for_every_operation(
    ready: dict[str, Any],
) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    with pytest.raises(WitnessWriterQuiescenceError, match="unauthorized"):
        ready["gate"].admit(ready["request"], service_context="wrong")
    _admit(ready)
    with pytest.raises(WitnessWriterQuiescenceError, match="unauthorized"):
        ready["gate"].request_stop(ready["request"], service_context="wrong")
    with pytest.raises(WitnessWriterQuiescenceError, match="unauthorized"):
        ready["gate"].observe(ready["request"], service_context="wrong")


def test_other_request_same_installation_is_refused(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    alien = replace(ready["request"], expected_witness_revision=3)
    with pytest.raises(WitnessWriterQuiescenceError, match="corrupt or competing"):
        ready["gate"].observe(alien, service_context=CONTEXT)


def test_gate_survives_database_restart(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)
    ready["connection"].close()
    connection = sqlite3.connect(ready["path"], isolation_level=None)
    ledger = WitnessCasFenceLedger(connection, authorize=ready["authorize"])
    gate = WitnessWriterQuiescenceGate(
        connection, ledger=ledger, authorize=ready["authorize"]
    )
    state = gate.observe(ready["request"], service_context=CONTEXT)
    assert state is not None and state.status == "STOP_REQUESTED_NO_DISPATCH"
    with pytest.raises(WitnessWriterQuiescenceError):
        gate.dispatch_once(
            ready["request"],
            service_context=CONTEXT,
            store=ready["store"],
            independently_approve=ready["approve"],
            witness_transport=ready["transport"],
            pinned_public_key=ready["public"],
            now=NOW,
        )
    connection.close()


def test_corrupted_local_record_rejected(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    ready["connection"].execute(
        "UPDATE witness_writer_quiescence SET request_sha256=?",
        ("0" * 64,),
    )
    with pytest.raises(WitnessWriterQuiescenceError, match="corrupt"):
        _stop(ready)


def test_concurrent_change_during_head_read_is_refused(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)
    original = ready["transport"]

    def drift(challenge: bytes) -> bytes:
        reply = original(challenge)
        ready["connection"].execute(
            "UPDATE witness_writer_quiescence SET state=? WHERE installation_id=?",
            ("CAS_MAY_BE_IN_FLIGHT", INSTALL),
        )
        return reply

    with pytest.raises(WitnessWriterQuiescenceError, match="concurrently"):
        _certify(ready, witness_transport=drift)
    assert ready["calls"]["supervisor"] == 1


def test_requires_exact_shared_service_connection(ready: dict[str, Any]) -> None:
    other = sqlite3.connect(":memory:", isolation_level=None)
    with pytest.raises(WitnessWriterQuiescenceError, match="share"):
        WitnessWriterQuiescenceGate(
            other, ledger=ready["ledger"], authorize=ready["authorize"]
        )
    other.close()


def test_operation_never_touches_teacher_workspace_or_launch(
    ready: dict[str, Any], tmp_path: Path
) -> None:
    classroom = tmp_path / "classroom"
    classroom.mkdir()
    (classroom / "work.txt").write_text("student work")
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    _stop(ready)
    _certify(ready)
    assert (classroom / "work.txt").read_text() == "student work"
    assert ready["calls"]["approve"] == 0


def test_direct_ledger_dispatch_is_not_mislabeled_unsent(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    # This bypass is explicitly UNSUPPORTED in deployment. The gate must be
    # conservative rather than asserting that no dispatch took place.
    ready["ledger"]._claim_once(ready["request"], CONTEXT)
    assert _stop(ready).status == "STOP_REQUESTED_MAY_BE_IN_FLIGHT"
    with pytest.raises(WitnessWriterQuiescenceError):
        _dispatch(ready)


def test_failed_stop_write_keeps_gate_admitted(ready: dict[str, Any]) -> None:
    ready["ledger"].reserve(ready["request"], service_context=CONTEXT)
    _admit(ready)
    ready["connection"].execute(
        "CREATE TRIGGER prevent_stop BEFORE UPDATE ON witness_writer_quiescence "
        "BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END"
    )
    with pytest.raises(WitnessWriterQuiescenceError, match="not persisted"):
        _stop(ready)
    state = ready["gate"].observe(ready["request"], service_context=CONTEXT)
    assert state is not None and state.status == "ADMITTED_NOT_DISPATCHED"
    # A failed admission-close is *not* a quiescence claim.
    with pytest.raises(WitnessWriterQuiescenceError, match="stop request"):
        _certify(ready)
