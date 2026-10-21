"""Slice 42: witness-side opt-in CAS; lost acknowledgments stay unresolved."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    commit_independently_approved_successor,
    inspect_uncertain_witness_commit,
    make_witness_commit_request,
    parse_witness_commit_request,
    serialize_witness_commit_request,
)

NOW = datetime(2026, 10, 20, 18, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "authenticated-service-operator"


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
def witness() -> dict[str, Any]:
    prior = make_untrusted_active_receipt(
        _candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"prior-prepared",
        registry_envelope=b"prior-registry",
        lock_envelope=b"prior-lock",
        native_envelope=b"prior-native",
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        _candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"next-prepared",
        registry_envelope=b"next-registry",
        lock_envelope=b"next-lock",
        native_envelope=b"next-native",
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
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    connection = sqlite3.connect(":memory:", isolation_level=None)
    calls: list[str] = []

    def allow(install: str, operation: str, context: object) -> bool:
        calls.append(operation)
        return install == INSTALL and context == CONTEXT

    store = MonotonicCheckpointStore(
        connection, witness_id=WITNESS, authorize=allow, sign=private.sign
    )
    store.commit_receipt(INSTALL, prior, context=CONTEXT)
    counts = {"approvals": 0, "transport": 0}

    def transport(challenge: bytes) -> bytes:
        counts["transport"] += 1
        return store.answer_challenge(challenge, context=CONTEXT, now=NOW)

    def approve(proposal: WitnessCommitRequest, context: object) -> bool:
        counts["approvals"] += 1
        return proposal is request and context == CONTEXT

    return {
        "prior": prior,
        "successor": successor,
        "draft": draft,
        "request": request,
        "store": store,
        "public": public,
        "transport": transport,
        "approve": approve,
        "counts": counts,
        "calls": calls,
    }


def _commit(witness: dict[str, Any], **changes: Any) -> Any:
    args = {
        "request": witness["request"],
        "store": witness["store"],
        "service_context": CONTEXT,
        "independently_approve": witness["approve"],
        "witness_transport": witness["transport"],
        "pinned_public_key": witness["public"],
        "now": NOW,
    }
    return commit_independently_approved_successor(**{**args, **changes})


def _read(witness: dict[str, Any], **changes: Any) -> Any:
    args = {
        "request": witness["request"],
        "witness_transport": witness["transport"],
        "pinned_public_key": witness["public"],
        "now": NOW,
    }
    return inspect_uncertain_witness_commit(**{**args, **changes})


def test_request_is_canonical_and_never_a_credential(witness: dict[str, Any]) -> None:
    request = witness["request"]
    raw = serialize_witness_commit_request(request)
    assert parse_witness_commit_request(raw) == request
    assert raw == serialize_witness_commit_request(parse_witness_commit_request(raw))
    assert b"DRAFT_ONLY" not in raw
    assert not hasattr(request, "can_launch")
    assert not hasattr(request, "approval")
    assert witness["counts"] == {"approvals": 0, "transport": 0}


def test_initial_signed_head_does_not_prove_no_commit_in_flight(
    witness: dict[str, Any],
) -> None:
    observed = _read(witness)
    assert observed.status == "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"
    assert observed.generation == 1 and observed.witness_revision == 1
    assert observed.receipt_sha256 == _sha(witness["prior"])
    assert not hasattr(observed, "rollback")


def test_independently_approved_server_cas_and_signed_readback(
    witness: dict[str, Any],
) -> None:
    result = _commit(witness)
    assert result.status == "SERVICE_CAS_RETURNED_INDEPENDENT_READBACK_REQUIRED"
    assert result.committed_witness_revision == 2
    assert result.successor_generation == 2
    assert result.successor_sha256 == _sha(witness["successor"])
    assert witness["counts"]["approvals"] == 1
    assert "commit" in witness["calls"]
    observed = _read(witness)
    assert observed.status == "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
    assert observed.witness_revision == 2 and observed.generation == 2
    assert observed.receipt_sha256 == result.successor_sha256
    assert not hasattr(observed, "activate")


def test_duplicate_commit_not_idempotently_replayed(witness: dict[str, Any]) -> None:
    _commit(witness)
    with pytest.raises(WitnessCommitProtocolError, match="predecessor"):
        _commit(witness)
    assert witness["counts"]["approvals"] == 1


def test_lost_ack_recovered_by_single_signed_head_query(
    witness: dict[str, Any],
) -> None:
    # Service CAS has happened but the client received no result.
    witness["store"].commit_receipt(INSTALL, witness["successor"], context=CONTEXT)
    initial = witness["counts"]["transport"]
    observed = _read(witness)
    assert observed.status == "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
    assert witness["counts"]["transport"] == initial + 1
    assert witness["counts"]["approvals"] == 0


def test_service_denial_does_not_write(witness: dict[str, Any]) -> None:
    with pytest.raises(WitnessCommitProtocolError, match="refused"):
        _commit(witness, independently_approve=lambda *args: False)
    assert _read(witness).generation == 1


def test_service_approval_exception_fails_closed(witness: dict[str, Any]) -> None:
    def no(*args: Any) -> bool:
        raise RuntimeError("private deployment path")

    with pytest.raises(WitnessCommitProtocolError, match="approval failed") as err:
        _commit(witness, independently_approve=no)
    assert "private deployment path" not in str(err.value)
    assert _read(witness).generation == 1


def test_service_context_denied_by_store(witness: dict[str, Any]) -> None:
    with pytest.raises(WitnessCommitProtocolError, match="outcome ambiguous"):
        _commit(
            witness,
            service_context="unprivileged",
            independently_approve=lambda *args: True,
        )
    assert _read(witness).generation == 1


def test_non_service_store_refused(witness: dict[str, Any]) -> None:
    with pytest.raises(WitnessCommitProtocolError, match="service"):
        _commit(witness, store=object())


def test_wrong_or_stale_witness_revision_refused(witness: dict[str, Any]) -> None:
    altered = replace(witness["request"], expected_witness_revision=2)
    with pytest.raises(WitnessCommitProtocolError):
        _commit(witness, request=altered)
    assert witness["counts"]["approvals"] == 0


def test_signed_witness_key_pin_refused(witness: dict[str, Any]) -> None:
    with pytest.raises(WitnessCommitProtocolError):
        _commit(witness, pinned_public_key=b"0" * 32)
    assert witness["counts"]["approvals"] == 0


def test_witness_offline_before_cas_refused(witness: dict[str, Any]) -> None:
    def offline(*args: Any) -> bytes:
        raise ConnectionError("offline")

    with pytest.raises(WitnessCommitProtocolError, match="unavailable"):
        _commit(witness, witness_transport=offline)
    assert witness["counts"]["approvals"] == 0


def test_signed_readback_after_network_failure_not_automatic_rollback(
    witness: dict[str, Any],
) -> None:
    with pytest.raises(WitnessCommitProtocolError, match="unrecognized"):
        _read(witness, witness_transport=lambda _: b"{}")
    assert _read(witness).status == "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"


def test_competing_commit_after_precheck_fails_cas(witness: dict[str, Any]) -> None:
    competitor = make_untrusted_active_receipt(
        _candidate("d" * 32, "alternate/three", "alternate/wheels"),
        prepared_record=b"alternate-prepared",
        registry_envelope=b"alternate-registry",
        lock_envelope=b"alternate-lock",
        native_envelope=b"alternate-native",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, _sha(witness["prior"])),
    )

    def race(proposal: WitnessCommitRequest, context: object) -> bool:
        witness["store"].commit_receipt(INSTALL, competitor, context=CONTEXT)
        return True

    with pytest.raises(WitnessCommitProtocolError, match="outcome ambiguous"):
        _commit(witness, independently_approve=race)
    with pytest.raises(WitnessCommitProtocolError, match="unrecognized"):
        _read(witness)


def test_mutated_successor_receipt_digest_rejected(witness: dict[str, Any]) -> None:
    altered = replace(witness["request"], successor_receipt_bytes=b"tampered")
    with pytest.raises(WitnessCommitProtocolError):
        serialize_witness_commit_request(altered)


def test_non_successor_and_unrelated_predecessor_rejected(
    witness: dict[str, Any],
) -> None:
    with pytest.raises(WitnessCommitProtocolError):
        serialize_witness_commit_request(
            replace(witness["request"], previous_receipt_bytes=witness["successor"])
        )


def test_wrong_draft_transaction_and_digest_refused(witness: dict[str, Any]) -> None:
    with pytest.raises(WitnessCommitProtocolError):
        make_witness_commit_request(
            replace(witness["draft"], transaction_id="d" * 32),
            installation_id=INSTALL,
            witness_id=WITNESS,
            previous_receipt_bytes=witness["prior"],
        )
    with pytest.raises(WitnessCommitProtocolError):
        make_witness_commit_request(
            replace(witness["draft"], proposed_receipt_sha256="0" * 64),
            installation_id=INSTALL,
            witness_id=WITNESS,
            previous_receipt_bytes=witness["prior"],
        )


@pytest.mark.parametrize(
    "change",
    [
        {"expected_witness_revision": True},
        {"expected_witness_revision": 0},
        {"expected_witness_revision": 2**53},
        {"installation_id": "not-an-installation"},
        {"witness_id": "WITNESS"},
        {"previous_receipt_bytes": b""},
        {"successor_receipt_bytes": b"x" * 16385},
    ],
)
def test_invalid_request_fails_before_network(
    witness: dict[str, Any], change: dict[str, Any]
) -> None:
    with pytest.raises(WitnessCommitProtocolError):
        serialize_witness_commit_request(replace(witness["request"], **change))
    assert witness["counts"]["transport"] == 0


def test_unknown_json_fields_rejected(witness: dict[str, Any]) -> None:
    raw = serialize_witness_commit_request(witness["request"])
    parsed = json.loads(raw)
    parsed["unexpected"] = "more authority"
    with pytest.raises(WitnessCommitProtocolError):
        parse_witness_commit_request(
            json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()
        )


def test_duplicate_json_fields_rejected(witness: dict[str, Any]) -> None:
    raw = serialize_witness_commit_request(witness["request"])
    mutated = raw.replace(
        b'"schema_version":1,', b'"schema_version":1,"schema_version":1,'
    )
    with pytest.raises(WitnessCommitProtocolError, match="duplicate"):
        parse_witness_commit_request(mutated)


def test_noncanonical_json_rejected(witness: dict[str, Any]) -> None:
    raw = serialize_witness_commit_request(witness["request"])
    with pytest.raises(WitnessCommitProtocolError, match="canonical"):
        parse_witness_commit_request(
            raw.replace(b'"schema_version":1', b'"schema_version": 1')
        )


def test_digest_mismatch_rejected(witness: dict[str, Any]) -> None:
    raw = serialize_witness_commit_request(witness["request"])
    mutated = raw.replace(b'"predecessor_sha256":"', b'"predecessor_sha256":"0')
    with pytest.raises(WitnessCommitProtocolError):
        parse_witness_commit_request(mutated)


def test_request_oversize_rejected_before_decode(witness: dict[str, Any]) -> None:
    with pytest.raises(WitnessCommitProtocolError, match="size"):
        parse_witness_commit_request(b"x" * 49153)


def test_no_subprocess_launch_or_local_recovery_mutation(
    witness: dict[str, Any],
) -> None:
    with patch("subprocess.run", side_effect=AssertionError("no subprocess")):
        _read(witness)
        _commit(witness)
        _read(witness)
    assert not hasattr(witness["request"], "restore_previous_selection")
