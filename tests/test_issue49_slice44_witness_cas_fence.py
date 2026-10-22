"""Slice 44: durable one-attempt CAS fence; signed readback never grants rollback."""

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
from paper_data_suite.evergreen_witness_cas_fence import (
    WitnessCasFenceError,
    WitnessCasFenceLedger,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    commit_independently_approved_successor,
    make_witness_commit_request,
)

NOW = datetime(2026, 10, 21, 20, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "service-authorized-context"


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
    calls = {"authorize": 0, "approve": 0, "transport": 0}

    def authorize(installation: str, operation: str, context: object) -> bool:
        calls["authorize"] += 1
        return installation == INSTALL and context == CONTEXT

    witness_connection = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        witness_connection, witness_id=WITNESS, authorize=authorize, sign=key.sign
    )
    store.commit_receipt(INSTALL, prior, context=CONTEXT)

    def transport(challenge: bytes) -> bytes:
        calls["transport"] += 1
        return store.answer_challenge(challenge, context=CONTEXT, now=NOW)

    def approve(candidate: WitnessCommitRequest, context: object) -> bool:
        calls["approve"] += 1
        return candidate == request and context == CONTEXT

    db_path = tmp_path / "independent-service-fence.sqlite"
    connection = sqlite3.connect(db_path, isolation_level=None)
    ledger = WitnessCasFenceLedger(connection, authorize=authorize)
    return {
        "ledger": ledger,
        "connection": connection,
        "db_path": db_path,
        "store": store,
        "request": request,
        "prior": prior,
        "successor": successor,
        "public": public,
        "transport": transport,
        "approve": approve,
        "authorize": authorize,
        "calls": calls,
    }


def _reserve(ready: dict[str, Any]) -> Any:
    return ready["ledger"].reserve(ready["request"], service_context=CONTEXT)


