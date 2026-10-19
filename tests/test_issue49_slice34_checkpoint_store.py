"""Slice 34: independent-host witness CAS, freshness, and signed responses."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
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
from paper_data_suite.evergreen_checkpoint_store import (
    CheckpointStoreError,
    MonotonicCheckpointStore,
)
from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    issue_witness_challenge,
    verify_witness_statement,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
INSTALL = "a" * 32
WITNESS = "independent_witness"


def _candidate() -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        "b" * 32,
        1,
        "candidate/one",
        "wheels/one",
        "c" * 64,
        "d" * 64,
        (("quillan", "e" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


def _receipt(previous: ExternallyPinnedReceiptHead | None = None) -> bytes:
    return make_untrusted_active_receipt(
        _candidate(),
        prepared_record=b"signed prepared",
        registry_envelope=b"root registry",
        lock_envelope=b"root lock",
        native_envelope=b"root native",
        generation=1 if previous is None else previous.generation + 1,
        recorded_at=NOW,
        previous=previous,
    )


def _open_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=1)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _authorize(installation: str, operation: str, context: object) -> bool:
    # Only a fixture: production contexts MUST come from independent auth.
    return installation == INSTALL and (
        context == "admin"
        if operation in ("commit", "enroll")
        else context == "reader" and operation == "read"
    )


def _store(
    connection: sqlite3.Connection,
    private: Ed25519PrivateKey,
    *,
    authorize: Any = _authorize,
    sign: Any = None,
) -> MonotonicCheckpointStore:
    return MonotonicCheckpointStore(
        connection,
        witness_id=WITNESS,
        authorize=authorize,
        sign=private.sign if sign is None else sign,
    )


@pytest.fixture
def witness(tmp_path: Path) -> tuple[MonotonicCheckpointStore, Ed25519PrivateKey, Path]:
    db_path = tmp_path / "separate_service.sqlite"
    private = Ed25519PrivateKey.generate()
    store = _store(_open_database(db_path), private)
    return store, private, db_path


def _enroll(store: MonotonicCheckpointStore) -> bytes:
    receipt = _receipt()
    assert store.commit_receipt(INSTALL, receipt, context="admin").revision == 1
    return receipt


def _verify(
    store: MonotonicCheckpointStore,
    key: Ed25519PrivateKey,
    receipt: bytes,
    *,
    now: datetime = NOW,
) -> Any:
    challenge = issue_witness_challenge(installation_id=INSTALL, now=now)
    signed = store.answer_challenge(challenge.bytes, context="reader", now=now)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return verify_witness_statement(
        challenge=challenge,
        signed_reply=signed,
        receipt_bytes=receipt,
        pinned_public_key=public,
        expected_witness_id=WITNESS,
        now=now,
    )


def test_genesis_signed_observation_matches_existing_verifier(
    witness: tuple[MonotonicCheckpointStore, Ed25519PrivateKey, Path],
) -> None:
    store, private, _ = witness
    receipt = _enroll(store)
    evidence = _verify(store, private, receipt)
    assert evidence.receipt.digest == hashlib.sha256(receipt).hexdigest()
    assert evidence.witness_revision == 1
    assert evidence.receipt.receipt.generation == 1
    assert not hasattr(evidence, "can_launch")


def test_successor_uses_exact_previous_receipt(
    witness: tuple[MonotonicCheckpointStore, Ed25519PrivateKey, Path],
) -> None:
    store, private, _ = witness
    first = _enroll(store)
    previous = ExternallyPinnedReceiptHead(1, hashlib.sha256(first).hexdigest())
    second = _receipt(previous)
    next_state = store.commit_receipt(INSTALL, second, context="admin")
    assert next_state.generation == 2
    assert next_state.revision == 2
    assert next_state.previous_sha256 == previous.receipt_sha256
    assert _verify(store, private, second).witness_revision == 2
    with pytest.raises(CheckpointWitnessError, match="continuity"):
        _verify(store, private, first)


def test_reused_genesis_fails_closed(witness: Any) -> None:
    store, _, _ = witness
    first = _enroll(store)
    with pytest.raises(CheckpointStoreError, match="predecessor"):
        store.commit_receipt(INSTALL, first, context="admin")


def test_wrong_predecessor_rejected_without_state_change(witness: Any) -> None:
    store, key, _ = witness
    first = _enroll(store)
    wrong = ExternallyPinnedReceiptHead(1, "e" * 64)
    with pytest.raises(CheckpointStoreError, match="predecessor"):
        store.commit_receipt(INSTALL, _receipt(wrong), context="admin")
    assert _verify(store, key, first).witness_revision == 1


def test_generation_skip_and_duplicate_are_rejected(witness: Any) -> None:
    store, _, _ = witness
    first = _enroll(store)
    previous = ExternallyPinnedReceiptHead(1, hashlib.sha256(first).hexdigest())
    store.commit_receipt(INSTALL, _receipt(previous), context="admin")
    with pytest.raises(CheckpointStoreError, match="predecessor"):
        store.commit_receipt(INSTALL, _receipt(previous), context="admin")


def test_reopen_database_retains_monotonic_state(witness: Any) -> None:
    store, key, path = witness
    first = _enroll(store)
    restarted = _store(_open_database(path), key)
    previous = ExternallyPinnedReceiptHead(1, hashlib.sha256(first).hexdigest())
    second = _receipt(previous)
    assert restarted.commit_receipt(INSTALL, second, context="admin").revision == 2
    assert _verify(store, key, second).witness_revision == 2


def test_separate_connections_serialize_cas(witness: Any) -> None:
    store, key, path = witness
    first = _enroll(store)
    other = _store(_open_database(path), key)
    previous = ExternallyPinnedReceiptHead(1, hashlib.sha256(first).hexdigest())
    second = _receipt(previous)
    assert other.commit_receipt(INSTALL, second, context="admin").revision == 2
    with pytest.raises(CheckpointStoreError, match="predecessor"):
        store.commit_receipt(INSTALL, second, context="admin")


def test_authentication_denied_before_state_change(witness: Any) -> None:
    store, _, _ = witness
    with pytest.raises(CheckpointStoreError, match="denied"):
        store.commit_receipt(INSTALL, _receipt(), context="reader")
    with pytest.raises(CheckpointStoreError, match="denied"):
        store.commit_receipt(INSTALL, _receipt(), context=None)
    assert _enroll(store)


def test_genesis_requires_distinct_enrollment_authority(witness: Any) -> None:
    _, key, path = witness
    operations: list[str] = []

    def deny_enroll(installation: str, operation: str, context: object) -> bool:
        operations.append(operation)
        return operation == "commit" and context == "admin"

    other = _store(_open_database(path), key, authorize=deny_enroll)
    with pytest.raises(CheckpointStoreError, match="denied"):
        other.commit_receipt(INSTALL, _receipt(), context="admin")
    assert operations == ["commit", "enroll"]
    # Failure within BEGIN IMMEDIATE must leave the DB usable.
    third = _store(_open_database(path), key)
    assert third.commit_receipt(INSTALL, _receipt(), context="admin").revision == 1


def test_unauthenticated_read_refused(witness: Any) -> None:
    store, _, _ = witness
    _enroll(store)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    with pytest.raises(CheckpointStoreError, match="denied"):
        store.answer_challenge(challenge.bytes, context="admin", now=NOW)


def test_replayed_challenge_refused_even_after_reopen(witness: Any) -> None:
    store, key, path = witness
    _enroll(store)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    store.answer_challenge(challenge.bytes, context="reader", now=NOW)
    with pytest.raises(CheckpointStoreError, match="replayed"):
        _store(_open_database(path), key).answer_challenge(
            challenge.bytes,
            context="reader",
            now=NOW,
        )


@pytest.mark.parametrize("delta", [-1, 121, 3600])
def test_stale_or_future_challenge_refused(witness: Any, delta: int) -> None:
    store, _, _ = witness
    _enroll(store)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    with pytest.raises(CheckpointStoreError, match="stale or future"):
        store.answer_challenge(
            challenge.bytes,
            context="reader",
            now=NOW + timedelta(seconds=delta),
        )


def test_unknown_installation_never_enrolls_on_read(witness: Any) -> None:
    store, _, _ = witness
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    with pytest.raises(CheckpointStoreError, match="unknown"):
        store.answer_challenge(challenge.bytes, context="reader", now=NOW)


def test_challenge_alteration_is_signed_only_for_exact_bytes(witness: Any) -> None:
    store, _, _ = witness
    _enroll(store)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    changed = json.loads(challenge.bytes)
    changed["nonce_b64"] = base64.b64encode(b"z" * 32).decode("ascii")
    altered = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
    # A caller-supplied challenge is not a witness authorization credential.
    signed = store.answer_challenge(altered, context="reader", now=NOW)
    assert signed != b""
    with pytest.raises(CheckpointStoreError, match="noncanonical"):
        store.answer_challenge(altered + b" ", context="reader", now=NOW)


def test_duplicate_challenge_member_rejected(witness: Any) -> None:
    store, _, _ = witness
    _enroll(store)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    assert challenge.bytes.startswith(b"{")
    bad = challenge.bytes[:-1] + b',"schema_version":1}'
    with pytest.raises(CheckpointStoreError, match="duplicate"):
        store.answer_challenge(bad, context="reader", now=NOW)


def test_bad_key_signer_refused(witness: Any) -> None:
    store, key, path = witness
    _enroll(store)
    broken = _store(_open_database(path), key, sign=lambda data: b"invalid")
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    with pytest.raises(CheckpointStoreError, match="signing"):
        broken.answer_challenge(challenge.bytes, context="reader", now=NOW)


def test_signature_tied_to_outside_pinned_key(witness: Any) -> None:
    store, _, _ = witness
    receipt = _enroll(store)
    different = Ed25519PrivateKey.generate()
    with pytest.raises(CheckpointWitnessError, match="signature"):
        _verify(store, different, receipt)


def test_witness_database_state_is_not_independent_authority(witness: Any) -> None:
    store, key, _ = witness
    receipt = _enroll(store)
    assert _verify(store, key, receipt)
    # Neither a local row nor returned CommittedCheckpoint exposes can_launch.
    committed = store.commit_receipt(
        INSTALL,
        _receipt(ExternallyPinnedReceiptHead(1, hashlib.sha256(receipt).hexdigest())),
        context="admin",
    )
    assert not hasattr(committed, "can_launch")


def test_corrupt_database_hash_causes_fail_closed(witness: Any) -> None:
    store, _, path = witness
    _enroll(store)
    direct = _open_database(path)
    direct.execute("UPDATE witness_heads SET receipt_sha256='not_a_hash'")
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    with pytest.raises(CheckpointStoreError, match="corrupt"):
        store.answer_challenge(challenge.bytes, context="reader", now=NOW)


def test_rejected_receipt_bytes_cannot_enroll(witness: Any) -> None:
    store, _, _ = witness
    with pytest.raises(CheckpointStoreError, match="noncanonical"):
        store.commit_receipt(INSTALL, b"{}", context="admin")


def test_minimum_revision_remains_caller_enforced(witness: Any) -> None:
    store, key, _ = witness
    receipt = _enroll(store)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    signed = store.answer_challenge(challenge.bytes, context="reader", now=NOW)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    with pytest.raises(CheckpointWitnessError, match="rollback"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=signed,
            receipt_bytes=receipt,
            pinned_public_key=public,
            expected_witness_id=WITNESS,
            now=NOW,
            minimum_witness_revision=2,
        )
