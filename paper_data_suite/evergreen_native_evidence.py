"""Issue #49: root-signed exact native-executable evidence for a staged venv.

Read-only, stage-specific binary observations. Only an independently pinned
root quorum can authorize the exact expected bytes. This does NOT activate an
environment or certify ongoing integrity, provenance of a Python distribution,
or the safety of executing a binary. Production signing is not provisioned.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    inspect_staged_virtualenv,
)

_CONTEXT: Final = b"pds-evergreen-staged-native-evidence-v1\x00"
_MAX_ENVELOPE: Final = 32 * 1024
_MAX_PAYLOAD: Final = 24 * 1024
_MAX_BINARY: Final = 64 * 1024 * 1024
_MAX_FILES: Final = 64
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_PATH: Final = re.compile(r"(?:Scripts|bin)/[A-Za-z][A-Za-z0-9._-]{0,79}\Z")
_KEY: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")


class NativeEvidenceError(ValueError):
    """Signed binary inventory or exact staged executable bytes disagree."""


@dataclass(frozen=True, slots=True)
class ObservedNativeBinary:
    """Exact digest observed at one point in time, not permission to execute."""

    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class VerifiedNativeEvidence:
    """Root-authorized byte comparison, not an installed-composition receipt."""

    transaction_id: str
    stage_root: Path
    revision: int
    payload_sha256: str
    signers: tuple[str, ...]
    binaries: tuple[ObservedNativeBinary, ...]
    checkpoint: RevisionCheckpoint


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise NativeEvidenceError("duplicate signed native evidence JSON member")
        result[name] = value
    return result


def _object(data: bytes, label: str) -> dict[str, object]:
    try:
        value: object = json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    except NativeEvidenceError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise NativeEvidenceError(f"invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise NativeEvidenceError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _decode(value: object, bound: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 4 * ((bound + 2) // 3):
        raise NativeEvidenceError("invalid native evidence base64")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise NativeEvidenceError("invalid native evidence base64") from error
    if not raw or len(raw) > bound or base64.b64encode(raw).decode("ascii") != value:
        raise NativeEvidenceError("noncanonical native evidence base64")
    return raw


def _value(value: object, expression: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not expression.fullmatch(value):
        raise NativeEvidenceError(f"invalid native evidence {label}")
    return value


def _time(value: object) -> datetime:
    text = _value(value, _UTC, "UTC timestamp")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise NativeEvidenceError("invalid native evidence timestamp") from error


def _pins(value: object) -> tuple[ObservedNativeBinary, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_FILES:
        raise NativeEvidenceError("invalid native binary inventory count")
    result: list[ObservedNativeBinary] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or item.keys() != {
            "relative_path",
            "sha256",
            "size",
        }:
            raise NativeEvidenceError("invalid native binary entry")
        claim = cast(dict[str, object], item)
        name = _value(claim["relative_path"], _PATH, "binary path")
        if name.lower() in names:
            raise NativeEvidenceError("duplicate or case-conflicting executable name")
        names.add(name.lower())
        size = claim["size"]
        if type(size) is not int or not 1 <= size <= _MAX_BINARY:
            raise NativeEvidenceError("invalid native binary size")
        result.append(
            ObservedNativeBinary(name, _value(claim["sha256"], _HASH, "SHA-256"), size)
        )
    return tuple(result)


def _digest(path: Path, *, stage_root: Path, size: int) -> str:
    """Hash regular bytes without following Windows reparse points or symlinks."""
    try:
        parent = stage_root
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
        ):
            raise NativeEvidenceError("unsafe staged executable root")
        relative = path.relative_to(stage_root)
        for segment in relative.parts[:-1]:
            parent = parent / segment
            info = parent.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise NativeEvidenceError("staged executable parent is a link")
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
        ):
            raise NativeEvidenceError("staged executable is not a regular file")
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_BINARY:
                    raise NativeEvidenceError("staged executable exceeds size limit")
                digest.update(chunk)
        if total != size:
            raise NativeEvidenceError("signed executable size mismatch")
        return digest.hexdigest()
    except OSError as error:
        raise NativeEvidenceError(
            "staged executable cannot be checked safely"
        ) from error


def verify_signed_staged_native_evidence(
    stage_root: Path,
    wheelhouse: Path,
    *,
    evidence_envelope: bytes,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> VerifiedNativeEvidence:
    """Reverify prepared stage and root-signed native hashes, without execution.

    `layout` exists for deterministic cross-platform tests, not authorization.
    The caller must provision actual root keys and a publisher-generated signed
    inventory independently of the staged files being checked.
    """
    if (
        type(evidence_envelope) is not bytes
        or not 1 <= len(evidence_envelope) <= _MAX_ENVELOPE
    ):
        raise NativeEvidenceError("native evidence exceeds envelope bound")
    if (
        not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        raise NativeEvidenceError("trusted keyring and aware clock required")
    try:
        stage = inspect_staged_virtualenv(
            stage_root,
            wheelhouse,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
        prepared = parse_unverified_prepared_record(prepared_record)
    except (StagedRuntimeError, PreparedRecordError) as error:
        raise NativeEvidenceError(
            "staged virtualenv or prepared record failed"
        ) from error
    envelope = _object(evidence_envelope, "native evidence envelope")
    if envelope.keys() != {"envelope_version", "payload_b64", "signatures"}:
        raise NativeEvidenceError("unknown native evidence envelope fields")
    if (
        type(envelope["envelope_version"]) is not int
        or envelope["envelope_version"] != 1
    ):
        raise NativeEvidenceError("unsupported native evidence envelope")
    payload = _decode(envelope["payload_b64"], _MAX_PAYLOAD)
    data = _object(payload, "native evidence payload")
    expected = {
        "record_type",
        "schema_version",
        "revision",
        "issued_at",
        "expires_at",
        "transaction_id",
        "registry_payload_sha256",
        "lock_payload_sha256",
        "trust_fingerprint",
        "python_minor",
        "platform",
        "files",
    }
    if data.keys() != expected:
        raise NativeEvidenceError("unknown native evidence payload fields")
    if (
        data["record_type"] != "pds_evergreen_staged_native_evidence"
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise NativeEvidenceError("unsupported native evidence identity")
    revision = data["revision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise NativeEvidenceError("invalid native evidence revision")
    issued, expiry = _time(data["issued_at"]), _time(data["expires_at"])
    if not issued <= now.astimezone(timezone.utc) < expiry:
        raise NativeEvidenceError("native evidence expired or not yet valid")
    for name, correct, pattern in (
        ("transaction_id", prepared.transaction_id, _TX),
        ("registry_payload_sha256", prepared.registry_payload_sha256, _HASH),
        ("lock_payload_sha256", prepared.lock_payload_sha256, _HASH),
        ("trust_fingerprint", prepared.trust_fingerprint, _HASH),
    ):
        if _value(data[name], pattern, name) != correct:
            raise NativeEvidenceError(f"native evidence {name} binding mismatch")
    if (
        data["python_minor"] != prepared.python_minor
        or data["platform"] != prepared.platform
    ):
        raise NativeEvidenceError("native evidence Python/platform mismatch")
    pins = _pins(data["files"])
    is_windows = layout == "windows" or (layout is None and sys.platform == "win32")
    prefix = "Scripts" if is_windows else "bin"
    required = {f"{prefix}/{'python.exe' if prefix == 'Scripts' else 'python'}"}
    for launcher in stage.console_launchers:
        required.add(launcher.path.relative_to(stage.stage_root).as_posix())
    optional_pythonw = stage.stage_root / "Scripts/pythonw.exe"
    if prefix == "Scripts" and optional_pythonw.exists():
        required.add("Scripts/pythonw.exe")
    actual = {pin.relative_path for pin in pins}
    if actual != required:
        raise NativeEvidenceError("signed native inventory missing or adds executable")
    digest = hashlib.sha256(payload).hexdigest()
    if checkpoint is not None:
        if not isinstance(checkpoint, RevisionCheckpoint):
            raise NativeEvidenceError("invalid native evidence checkpoint")
        if revision < checkpoint.revision:
            raise NativeEvidenceError("native evidence revision rollback")
        if revision == checkpoint.revision and digest != checkpoint.payload_sha256:
            raise NativeEvidenceError("native evidence equivocation")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 8:
        raise NativeEvidenceError("invalid native evidence signature count")
    signers: list[str] = []
    for raw in signatures:
        if not isinstance(raw, dict) or raw.keys() != {
            "key_id",
            "algorithm",
            "signature_b64",
        }:
            raise NativeEvidenceError("invalid native evidence signature entry")
        signature = cast(dict[str, object], raw)
        signer = _value(signature["key_id"], _KEY, "signer")
        if (
            signer not in trust.root_key_ids
            or signer in signers
            or signature["algorithm"] != "ed25519"
        ):
            raise NativeEvidenceError(
                "unauthorized or duplicate native evidence signer"
            )
        key = trust.key(signer)
        if key is None:
            raise NativeEvidenceError("missing trusted native evidence key")
        sig = _decode(signature["signature_b64"], 64)
        if len(sig) != 64:
            raise NativeEvidenceError("invalid native evidence signature length")
        try:
            Ed25519PublicKey.from_public_bytes(key.public_bytes).verify(
                sig, _CONTEXT + payload
            )
        except (InvalidSignature, ValueError) as error:
            raise NativeEvidenceError(
                "invalid native evidence Ed25519 signature"
            ) from error
        signers.append(signer)
    if len(signers) < trust.root_threshold:
        raise NativeEvidenceError("native evidence root-signature quorum not met")
    for pin in pins:
        actual_hash = _digest(
            stage.stage_root / pin.relative_path,
            stage_root=stage.stage_root,
            size=pin.size,
        )
        if actual_hash != pin.sha256:
            raise NativeEvidenceError("signed staged executable digest mismatch")
    return VerifiedNativeEvidence(
        prepared.transaction_id,
        stage.stage_root,
        revision,
        digest,
        tuple(signers),
        pins,
        RevisionCheckpoint(revision, digest),
    )


__all__ = (
    "NativeEvidenceError",
    "ObservedNativeBinary",
    "VerifiedNativeEvidence",
    "verify_signed_staged_native_evidence",
)
