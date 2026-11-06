"""Issue #49 Slice 33: challenge-bound signed external checkpoint head."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    issue_witness_challenge,
    query_checkpoint_witness,
    verify_witness_statement,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
INSTALL = "a" * 32
WITNESS = "school_witness_1"
_EVIDENCE = {
    "prepared_record": b"signed prepared",
    "registry_envelope": b"root registry",
    "lock_envelope": b"root lock",
    "native_envelope": b"root native",
}


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
        **_EVIDENCE,
        generation=1 if previous is None else 2,
        recorded_at=NOW,
        previous=previous,
    )


def _canon(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii")


def _public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _signed(key: Ed25519PrivateKey, data: dict[str, Any]) -> bytes:
    payload = _canon(data)
    return _canon(
        {
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signature_b64": base64.b64encode(key.sign(payload)).decode("ascii"),
        }
    )


def _fixture(
    *,
    previous: ExternallyPinnedReceiptHead | None = None,
) -> tuple[Ed25519PrivateKey, bytes, object, dict[str, Any]]:
    receipt = _receipt(previous)
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    key = Ed25519PrivateKey.generate()
    statement: dict[str, Any] = {
        "record_type": "pds_external_checkpoint_statement",
        "schema_version": 1,
        "witness_id": WITNESS,
        "installation_id": INSTALL,
        "challenge_sha256": hashlib.sha256(challenge.bytes).hexdigest(),
        "witness_revision": 8 if previous is None else 9,
        "head_generation": 1 if previous is None else 2,
        "head_sha256": hashlib.sha256(receipt).hexdigest(),
        "predecessor_generation": previous.generation if previous else None,
        "predecessor_sha256": previous.receipt_sha256 if previous else None,
        "issued_at": "2026-10-19T18:00:00Z",
        "expires_at": "2026-10-19T18:01:00Z",
    }
    return key, receipt, challenge, statement


def _verify(
    key: Ed25519PrivateKey,
    receipt: bytes,
    challenge: Any,
    statement: dict[str, Any],
    **options: Any,
) -> Any:
    return verify_witness_statement(
        challenge=challenge,
        signed_reply=_signed(key, statement),
        receipt_bytes=receipt,
        pinned_public_key=_public(key),
        expected_witness_id=WITNESS,
        now=NOW,
        **options,
    )


def test_signed_fresh_genesis_head_matches_exact_receipt() -> None:
    key, receipt, challenge, statement = _fixture()
    result = _verify(key, receipt, challenge, statement, minimum_witness_revision=8)
    assert result.receipt.receipt.generation == 1
    assert result.receipt.digest == hashlib.sha256(receipt).hexdigest()
    assert result.witness_revision == 8
    assert result.witness_id == WITNESS
    assert not hasattr(result, "can_launch")


def test_next_generation_is_pinned_to_signed_previous_head() -> None:
    first = _receipt()
    previous = ExternallyPinnedReceiptHead(1, hashlib.sha256(first).hexdigest())
    key, receipt, challenge, statement = _fixture(previous=previous)
    result = _verify(key, receipt, challenge, statement)
    assert result.receipt.receipt.previous_receipt_sha256 == previous.receipt_sha256
    assert result.receipt.receipt.generation == 2


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("installation_id", "f" * 32, "identity"),
        ("witness_id", "other_witness", "identity"),
        ("challenge_sha256", "f" * 64, "identity"),
        ("head_sha256", "f" * 64, "continuity"),
        ("head_generation", 2, "continuity"),
        ("head_generation", True, "generation"),
        ("witness_revision", 0, "revision"),
        ("predecessor_generation", 1, "predecessor"),
        ("issued_at", "2026-10-19T18:01:00Z", "stale"),
        ("expires_at", "2026-10-19T17:59:00Z", "stale"),
        ("expires_at", "2026-10-19T18:10:00Z", "stale"),
    ],
)
def test_signed_mismatched_claims_fail_closed(
    field: str,
    value: object,
    match: str,
) -> None:
    key, receipt, challenge, statement = _fixture()
    statement[field] = value
    with pytest.raises(CheckpointWitnessError, match=match):
        _verify(key, receipt, challenge, statement)


def test_replay_to_fresh_challenge_fails() -> None:
    key, receipt, old_challenge, statement = _fixture()
    new = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    assert new.bytes != old_challenge.bytes
    with pytest.raises(CheckpointWitnessError, match="identity"):
        verify_witness_statement(
            challenge=new,
            signed_reply=_signed(key, statement),
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )


def test_signature_or_trust_key_substitution_rejected() -> None:
    key, receipt, challenge, statement = _fixture()
    wrong = Ed25519PrivateKey.generate()
    with pytest.raises(CheckpointWitnessError, match="signature"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=_signed(key, statement),
            receipt_bytes=receipt,
            pinned_public_key=_public(wrong),
            expected_witness_id=WITNESS,
            now=NOW,
        )
    with pytest.raises(CheckpointWitnessError, match="key"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=_signed(key, statement),
            receipt_bytes=receipt,
            pinned_public_key=b"",
            expected_witness_id=WITNESS,
            now=NOW,
        )


def test_revision_floor_blocks_older_signed_witness_head() -> None:
    key, receipt, challenge, statement = _fixture()
    with pytest.raises(CheckpointWitnessError, match="rollback"):
        _verify(key, receipt, challenge, statement, minimum_witness_revision=9)
    assert _verify(key, receipt, challenge, statement, minimum_witness_revision=8)


def test_missing_or_unprovisioned_transport_refuses() -> None:
    key, receipt, _, _ = _fixture()
    with pytest.raises(CheckpointWitnessError, match="provisioned"):
        query_checkpoint_witness(
            None,  # type: ignore[arg-type]
            installation_id=INSTALL,
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )


def test_query_generates_fresh_challenge_and_binds_response() -> None:
    key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    challenges: list[bytes] = []

    def witness(raw: bytes) -> bytes:
        challenges.append(raw)
        payload = {
            "record_type": "pds_external_checkpoint_statement",
            "schema_version": 1,
            "witness_id": WITNESS,
            "installation_id": INSTALL,
            "challenge_sha256": hashlib.sha256(raw).hexdigest(),
            "witness_revision": 8,
            "head_generation": 1,
            "head_sha256": hashlib.sha256(receipt).hexdigest(),
            "predecessor_generation": None,
            "predecessor_sha256": None,
            "issued_at": "2026-10-19T18:00:00Z",
            "expires_at": "2026-10-19T18:01:00Z",
        }
        return _signed(key, payload)

    for _ in range(2):
        result = query_checkpoint_witness(
            witness,
            installation_id=INSTALL,
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )
        assert result.witness_revision == 8
    assert len(set(challenges)) == 2


def test_transport_error_is_not_silently_treated_as_trust() -> None:
    key, receipt, _, _ = _fixture()

    def unavailable(_: bytes) -> bytes:
        raise TimeoutError("offline")

    with pytest.raises(CheckpointWitnessError, match="unavailable"):
        query_checkpoint_witness(
            unavailable,
            installation_id=INSTALL,
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )


def test_duplicate_json_and_noncanonical_payload_rejected() -> None:
    key, receipt, challenge, statement = _fixture()
    valid = _signed(key, statement)
    with pytest.raises(CheckpointWitnessError, match="duplicate"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=valid.replace(
                b'"signature_b64":',
                b'"signature_b64":"x","signature_b64":',
            ),
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )
    raw = _canon(statement) + b"\n"
    invalid = _canon(
        {
            "payload_b64": base64.b64encode(raw).decode("ascii"),
            "signature_b64": base64.b64encode(key.sign(raw)).decode("ascii"),
        }
    )
    with pytest.raises(CheckpointWitnessError, match="noncanonical"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=invalid,
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )


def test_oversized_and_unexpected_members_refused() -> None:
    key, receipt, challenge, statement = _fixture()
    statement["can_launch"] = True
    with pytest.raises(CheckpointWitnessError, match="schema"):
        _verify(key, receipt, challenge, statement)
    with pytest.raises(CheckpointWitnessError, match="size"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=b"X" * 9000,
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW,
        )


def test_challenge_expires_and_clock_must_be_aware() -> None:
    key, receipt, challenge, statement = _fixture()
    with pytest.raises(CheckpointWitnessError, match="challenge"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=_signed(key, statement),
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW + timedelta(seconds=121),
        )
    with pytest.raises(CheckpointWitnessError, match="clock"):
        verify_witness_statement(
            challenge=challenge,
            signed_reply=_signed(key, statement),
            receipt_bytes=receipt,
            pinned_public_key=_public(key),
            expected_witness_id=WITNESS,
            now=NOW.replace(tzinfo=None),
        )


def test_synthetic_signer_does_not_provision_real_witness_or_launch() -> None:
    key, receipt, challenge, statement = _fixture()
    observed = _verify(key, receipt, challenge, statement)
    assert not hasattr(observed, "activate")
    assert not hasattr(observed, "trusted_active_installation")
    assert not hasattr(observed, "launch")
