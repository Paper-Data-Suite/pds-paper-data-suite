"""Issue #49: root-authorized, complete dependency-wheel lock.

An exact signed lock grants ONLY wheelhouse inspection authority, never
installation, workspace access, receipt authority or permission to launch.
The trust keyring must originate from independently pinned deployment policy.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import sys
import sysconfig
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.utils import canonicalize_name, parse_wheel_filename

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    verify_registry_document,
)
from paper_data_suite.evergreen_wheelhouse import (
    WheelhouseError,
    WheelhouseInspection,
    WheelPin,
    inspect_closed_wheelhouse,
)

_LOCK_CONTEXT: Final = b"pds-evergreen-wheelhouse-lock-v1\x00"
_MAX_ENVELOPE: Final = 48 * 1024
_MAX_PAYLOAD: Final = 32 * 1024
_MAX_SIGNATURES: Final = 8
_MAX_WHEELS: Final = 128
_SHA256: Final = re.compile(r"[0-9a-f]{64}\Z")
_KEY: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")
_DIST: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_PYTHON: Final = re.compile(r"3\.(?:1[1-9]|[2-9][0-9])\Z")
_PLATFORM: Final = re.compile(r"[a-z][a-z0-9_.-]{1,95}\Z")
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class DependencyLockError(ValueError):
    """Lock metadata, trusted signatures, validity or wheelhouse failed."""


@dataclass(frozen=True, slots=True)
class VerifiedDependencyLock:
    """Signed wheelhouse pinset; never an installed-composition credential."""

    revision: int
    issued_at: datetime
    expires_at: datetime
    registry_payload_sha256: str
    payload_sha256: str
    trust_fingerprint: str
    signers: tuple[str, ...]
    python_minor: str
    platform: str
    roots: tuple[str, ...]
    pins: tuple[WheelPin, ...]
    checkpoint: RevisionCheckpoint


@dataclass(frozen=True, slots=True)
class VerifiedLockedWheelhouse:
    """Root-authorized, byte-inspected wheelhouse, still NOT installed."""

    lock: VerifiedDependencyLock
    inspection: WheelhouseInspection


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise DependencyLockError("duplicate signed lock JSON member")
        output[key] = value
    return output


def _json(raw: bytes, label: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_pairs
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise DependencyLockError(f"invalid {label} JSON") from error
    if not isinstance(parsed, dict):
        raise DependencyLockError(f"{label} must be an object")
    return cast(dict[str, object], parsed)


def _b64(value: object, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 4 * ((maximum + 2) // 3):
        raise DependencyLockError("invalid signed lock base64")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise DependencyLockError("invalid signed lock base64") from error
    if not data or len(data) > maximum or base64.b64encode(data).decode() != value:
        raise DependencyLockError("noncanonical signed lock base64")
    return data


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise DependencyLockError("invalid signed lock UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise DependencyLockError("invalid signed lock UTC timestamp") from error


def _str(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise DependencyLockError(f"invalid signed lock {label}")
    return value


def _strings(value: object, label: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise DependencyLockError(f"invalid signed lock {label} count")
    result = tuple(_str(item, _DIST, label) for item in value)
    normalized = tuple(canonicalize_name(item) for item in result)
    if len(set(normalized)) != len(normalized):
        raise DependencyLockError(f"duplicate signed lock {label}")
    return normalized


def _pins(value: object) -> tuple[WheelPin, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_WHEELS:
        raise DependencyLockError("invalid signed lock wheel count")
    result: list[WheelPin] = []
    distributions: set[str] = set()
    filenames: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or raw.keys() != {"filename", "sha256"}:
            raise DependencyLockError("invalid signed lock wheel claim")
        item = cast(dict[str, object], raw)
        try:
            pin = WheelPin(cast(str, item["filename"]), cast(str, item["sha256"]))
        except (WheelhouseError, TypeError) as error:
            raise DependencyLockError("invalid signed lock wheel pin") from error
        distribution, _, _, _ = parse_wheel_filename(pin.filename)
        if pin.filename.lower() in filenames or str(distribution) in distributions:
            raise DependencyLockError("duplicate signed lock wheel identity")
        filenames.add(pin.filename.lower())
        distributions.add(str(distribution))
        result.append(pin)
    return tuple(result)


def verify_signed_dependency_lock(
    lock_envelope: bytes,
    *,
    registry_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
    registry_checkpoint: RevisionCheckpoint | None = None,
) -> VerifiedDependencyLock:
    """Root-verify domain-separated lock and bind it to a verified registry.

    Does not use caller-created VerifiedRegistryDocument or WheelPin objects as
    signing authority. Checkpoints must come from independently continuous state.
    """
    if type(lock_envelope) is not bytes or not 1 <= len(lock_envelope) <= _MAX_ENVELOPE:
        raise DependencyLockError("signed dependency lock exceeds size limits")
    if not isinstance(trust, TrustedKeyring):
        raise DependencyLockError("independently trusted keyring is required")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise DependencyLockError("aware clock required for signed dependency lock")
    try:
        registry = verify_registry_document(
            registry_envelope, trust=trust, now=now, checkpoint=registry_checkpoint
        )
    except CatalogVerificationError as error:
        raise DependencyLockError("registry signature or freshness invalid") from error
    envelope = _json(lock_envelope, "signed lock envelope")
    if envelope.keys() != {"envelope_version", "payload_b64", "signatures"}:
        raise DependencyLockError("unsupported signed lock envelope")
    if (
        type(envelope["envelope_version"]) is not int
        or envelope["envelope_version"] != 1
    ):
        raise DependencyLockError("unsupported signed lock envelope version")
    body = _b64(envelope["payload_b64"], _MAX_PAYLOAD)
    claims = _json(body, "signed lock payload")
    expected = {
        "record_type",
        "schema_version",
        "revision",
        "issued_at",
        "expires_at",
        "registry_payload_sha256",
        "python_minor",
        "platform",
        "roots",
        "wheels",
    }
    if claims.keys() != expected:
        raise DependencyLockError("unsupported signed lock payload contract")
    if (
        claims["record_type"] != "pds_evergreen_dependency_lock"
        or type(claims["schema_version"]) is not int
        or claims["schema_version"] != 1
    ):
        raise DependencyLockError("unsupported signed lock identity")
    revision = claims["revision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise DependencyLockError("invalid signed lock revision")
    issued = _utc(claims["issued_at"])
    expiry = _utc(claims["expires_at"])
    current = now.astimezone(timezone.utc)
    if not issued <= current < expiry:
        raise DependencyLockError("signed dependency lock expired or not yet valid")
    registry_hash = _str(claims["registry_payload_sha256"], _SHA256, "registry hash")
    if registry_hash != registry.payload_sha256:
        raise DependencyLockError("signed lock targets different registry")
    python_minor = _str(claims["python_minor"], _PYTHON, "python minor")
    platform = _str(claims["platform"], _PLATFORM, "platform")
    if python_minor != f"{sys.version_info.major}.{sys.version_info.minor}":
        raise DependencyLockError("dependency lock targets a different Python")
    if platform != sysconfig.get_platform().lower():
        raise DependencyLockError("dependency lock targets a different platform")
    roots = _strings(claims["roots"], "roots", _MAX_WHEELS)
    pins = _pins(claims["wheels"])
    dig = hashlib.sha256(body).hexdigest()
    if checkpoint is not None:
        if not isinstance(checkpoint, RevisionCheckpoint):
            raise DependencyLockError("invalid previous dependency lock checkpoint")
        if revision < checkpoint.revision:
            raise DependencyLockError("dependency lock revision rollback")
        if revision == checkpoint.revision and dig != checkpoint.payload_sha256:
            raise DependencyLockError("dependency lock revision equivocation")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= _MAX_SIGNATURES:
        raise DependencyLockError("invalid signed dependency lock signature count")
    signers: list[str] = []
    for raw in signatures:
        if not isinstance(raw, dict) or raw.keys() != {
            "key_id",
            "algorithm",
            "signature_b64",
        }:
            raise DependencyLockError("invalid signed lock signature entry")
        signature = cast(dict[str, object], raw)
        signer = _str(signature["key_id"], _KEY, "signer")
        if (
            signer not in trust.root_key_ids
            or signer in signers
            or signature["algorithm"] != "ed25519"
        ):
            raise DependencyLockError("unauthorized signed lock signer")
        public = trust.key(signer)
        if public is None:
            raise DependencyLockError("missing trusted lock signing key")
        signature_bytes = _b64(signature["signature_b64"], 64)
        if len(signature_bytes) != 64:
            raise DependencyLockError("invalid signed lock signature length")
        try:
            Ed25519PublicKey.from_public_bytes(public.public_bytes).verify(
                signature_bytes, _LOCK_CONTEXT + body
            )
        except (InvalidSignature, ValueError) as error:
            raise DependencyLockError(
                "invalid signed lock Ed25519 signature"
            ) from error
        signers.append(signer)
    if len(signers) < trust.root_threshold:
        raise DependencyLockError("insufficient root signatures on dependency lock")
    return VerifiedDependencyLock(
        revision,
        issued,
        expiry,
        registry_hash,
        dig,
        registry.trust_fingerprint,
        tuple(signers),
        python_minor,
        platform,
        roots,
        pins,
        RevisionCheckpoint(revision, dig),
    )


def verify_signed_locked_wheelhouse(
    directory: Path,
    *,
    lock_envelope: bytes,
    registry_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
    registry_checkpoint: RevisionCheckpoint | None = None,
) -> VerifiedLockedWheelhouse:
    """Reverify raw signed documents, then inspect EXACT closed wheel bytes."""
    lock = verify_signed_dependency_lock(
        lock_envelope,
        registry_envelope=registry_envelope,
        trust=trust,
        now=now,
        checkpoint=checkpoint,
        registry_checkpoint=registry_checkpoint,
    )
    try:
        inspection = inspect_closed_wheelhouse(
            directory, pins=lock.pins, roots=lock.roots
        )
    except WheelhouseError as error:
        raise DependencyLockError(
            "signed wheelhouse failed byte/dependency checks"
        ) from error
    return VerifiedLockedWheelhouse(lock, inspection)


__all__ = (
    "DependencyLockError",
    "VerifiedDependencyLock",
    "VerifiedLockedWheelhouse",
    "verify_signed_dependency_lock",
    "verify_signed_locked_wheelhouse",
)
