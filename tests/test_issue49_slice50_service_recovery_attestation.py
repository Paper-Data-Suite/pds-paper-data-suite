"""Slice 50: signed service observation is bounded and NEVER recovery authority."""

from __future__ import annotations

import base64
import hashlib
import json
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
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_service_recovery_attestation import (
    RecoveryServiceAttestationError,
    issue_service_recovery_attestation,
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 22, 20, tzinfo=UTC)
INSTALL = "a" * 32
PREVIOUS = "b" * 32
SUCCESSOR = "c" * 32
WITNESS = "independent_witness"
CHALLENGE = b"R" * 32


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
def ready() -> dict[str, Any]:
    prev = make_untrusted_active_receipt(
        candidate(PREVIOUS, "prior/one", "prior/wheels"),
        prepared_record=b"prior-prepared",
        registry_envelope=b"prior-registry",
        lock_envelope=b"prior-lock",
        native_envelope=b"prior-native",
        generation=1,
        recorded_at=NOW - timedelta(minutes=5),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(SUCCESSOR, "candidate/two", "candidate/wheels"),
        prepared_record=b"successor-prepared",
        registry_envelope=b"successor-registry",
        lock_envelope=b"successor-lock",
        native_envelope=b"successor-native",
        generation=2,
        recorded_at=NOW - timedelta(minutes=1),
        previous=ExternallyPinnedReceiptHead(1, sha(prev)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, prev, successor)
    service = WitnessWriterQuiescenceState(
        INSTALL,
        sha(serialize_witness_commit_request(request)),
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        sha(successor),
    )
    key = Ed25519PrivateKey.generate()
    return {
        "request": request,
        "service": service,
        "key": key,
        "public": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
    }


def issue(ready: dict[str, Any], **kwargs: Any) -> bytes:
    values = {
        "request": ready["request"],
        "service": ready["service"],
        "challenge": CHALLENGE,
        "observed_at": NOW,
        "sign": ready["key"].sign,
    }
    return issue_service_recovery_attestation(**{**values, **kwargs})


def verify(ready: dict[str, Any], raw: bytes, **kwargs: Any) -> Any:
    values = {
        "request": ready["request"],
        "challenge": CHALLENGE,
        "pinned_service_public_key": ready["public"],
        "now": NOW,
    }
    return verify_service_recovery_attestation(raw, **{**values, **kwargs})


def test_signed_observation_binds_exact_successor_but_grants_no_rights(
    ready: dict[str, Any],
) -> None:
    raw = issue(ready)
    result = verify(ready, raw)
    assert result.successor_sha256 == ready["request"].successor_sha256
    assert result.transaction_id == SUCCESSOR
    assert result.installation_id == INSTALL
    assert result.witness_revision == 2 and result.successor_generation == 2
    assert result.status == "SERVICE_SIGNED_SUCCESSOR_OBSERVATION_ONLY"
    assert result.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    assert result.expires_at - result.issued_at == timedelta(seconds=60)
    assert not hasattr(result, "activate")
    assert not hasattr(result, "rollback")
    assert not hasattr(result, "commit")
    assert not hasattr(result, "launch")


def test_signer_receives_domain_separated_canonical_bytes(
    ready: dict[str, Any],
) -> None:
    messages: list[bytes] = []

    def wrapped(data: bytes) -> bytes:
        messages.append(data)
        return ready["key"].sign(data)

    raw = issue(ready, sign=wrapped)
    assert len(messages) == 1
    assert messages[0].startswith(b"pds-evergreen-service-recovery-observation-v1\x00{")
    assert verify(ready, raw).transaction_id == SUCCESSOR
    assert issue(ready) == raw


def test_random_challenge_mismatch_fails(ready: dict[str, Any]) -> None:
    raw = issue(ready)
    with pytest.raises(RecoveryServiceAttestationError, match="another request"):
        verify(ready, raw, challenge=b"Z" * 32)


def test_wrong_service_signer_fails(ready: dict[str, Any]) -> None:
    raw = issue(ready)
    alien = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(RecoveryServiceAttestationError, match="not trusted"):
        verify(ready, raw, pinned_service_public_key=alien)


def test_corrupted_signature_fails(ready: dict[str, Any]) -> None:
    outer = json.loads(issue(ready))
    outer["signature_b64"] = base64.b64encode(b"0" * 64).decode("ascii")
    raw = json.dumps(outer, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(RecoveryServiceAttestationError, match="not trusted"):
        verify(ready, raw)


@pytest.mark.parametrize("offset", [-1, 60, 600])
def test_expired_or_early_observation_fails(ready: dict[str, Any], offset: int) -> None:
    raw = issue(ready)
    with pytest.raises(RecoveryServiceAttestationError, match="another request"):
        verify(ready, raw, now=NOW + timedelta(seconds=offset))


def test_last_second_is_accepted(ready: dict[str, Any]) -> None:
    raw = issue(ready)
    assert verify(ready, raw, now=NOW + timedelta(seconds=59)).witness_revision == 2


@pytest.mark.parametrize(
    "change",
    [
        {
            "status": "STOP_REQUESTED_MAY_BE_IN_FLIGHT",
            "signed_revision": None,
            "signed_head_sha256": None,
        },
        {"status": "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"},
        {"request_sha256": "0" * 64},
        {"signed_revision": 1},
        {"signed_revision": True},
        {"signed_head_sha256": "0" * 64},
        {"authority": "CAN_LAUNCH"},
        {"installation_id": "f" * 32},
    ],
)
def test_uncertain_or_forged_service_state_cannot_be_issued(
    ready: dict[str, Any], change: dict[str, Any]
) -> None:
    service = replace(ready["service"], **change)
    with pytest.raises(RecoveryServiceAttestationError):
        issue(ready, service=service)


def test_other_canonical_request_is_rejected(ready: dict[str, Any]) -> None:
    raw = issue(ready)
    alien = replace(ready["request"], witness_id="a_different_witness")
    with pytest.raises(RecoveryServiceAttestationError):
        verify(ready, raw, request=alien)


def test_invalid_request_rejected(ready: dict[str, Any]) -> None:
    with pytest.raises(RecoveryServiceAttestationError):
        issue(ready, request=replace(ready["request"], expected_witness_revision=0))


@pytest.mark.parametrize("challenge", [b"", b"0" * 31, b"0" * 33])
def test_challenge_requires_exact_32_bytes(
    ready: dict[str, Any], challenge: bytes
) -> None:
    with pytest.raises(RecoveryServiceAttestationError, match="32-byte"):
        issue(ready, challenge=challenge)


def test_invalid_clock_rejected(ready: dict[str, Any]) -> None:
    with pytest.raises(RecoveryServiceAttestationError, match="clock"):
        issue(ready, observed_at=datetime(2026, 10, 22, 20))
    with pytest.raises(RecoveryServiceAttestationError, match="clock"):
        verify(ready, issue(ready), now=NOW.replace(microsecond=1))


def test_signer_outage_and_invalid_signature_fail(ready: dict[str, Any]) -> None:
    def offline(_message: bytes) -> bytes:
        raise ConnectionError("service down")

    with pytest.raises(RecoveryServiceAttestationError, match="unavailable"):
        issue(ready, sign=offline)
    with pytest.raises(RecoveryServiceAttestationError, match="invalid service"):
        issue(ready, sign=lambda _message: b"wrong")


def test_noncanonical_or_duplicate_signed_envelope_rejected(
    ready: dict[str, Any],
) -> None:
    raw = issue(ready)
    with pytest.raises(RecoveryServiceAttestationError, match="noncanonical"):
        verify(ready, b" " + raw)
    with pytest.raises(RecoveryServiceAttestationError, match="duplicate"):
        verify(ready, raw[:-1] + b',"schema_version":1}')


def test_unknown_schema_and_extra_signed_fields_rejected(
    ready: dict[str, Any],
) -> None:
    outer = json.loads(issue(ready))
    outer["schema_version"] = 2
    with pytest.raises(RecoveryServiceAttestationError, match="unsupported"):
        verify(ready, json.dumps(outer, sort_keys=True, separators=(",", ":")).encode())


def test_unsigned_modified_authority_is_not_accepted(ready: dict[str, Any]) -> None:
    outer = json.loads(issue(ready))
    payload = json.loads(base64.b64decode(outer["payload_b64"]))
    payload["authority"] = "CAN_ROLLBACK"
    outer["payload_b64"] = base64.b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode("ascii")
    with pytest.raises(RecoveryServiceAttestationError, match="not trusted"):
        verify(ready, json.dumps(outer, sort_keys=True, separators=(",", ":")).encode())


def test_no_io_side_effects_or_network(ready: dict[str, Any]) -> None:
    with (
        patch("subprocess.run", side_effect=AssertionError("execution")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("write")),
    ):
        raw = issue(ready)
        result = verify(ready, raw)
    assert result.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
