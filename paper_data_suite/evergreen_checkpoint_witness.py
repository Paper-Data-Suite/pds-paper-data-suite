"""Issue #49 Slice 33: challenge-bound, signed external receipt head observation.

This verifier does NOT implement an independent append-only witness, protect a
pinned key, certify a live installed environment, or authorize launching.
The transport and public key must be provisioned independently of local software.
Normal teacher launches MUST NOT depend on live network access to this API.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final, Protocol, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    ExternallyPinnedReceiptHead,
    PinnedReceiptObservation,
    verify_externally_pinned_receipt,
)

_MAX_REPLY: Final = 8192
_MAX_PAYLOAD: Final = 4096
_MAX_CHALLENGE: Final = 1024
_MAX_WINDOW_SECONDS: Final = 300
_MAX_CHALLENGE_AGE_SECONDS: Final = 120
_ID: Final = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
_INSTALL: Final = re.compile(r"[0-9a-f]{32}\Z")
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_TIME: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class CheckpointWitnessError(ValueError):
    """Untrusted or stale witness identity, response, or receipt continuity."""


class CheckpointWitnessTransport(Protocol):
    """Externally provisioned transport (MUST enforce monotonic CAS at witness)."""

    def __call__(self, challenge: bytes, /) -> bytes: ...


@dataclass(frozen=True, slots=True)
class IssuedWitnessChallenge:
    """Locally fresh request; an arbitrary caller-built object is not authority."""

    bytes: bytes
    installation_id: str
    nonce_sha256: str
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class WitnessReceiptObservation:
    """Fresh signed witness statement and matching receipt, NOT launch authority."""

    receipt: PinnedReceiptObservation
    witness_id: str
    installation_id: str
    witness_revision: int
    challenge_sha256: str
    signed_payload_sha256: str
    signed_expires_at: datetime


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise CheckpointWitnessError("duplicate witness JSON member")
        data[key] = value
    return data


def _json(raw: bytes, bound: int) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= bound:
        raise CheckpointWitnessError("witness message size invalid")
    try:
        value: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except CheckpointWitnessError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise CheckpointWitnessError("malformed witness JSON") from error
    if not isinstance(value, dict):
        raise CheckpointWitnessError("witness message must be an object")
    document = cast(dict[str, object], value)
    if _canonical(document) != raw:
        raise CheckpointWitnessError("noncanonical witness JSON")
    return document


def _canonical(document: dict[str, object]) -> bytes:
    return json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _string(value: object, pattern: re.Pattern[str], name: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise CheckpointWitnessError(f"invalid witness {name}")
    return value


def _time(value: object) -> datetime:
    raw = _string(value, _TIME, "timestamp")
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise CheckpointWitnessError("invalid witness timestamp") from error


def _utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CheckpointWitnessError("witness clock must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    if utc.microsecond:
        raise CheckpointWitnessError("witness clock must have whole seconds")
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _positive(value: object, name: str) -> int:
    if type(value) is not int or not 1 <= value <= 2**53 - 1:
        raise CheckpointWitnessError(f"invalid witness {name}")
    return value


def _head(generation: object, digest: object) -> ExternallyPinnedReceiptHead:
    try:
        return ExternallyPinnedReceiptHead(
            _positive(generation, "generation"),
            _string(digest, _HASH, "receipt digest"),
        )
    except ActiveReceiptError as error:
        raise CheckpointWitnessError("invalid witness receipt head") from error


def issue_witness_challenge(
    *, installation_id: str, now: datetime
) -> IssuedWitnessChallenge:
    """Generate an unpredictable nonce for one independently provisioned witness.

    The challenge is not authorization. Do not construct a fixed test nonce in
    production, save a challenge for reuse, or accept untrusted witness keys.
    """
    installation = _string(installation_id, _INSTALL, "installation id")
    stamp = _utc(now)
    nonce = secrets.token_bytes(32)
    if len(nonce) != 32:
        raise CheckpointWitnessError("unavailable secure challenge randomness")
    raw = _canonical(
        {
            "record_type": "pds_external_checkpoint_challenge",
            "schema_version": 1,
            "installation_id": installation,
            "nonce_b64": base64.b64encode(nonce).decode("ascii"),
            "issued_at": stamp,
        }
    )
    return IssuedWitnessChallenge(
        raw,
        installation,
        hashlib.sha256(nonce).hexdigest(),
        now.astimezone(timezone.utc),
    )


def _parse_challenge(challenge: IssuedWitnessChallenge, now: datetime) -> str:
    if not isinstance(challenge, IssuedWitnessChallenge):
        raise CheckpointWitnessError("missing issued challenge")
    data = _json(challenge.bytes, _MAX_CHALLENGE)
    if (
        data.keys()
        != {
            "record_type",
            "schema_version",
            "installation_id",
            "nonce_b64",
            "issued_at",
        }
        or data["record_type"] != "pds_external_checkpoint_challenge"
        or (type(data["schema_version"]) is not int or data["schema_version"] != 1)
    ):
        raise CheckpointWitnessError("invalid challenge schema")
    installation = _string(data["installation_id"], _INSTALL, "installation id")
    if installation != challenge.installation_id:
        raise CheckpointWitnessError("changed challenge installation id")
    nonce = _decode(data["nonce_b64"], 32)
    if hashlib.sha256(nonce).hexdigest() != challenge.nonce_sha256:
        raise CheckpointWitnessError("changed challenge nonce")
    stamp = _time(data["issued_at"])
    if stamp != challenge.issued_at or not (
        timedelta(0)
        <= now.astimezone(timezone.utc) - stamp
        <= timedelta(seconds=_MAX_CHALLENGE_AGE_SECONDS)
    ):
        raise CheckpointWitnessError("stale or future witness challenge")
    return installation


def _decode(value: object, size: int) -> bytes:
    if type(value) is not str:
        raise CheckpointWitnessError("invalid witness base64")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise CheckpointWitnessError("invalid witness base64") from error
    if len(result) != size or base64.b64encode(result).decode("ascii") != value:
        raise CheckpointWitnessError("noncanonical witness base64")
    return result


def verify_witness_statement(
    *,
    challenge: IssuedWitnessChallenge,
    signed_reply: bytes,
    receipt_bytes: bytes,
    pinned_public_key: bytes,
    expected_witness_id: str,
    now: datetime,
    minimum_witness_revision: int | None = None,
) -> WitnessReceiptObservation:
    """Authenticate a fresh external response then bind it to local receipt bytes.

    The pinned key must be provisioned through an independent trust channel.
    The witness must enforce monotonic state, challenge freshness, and CAS;
    signatures alone cannot prove that the witness does so.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CheckpointWitnessError("invalid witness verification clock")
    expected = _string(expected_witness_id, _ID, "witness id")
    installation = _parse_challenge(challenge, now)
    if type(pinned_public_key) is not bytes or len(pinned_public_key) != 32:
        raise CheckpointWitnessError("missing independently pinned witness key")
    if minimum_witness_revision is not None:
        _positive(minimum_witness_revision, "minimum revision")
    envelope = _json(signed_reply, _MAX_REPLY)
    if envelope.keys() != {"payload_b64", "signature_b64"}:
        raise CheckpointWitnessError("invalid signed witness envelope")
    payload = _decode_variable(envelope["payload_b64"], _MAX_PAYLOAD)
    signature = _decode(envelope["signature_b64"], 64)
    try:
        Ed25519PublicKey.from_public_bytes(pinned_public_key).verify(signature, payload)
    except (ValueError, InvalidSignature) as error:
        raise CheckpointWitnessError("witness signature invalid") from error
    data = _json(payload, _MAX_PAYLOAD)
    if (
        data.keys()
        != {
            "record_type",
            "schema_version",
            "witness_id",
            "installation_id",
            "challenge_sha256",
            "witness_revision",
            "head_generation",
            "head_sha256",
            "predecessor_generation",
            "predecessor_sha256",
            "issued_at",
            "expires_at",
        }
        or data["record_type"] != "pds_external_checkpoint_statement"
        or (type(data["schema_version"]) is not int or data["schema_version"] != 1)
    ):
        raise CheckpointWitnessError("invalid witness statement schema")
    if (
        _string(data["witness_id"], _ID, "witness id") != expected
        or _string(data["installation_id"], _INSTALL, "installation id") != installation
        or _string(data["challenge_sha256"], _HASH, "challenge digest")
        != hashlib.sha256(challenge.bytes).hexdigest()
    ):
        raise CheckpointWitnessError("witness statement identity mismatch")
    revision = _positive(data["witness_revision"], "revision")
    if minimum_witness_revision is not None and revision < minimum_witness_revision:
        raise CheckpointWitnessError("witness revision rollback")
    issued, expires = _time(data["issued_at"]), _time(data["expires_at"])
    instant = now.astimezone(timezone.utc)
    if not (
        issued <= instant <= expires
        and timedelta(0) < expires - issued <= timedelta(seconds=_MAX_WINDOW_SECONDS)
        and issued >= challenge.issued_at
    ):
        raise CheckpointWitnessError("stale, future or excessive witness validity")
    head = _head(data["head_generation"], data["head_sha256"])
    if (data["predecessor_generation"] is None) != (data["predecessor_sha256"] is None):
        raise CheckpointWitnessError("incomplete witness predecessor")
    predecessor = (
        None
        if data["predecessor_generation"] is None
        else _head(data["predecessor_generation"], data["predecessor_sha256"])
    )
    try:
        pinned = verify_externally_pinned_receipt(
            receipt_bytes, head=head, predecessor=predecessor
        )
    except ActiveReceiptError as error:
        raise CheckpointWitnessError("witness receipt continuity mismatch") from error
    return WitnessReceiptObservation(
        pinned,
        expected,
        installation,
        revision,
        hashlib.sha256(challenge.bytes).hexdigest(),
        hashlib.sha256(payload).hexdigest(),
        expires,
    )


