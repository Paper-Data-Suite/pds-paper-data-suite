"""Slice 51: signed service statement is checked before local handoff use."""

from __future__ import annotations

import hashlib
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
from paper_data_suite.evergreen_attested_forward_handoff import (
    AttestedForwardHandoffError,
    inspect_attested_forward_handoff,
)
from paper_data_suite.evergreen_forward_byte_requalification import (
    ObservedForwardSuccessorBytes,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_local_receipt_recovery import ForwardRecoveryObservation
from paper_data_suite.evergreen_service_recovery_attestation import (
    issue_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 22, 20, 30, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CHALLENGE = b"Q" * 32


def digest(raw: bytes) -> str:
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
def ready() -> dict[str, Any]:
    old = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old prepared",
        registry_envelope=b"old registry",
        lock_envelope=b"old lock",
        native_envelope=b"old native",
        generation=1,
        recorded_at=NOW - timedelta(minutes=4),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"next prepared",
        registry_envelope=b"next registry",
        lock_envelope=b"next lock",
        native_envelope=b"next native",
        generation=2,
        recorded_at=NOW - timedelta(minutes=1),
        previous=ExternallyPinnedReceiptHead(1, digest(old)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, old, successor)
    service = WitnessWriterQuiescenceState(
        INSTALL,
        digest(serialize_witness_commit_request(request)),
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        digest(successor),
    )
    key = Ed25519PrivateKey.generate()
    raw = issue_service_recovery_attestation(
        request, service, challenge=CHALLENGE, observed_at=NOW, sign=key.sign
    )
    return {
        "request": request,
        "envelope": raw,
        "key": key,
        "public": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        "local": ForwardRecoveryObservation(
            NEXT,
            2,
            2,
            digest(successor),
            "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED",
        ),
        "requalified": ObservedForwardSuccessorBytes(
            NEXT,
            2,
            digest(successor),
            2,
            "4" * 64,
            "3" * 64,
            "candidate/two",
        ),
    }


def inspect(ready: dict[str, Any], **updates: Any) -> Any:
    inputs: dict[str, Any] = {
        "request": ready["request"],
        "signed_service_envelope": ready["envelope"],
        "challenge": CHALLENGE,
        "pinned_service_public_key": ready["public"],
        "now": NOW,
        "local": ready["local"],
        "requalified": ready["requalified"],
    }
    return inspect_attested_forward_handoff(**{**inputs, **updates})


def test_valid_signed_service_and_successor_produce_only_review(
    ready: dict[str, Any],
) -> None:
    result = inspect(ready)
    assert result.service_observation.transaction_id == NEXT
    assert result.service_observation.status == (
        "SERVICE_SIGNED_SUCCESSOR_OBSERVATION_ONLY"
    )
    assert result.forward_handoff.transaction_id == NEXT
    assert result.forward_handoff.witness_revision == 2
    assert result.forward_handoff.native_payload_sha256 == "3" * 64
    assert result.forward_handoff.pip_inventory_sha256 == "4" * 64
    assert result.status == "SIGNED_SERVICE_HANDOFF_CORRELATED_REVIEW_ONLY"
    assert result.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    assert result.forward_handoff.authority == (
        "NO_LAUNCH_ROLLBACK_RECEIPT_OR_SWITCH_AUTHORITY"
    )
    assert result.service_envelope_sha256 == digest(ready["envelope"])
    for name in ("launch", "rollback", "activate", "commit", "clear_recovery"):
        assert not hasattr(result, name)


def test_deterministic_result_and_read_only(ready: dict[str, Any]) -> None:
    before = dict(ready)
    with (
        patch("subprocess.run", side_effect=AssertionError("exec")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("write")),
    ):
        result = inspect(ready)
        assert result == inspect(ready)
    assert ready == before


def test_an_untrusted_service_state_is_not_an_input(ready: dict[str, Any]) -> None:
    # No raw service_state parameter. Only signed input is accepted.
    with pytest.raises(TypeError):
        inspect(ready, service=object())
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, signed_service_envelope=b"unsigned")


def test_other_service_signer_fails(ready: dict[str, Any]) -> None:
    other = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, pinned_service_public_key=other)


def test_changed_service_signature_fails(ready: dict[str, Any]) -> None:
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, signed_service_envelope=ready["envelope"][:-1] + b"x")


@pytest.mark.parametrize("challenge", [b"", b"X" * 32, b"Q" * 31, b"Q" * 33])
def test_challenge_mismatch_or_invalid_length_fails(
    ready: dict[str, Any], challenge: bytes
) -> None:
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, challenge=challenge)


@pytest.mark.parametrize("delta", [-1, 60, 3600])
def test_stale_or_future_service_statement_fails(
    ready: dict[str, Any], delta: int
) -> None:
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, now=NOW + timedelta(seconds=delta))


def test_same_envelope_cannot_authorize_another_request(ready: dict[str, Any]) -> None:
    different = replace(ready["request"], witness_id="another_witness")
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, request=different)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("transaction_id", "d" * 32),
        ("generation", 1),
        ("witness_revision", 1),
        ("observed_receipt_sha256", "0" * 64),
        ("status", "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"),
        ("authority", "CAN_LAUNCH"),
    ],
)
def test_local_witness_claim_conflict_fails(
    ready: dict[str, Any], field: str, bad: Any
) -> None:
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, local=replace(ready["local"], **{field: bad}))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("transaction_id", "d" * 32),
        ("generation", 1),
        ("witness_revision", 1),
        ("successor_receipt_sha256", "0" * 64),
        ("stage_relative_path", "other/path"),
        ("pip_inventory_sha256", "3" * 64),
        ("native_payload_sha256", "4" * 64),
        ("status", "READY_TO_ACTIVATE"),
        ("authority", "CAN_COMMIT"),
    ],
)
def test_physical_byte_claim_conflict_fails(
    ready: dict[str, Any], field: str, bad: Any
) -> None:
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, requalified=replace(ready["requalified"], **{field: bad}))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("signed_service_envelope", None),
        ("local", {}),
        ("requalified", None),
        ("pinned_service_public_key", b""),
        ("request", None),
        ("now", datetime(2026, 10, 22, 20, 30)),
    ],
)
def test_missing_or_wrong_inputs_fail_closed(
    ready: dict[str, Any], field: str, bad: Any
) -> None:
    with pytest.raises(AttestedForwardHandoffError):
        inspect(ready, **{field: bad})


def test_verification_precedes_convergence_check(ready: dict[str, Any]) -> None:
    import paper_data_suite.evergreen_attested_forward_handoff as module

    with patch.object(
        module, "compare_recovery_convergence", side_effect=AssertionError("called")
    ):
        with pytest.raises(AttestedForwardHandoffError):
            inspect(ready, challenge=b"X" * 32)


def test_convergence_is_recomputed_not_injected(ready: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        inspect(ready, convergence=object())
    assert inspect(ready).forward_handoff.transaction_id == NEXT