def _dispatch(ready: dict[str, Any], **changes: Any) -> Any:
    args = {
        "service_context": CONTEXT,
        "store": ready["store"],
        "independently_approve": ready["approve"],
        "witness_transport": ready["transport"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["ledger"].dispatch_once(ready["request"], **{**args, **changes})


def _inspect(ready: dict[str, Any], **changes: Any) -> Any:
    args = {
        "service_context": CONTEXT,
        "witness_transport": ready["transport"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["ledger"].inspect_signed_head(ready["request"], **{**args, **changes})


def test_reservation_is_service_only_and_not_launch_authority(
    ready: dict[str, Any],
) -> None:
    state = _reserve(ready)
    assert state.status == "PREPARED_NO_DISPATCH"
    assert state.authority == "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
    assert state.successor_sha256 == _sha(ready["successor"])
    assert state.witnessed_revision is None
    assert ready["calls"]["transport"] == 0
    assert not hasattr(state, "launch") and not hasattr(state, "rollback")


def test_dispatch_records_uncertainty_then_signed_successor(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    pending = _dispatch(ready)
    assert pending.status == "CAS_MAY_HAVE_BEEN_DISPATCHED"
    assert pending.witnessed_revision is None
    observed = _inspect(ready)
    assert observed.status == "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"
    assert observed.witnessed_revision == 2
    assert observed.witnessed_receipt_sha256 == _sha(ready["successor"])
    assert observed.authority == "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT) == observed
    )
    assert ready["calls"]["approve"] == 1


def test_no_second_dispatch_even_after_signed_confirmation(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    _dispatch(ready)
    _inspect(ready)
    calls_before = ready["calls"]["approve"]
    with pytest.raises(WitnessCasFenceError, match="replay"):
        _dispatch(ready)
    with pytest.raises(WitnessCasFenceError, match="already reserved"):
        _reserve(ready)
    assert ready["calls"]["approve"] == calls_before


def test_crash_after_preclaim_blocks_retry_even_when_prior_still_visible(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    with patch(
        "paper_data_suite.evergreen_witness_cas_fence."
        "commit_independently_approved_successor",
        side_effect=KeyboardInterrupt("simulated process termination"),
    ):
        with pytest.raises(KeyboardInterrupt):
            _dispatch(ready)
    assert _inspect(ready).status == "PRIOR_SIGNED_STILL_UNRESOLVED"
    with pytest.raises(WitnessCasFenceError, match="replay"):
        _dispatch(ready)
    assert ready["calls"]["approve"] == 0


def test_lost_ack_after_real_commit_requires_forward_recovery(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)

    def lost_ack(*args: Any, **kwargs: Any) -> None:
        commit_independently_approved_successor(*args, **kwargs)
        raise WitnessCommitProtocolError("reply was lost after durable CAS")

    with patch(
        "paper_data_suite.evergreen_witness_cas_fence."
        "commit_independently_approved_successor",
        side_effect=lost_ack,
    ):
        with pytest.raises(WitnessCasFenceError, match="may have been sent"):
            _dispatch(ready)
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
        == "CAS_MAY_HAVE_BEEN_DISPATCHED"
    )
    assert _inspect(ready).status == "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"


def test_denied_approval_still_requires_explicit_reconciliation(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    with pytest.raises(WitnessCasFenceError, match="may have been sent"):
        _dispatch(ready, independently_approve=lambda _request, _context: False)
    assert _inspect(ready).status == "PRIOR_SIGNED_STILL_UNRESOLVED"
    with pytest.raises(WitnessCasFenceError, match="replay"):
        _dispatch(ready)


def test_outage_on_commit_does_not_release_fence(ready: dict[str, Any]) -> None:
    _reserve(ready)

    def offline(_challenge: bytes) -> bytes:
        raise ConnectionError("network unavailable")

    with pytest.raises(WitnessCasFenceError, match="may have been sent"):
        _dispatch(ready, witness_transport=offline)
    with pytest.raises(WitnessCasFenceError, match="unavailable"):
        _inspect(ready, witness_transport=offline)
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
        == "CAS_MAY_HAVE_BEEN_DISPATCHED"
    )
    assert _inspect(ready).status == "PRIOR_SIGNED_STILL_UNRESOLVED"


def test_wrong_witness_signer_does_not_clear_uncertainty(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    _dispatch(ready)
    with pytest.raises(WitnessCasFenceError, match="unavailable"):
        _inspect(ready, pinned_public_key=b"0" * 32)
    assert (
        ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
        == "CAS_MAY_HAVE_BEEN_DISPATCHED"
    )
    assert _inspect(ready).status == "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"


def test_inspect_before_dispatch_refused(ready: dict[str, Any]) -> None:
    _reserve(ready)
    with pytest.raises(WitnessCasFenceError, match="no CAS dispatch"):
        _inspect(ready)


def test_dispatch_requires_prior_reservation(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessCasFenceError, match="missing reservation"):
        _dispatch(ready)
    assert ready["calls"]["approve"] == 0


def test_wrong_service_identity_denied(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessCasFenceError, match="refused"):
        ready["ledger"].reserve(ready["request"], service_context="teacher")
    assert ready["ledger"].observe(ready["request"], service_context=CONTEXT) is None


def test_one_installation_cannot_reserve_competing_successor(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    alternate = replace(ready["request"], expected_witness_revision=2)
    with pytest.raises(WitnessCasFenceError, match="different"):
        ready["ledger"].reserve(alternate, service_context=CONTEXT)
    with pytest.raises(WitnessCasFenceError, match="different"):
        ready["ledger"].observe(alternate, service_context=CONTEXT)


def test_invalid_receipt_cannot_reserve(ready: dict[str, Any]) -> None:
    malformed = replace(ready["request"], successor_receipt_bytes=b"not a receipt")
    with pytest.raises(WitnessCasFenceError, match="invalid canonical"):
        ready["ledger"].reserve(malformed, service_context=CONTEXT)


def test_fence_survives_sqlite_connection_restart(ready: dict[str, Any]) -> None:
    _reserve(ready)
    with patch(
        "paper_data_suite.evergreen_witness_cas_fence."
        "commit_independently_approved_successor",
        side_effect=KeyboardInterrupt("power loss"),
    ):
        with pytest.raises(KeyboardInterrupt):
            _dispatch(ready)
    ready["connection"].close()
    conn = sqlite3.connect(ready["db_path"], isolation_level=None)
    restored = WitnessCasFenceLedger(conn, authorize=ready["authorize"])
    assert (
        restored.observe(ready["request"], service_context=CONTEXT).status
        == "CAS_MAY_HAVE_BEEN_DISPATCHED"
    )
    with pytest.raises(WitnessCasFenceError, match="replay"):
        restored.dispatch_once(
            ready["request"],
            service_context=CONTEXT,
            store=ready["store"],
            independently_approve=ready["approve"],
            witness_transport=ready["transport"],
            pinned_public_key=ready["public"],
            now=NOW,
        )
    conn.close()


def test_precommit_sqlite_failure_does_not_call_CAS(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    ready["connection"].execute("DROP TABLE witness_cas_attempt_fences")
    with pytest.raises(WitnessCasFenceError):
        _dispatch(ready)
    assert ready["calls"]["approve"] == 0


def test_corrupt_service_ledger_is_not_accepted(ready: dict[str, Any]) -> None:
    _reserve(ready)
    ready["connection"].execute(
        "UPDATE witness_cas_attempt_fences SET state=?,"
        "witnessed_revision=?,witnessed_sha256=? WHERE installation_id=?",
        ("CAS_MAY_HAVE_BEEN_DISPATCHED", 99, "0" * 64, INSTALL),
    )
    with pytest.raises(WitnessCasFenceError, match="corrupt"):
        ready["ledger"].observe(ready["request"], service_context=CONTEXT)
    with pytest.raises(WitnessCasFenceError, match="corrupt"):
        _dispatch(ready)


def test_ledger_drift_during_witness_read_is_refused(
    ready: dict[str, Any],
) -> None:
    _reserve(ready)
    _dispatch(ready)
    original = ready["transport"]

    def mutate(challenge: bytes) -> bytes:
        response = original(challenge)
        ready["connection"].execute(
            "UPDATE witness_cas_attempt_fences SET state=? WHERE installation_id=?",
            ("PRIOR_SIGNED_STILL_UNRESOLVED", INSTALL),
        )
        return response

    with pytest.raises(WitnessCasFenceError):
        _inspect(ready, witness_transport=mutate)


def test_signer_or_service_must_be_independently_provisioned(
    ready: dict[str, Any],
) -> None:
    with pytest.raises(WitnessCasFenceError):
        WitnessCasFenceLedger(sqlite3.connect(":memory:"), authorize=None)
    with pytest.raises(WitnessCasFenceError):
        WitnessCasFenceLedger(None, authorize=ready["authorize"])


def test_no_external_side_effects_until_dispatch(
    ready: dict[str, Any],
) -> None:
    with patch(
        "paper_data_suite.evergreen_witness_cas_fence."
        "commit_independently_approved_successor",
        side_effect=AssertionError("CAS forbidden without dispatch"),
    ):
        _reserve(ready)
        assert (
            ready["ledger"].observe(ready["request"], service_context=CONTEXT).status
            == "PREPARED_NO_DISPATCH"
        )
    assert ready["calls"]["approve"] == 0