def _decode_variable(value: object, maximum: int) -> bytes:
    if type(value) is not str or len(value) > maximum * 2:
        raise CheckpointWitnessError("invalid witness payload encoding")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise CheckpointWitnessError("invalid witness payload encoding") from error
    if not 1 <= len(data) <= maximum or base64.b64encode(data).decode("ascii") != value:
        raise CheckpointWitnessError("invalid witness payload encoding")
    return data


def query_checkpoint_witness(
    transport: CheckpointWitnessTransport,
    *,
    installation_id: str,
    receipt_bytes: bytes,
    pinned_public_key: bytes,
    expected_witness_id: str,
    now: datetime,
    minimum_witness_revision: int | None = None,
) -> WitnessReceiptObservation:
    """Issue a fresh request; transport is independently configured by caller.

    No default network transport or private signing key is provided. Caller
    must not use this at ordinary offline teacher-launch time.
    """
    if not callable(transport):
        raise CheckpointWitnessError("no provisioned checkpoint witness")
    challenge = issue_witness_challenge(installation_id=installation_id, now=now)
    try:
        response = transport(challenge.bytes)
    except Exception as error:
        raise CheckpointWitnessError("checkpoint witness unavailable") from error
    return verify_witness_statement(
        challenge=challenge,
        signed_reply=response,
        receipt_bytes=receipt_bytes,
        pinned_public_key=pinned_public_key,
        expected_witness_id=expected_witness_id,
        now=now,
        minimum_witness_revision=minimum_witness_revision,
    )


__all__ = (
    "CheckpointWitnessError",
    "CheckpointWitnessTransport",
    "IssuedWitnessChallenge",
    "WitnessReceiptObservation",
    "issue_witness_challenge",
    "query_checkpoint_witness",
    "verify_witness_statement",
)
