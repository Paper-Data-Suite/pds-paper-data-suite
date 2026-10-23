"""Issue #49 Slice 50: signed, non-authorizing witness-service observation.

A trusted service may sign a bounded observation of its stopped-writer state.
Verification binds a fresh challenge to the exact witness request and service
key pinned OUTSIDE this envelope. Neither issuing nor verifying this record
confers local activation, rollback, receipt-commit, or launch authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Final, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)


class RecoveryServiceAttestationError(ValueError):
    """Service observation cannot be authenticated for this bounded request."""


@dataclass(frozen=True, slots=True)
class VerifiedRecoveryServiceAttestation:
    """Authenticated *statement* only; never proof of protected deployment."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    witness_revision: int
    successor_generation: int
    issued_at: datetime
    expires_at: datetime
    status: str = "SERVICE_SIGNED_SUCCESSOR_OBSERVATION_ONLY"
    authority: str = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"


_CONTEXT: Final = b"pds-evergreen-service-recovery-observation-v1\x00"
_RECORD_TYPE: Final = "pds_evergreen_service_recovery_observation"
_SERVICE_STATUS: Final = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
_AUTHORITY: Final = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
_MAX_PAYLOAD: Final = 4096
_MAX_ENVELOPE: Final = 8192
_WINDOW_SECONDS: Final = 60
_FIELDS: Final = frozenset(
    {
        "installation_id",
        "transaction_id",
        "request_sha256",
        "predecessor_sha256",
        "successor_sha256",
        "witness_id",
        "witness_revision",
        "successor_generation",
        "service_status",
        "authority",
        "issued_at",
        "expires_at",
        "challenge_b64",
    }
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise RecoveryServiceAttestationError("duplicate signed JSON field")
        out[key] = value
    return out


def _canonical(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise RecoveryServiceAttestationError("invalid observation JSON") from error


def _json_object(raw: bytes, *, limit: int) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= limit:
        raise RecoveryServiceAttestationError("invalid observation byte length")
    try:
        parsed: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except RecoveryServiceAttestationError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise RecoveryServiceAttestationError("malformed signed observation") from error
    if not isinstance(parsed, dict):
        raise RecoveryServiceAttestationError("signed observation is not an object")
    data = cast(dict[str, object], parsed)
    if _canonical(data) != raw:
        raise RecoveryServiceAttestationError("noncanonical signed observation")
    return data


def _b64(value: object, limit: int) -> bytes:
    if type(value) is not str or not 1 <= len(value) <= 4 * ((limit + 2) // 3):
        raise RecoveryServiceAttestationError("invalid observation base64")
    try:
        out = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise RecoveryServiceAttestationError("invalid observation base64") from error
    if not 1 <= len(out) <= limit or base64.b64encode(out).decode("ascii") != value:
        raise RecoveryServiceAttestationError("noncanonical observation base64")
    return out


def _time(value: object) -> datetime:
    if type(value) is not str:
        raise RecoveryServiceAttestationError("invalid signed observation time")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise RecoveryServiceAttestationError(
            "invalid signed observation time"
        ) from error
    when = parsed.replace(tzinfo=timezone.utc)
    if when.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise RecoveryServiceAttestationError("noncanonical signed observation time")
    return when


def _now(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise RecoveryServiceAttestationError("aware whole-second clock required")
    return value.astimezone(timezone.utc)


def _challenge(value: bytes) -> str:
    if type(value) is not bytes or len(value) != 32:
        raise RecoveryServiceAttestationError("fresh 32-byte challenge required")
    return base64.b64encode(value).decode("ascii")


def _identity(request: WitnessCommitRequest) -> tuple[str, str, int, int]:
    if not isinstance(request, WitnessCommitRequest):
        raise RecoveryServiceAttestationError("invalid witness commit request")
    try:
        canonical = serialize_witness_commit_request(request)
        previous = parse_untrusted_active_receipt(request.previous_receipt_bytes)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    except (WitnessCommitProtocolError, ActiveReceiptError, ValueError) as error:
        raise RecoveryServiceAttestationError("invalid witnessed successor") from error
    if (
        successor.generation != previous.generation + 1
        or successor.previous_receipt_sha256 != request.predecessor_sha256
    ):
        raise RecoveryServiceAttestationError("successor chain is inconsistent")
    return (
        _sha(canonical),
        successor.transaction_id,
        successor.generation,
        request.expected_witness_revision + 1,
    )


def issue_service_recovery_attestation(
    request: WitnessCommitRequest,
    service: WitnessWriterQuiescenceState,
    *,
    challenge: bytes,
    observed_at: datetime,
    sign: Callable[[bytes], bytes],
) -> bytes:
    """Service-only signing adapter; external deployment must protect its key.

    The caller must obtain `service` from an independently controlled, durable
    quiescence ledger with real CAS writer isolation and supervision. This
    Python function CANNOT prove that the callback or ledger is independent.
    """
    request_sha, transaction, generation, revision = _identity(request)
    observed = _now(observed_at)
    nonce = _challenge(challenge)
    if (
        not isinstance(service, WitnessWriterQuiescenceState)
        or service.installation_id != request.installation_id
        or service.request_sha256 != request_sha
        or service.status != _SERVICE_STATUS
        or service.authority != _AUTHORITY
        or type(service.signed_revision) is not int
        or service.signed_revision != revision
        or service.signed_head_sha256 != request.successor_sha256
        or not callable(sign)
    ):
        raise RecoveryServiceAttestationError(
            "service state does not confirm successor"
        )
    until = observed + timedelta(seconds=_WINDOW_SECONDS)
    payload: dict[str, object] = {
        "installation_id": request.installation_id,
        "transaction_id": transaction,
        "request_sha256": request_sha,
        "predecessor_sha256": request.predecessor_sha256,
        "successor_sha256": request.successor_sha256,
        "witness_id": request.witness_id,
        "witness_revision": revision,
        "successor_generation": generation,
        "service_status": _SERVICE_STATUS,
        "authority": _AUTHORITY,
        "issued_at": observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "challenge_b64": nonce,
    }
    raw = _canonical(payload)
    if len(raw) > _MAX_PAYLOAD:
        raise RecoveryServiceAttestationError("service observation is too large")
    try:
        signature = sign(_CONTEXT + raw)
    except Exception as error:
        raise RecoveryServiceAttestationError("service signer unavailable") from error
    if type(signature) is not bytes or len(signature) != 64:
        raise RecoveryServiceAttestationError("invalid service signature")
    envelope = _canonical(
        {
            "record_type": _RECORD_TYPE,
            "schema_version": 1,
            "payload_b64": base64.b64encode(raw).decode("ascii"),
            "signature_b64": base64.b64encode(signature).decode("ascii"),
        }
    )
    if len(envelope) > _MAX_ENVELOPE:
        raise RecoveryServiceAttestationError("service envelope is too large")
    return envelope


def verify_service_recovery_attestation(
    raw: bytes,
    *,
    request: WitnessCommitRequest,
    challenge: bytes,
    pinned_service_public_key: bytes,
    now: datetime,
) -> VerifiedRecoveryServiceAttestation:
    """Verify independent service signature and request-specific freshness.

    Caller MUST generate a new unpredictable challenge, pin the service key
    outside the record and independently enforce all physical install checks.
    An authenticated service observation is NEVER activation authorization.
    """
    request_sha, transaction, generation, revision = _identity(request)
    nonce = _challenge(challenge)
    current = _now(now)
    if (
        type(pinned_service_public_key) is not bytes
        or len(pinned_service_public_key) != 32
    ):
        raise RecoveryServiceAttestationError("missing pinned service key")
    envelope = _json_object(raw, limit=_MAX_ENVELOPE)
    if (
        envelope.keys()
        != {"record_type", "schema_version", "payload_b64", "signature_b64"}
        or envelope["record_type"] != _RECORD_TYPE
        or type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != 1
    ):
        raise RecoveryServiceAttestationError("unsupported service envelope")
    payload_raw = _b64(envelope["payload_b64"], _MAX_PAYLOAD)
    signature = _b64(envelope["signature_b64"], 64)
    if len(signature) != 64:
        raise RecoveryServiceAttestationError("bad service signature length")
    try:
        key = Ed25519PublicKey.from_public_bytes(pinned_service_public_key)
        key.verify(signature, _CONTEXT + payload_raw)
    except (InvalidSignature, ValueError) as error:
        raise RecoveryServiceAttestationError(
            "service signature not trusted"
        ) from error
    payload = _json_object(payload_raw, limit=_MAX_PAYLOAD)
    if payload.keys() != _FIELDS:
        raise RecoveryServiceAttestationError("unexpected service statement fields")
    issued = _time(payload["issued_at"])
    expires = _time(payload["expires_at"])
    if (
        payload["installation_id"] != request.installation_id
        or payload["transaction_id"] != transaction
        or payload["request_sha256"] != request_sha
        or payload["predecessor_sha256"] != request.predecessor_sha256
        or payload["successor_sha256"] != request.successor_sha256
        or payload["witness_id"] != request.witness_id
        or type(payload["witness_revision"]) is not int
        or payload["witness_revision"] != revision
        or type(payload["successor_generation"]) is not int
        or payload["successor_generation"] != generation
        or payload["service_status"] != _SERVICE_STATUS
        or payload["authority"] != _AUTHORITY
        or payload["challenge_b64"] != nonce
        or issued > current
        or current >= expires
        or expires - issued != timedelta(seconds=_WINDOW_SECONDS)
    ):
        raise RecoveryServiceAttestationError(
            "service observation is stale or bound to another request"
        )
    return VerifiedRecoveryServiceAttestation(
        request.installation_id,
        transaction,
        request_sha,
        request.successor_sha256,
        revision,
        generation,
        issued,
        expires,
    )


__all__ = (
    "RecoveryServiceAttestationError",
    "VerifiedRecoveryServiceAttestation",
    "issue_service_recovery_attestation",
    "verify_service_recovery_attestation",
)
