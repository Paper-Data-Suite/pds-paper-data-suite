"""Issue #49: verified, atomically cached signed catalog snapshots.

Local persisted state is a crash-safe, signed-metadata *cache*, not a trusted
installation receipt or an OS-protected monotonic counter. Same-user deletion,
backup restoration or replacement of this entire cache can defeat local replay
history. Never authorize production launching from this module alone.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_catalog_contracts import (
    CatalogContractError,
    IntegrationClaims,
    ModuleReleaseClaims,
    parse_unverified_envelope,
)
from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    TrustedKeyring,
    VerifiedIntegrationDocument,
    VerifiedModuleDocument,
    VerifiedRegistryDocument,
    verify_integration_document,
    verify_module_document,
    verify_registry_document,
)

_MAX_SNAPSHOT: Final = 4 * 1024 * 1024
_MAX_DOCUMENTS: Final = 32
_RECORD_TYPE: Final = "pds_evergreen_signed_catalog_cache"


class CatalogStateError(ValueError):
    """Stored snapshot invalid, unsafe, stale or conflicting with previous state."""


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Authenticated signed claims only, not installed artifacts/launch approval."""

    registry: VerifiedRegistryDocument
    modules: tuple[VerifiedModuleDocument, ...]
    integrations: tuple[VerifiedIntegrationDocument, ...]
    accepted_at: datetime


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogStateError("duplicate cached JSON member")
        result[key] = value
    return result


def _encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode(value: object, label: str) -> bytes:
    if not isinstance(value, str) or len(value) > 4 * ((192 * 1024 + 2) // 3):
        raise CatalogStateError(f"invalid cached {label}")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise CatalogStateError(f"invalid cached {label}") from error
    if not decoded or len(decoded) > 192 * 1024 or _encode(decoded) != value:
        raise CatalogStateError(f"noncanonical cached {label}")
    return decoded


def _path_guard(path: Path) -> Path:
    if not isinstance(path, Path):
        raise CatalogStateError("catalog cache path must be a Path")
    raw = path.absolute()
    if not raw.parent.is_dir():
        raise CatalogStateError("cache parent directory must already exist")
    if raw.exists() and not raw.is_file():
        raise CatalogStateError("cache target must be a regular file")
    for part in (raw, *raw.parents):
        if part.is_symlink():
            raise CatalogStateError("cache paths may not contain symlinks")
    return raw


def _read_raw(path: Path) -> bytes | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as reader:
            raw = reader.read(_MAX_SNAPSHOT + 1)
    except OSError as error:
        raise CatalogStateError("could not read cached signed metadata") from error
    if not 1 <= len(raw) <= _MAX_SNAPSHOT:
        raise CatalogStateError("cached signed metadata exceeds size limit")
    return raw


def _parse_cache(
    raw: bytes,
) -> tuple[bytes, tuple[bytes, ...], tuple[bytes, ...], datetime, str]:
    try:
        data: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise CatalogStateError("malformed signed catalog cache") from error
    if not isinstance(data, dict) or data.keys() != {
        "record_type",
        "schema_version",
        "registry_envelope_b64",
        "module_envelopes_b64",
        "integration_envelopes_b64",
        "accepted_at",
        "trust_fingerprint",
    }:
        raise CatalogStateError("invalid catalog cache contract")
    document = cast(dict[str, object], data)
    if (
        document["record_type"] != _RECORD_TYPE
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
    ):
        raise CatalogStateError("invalid catalog cache version")
    modules = document["module_envelopes_b64"]
    integrations = document["integration_envelopes_b64"]
    if (
        not isinstance(modules, list)
        or not isinstance(integrations, list)
        or len(modules) > _MAX_DOCUMENTS
        or len(integrations) > _MAX_DOCUMENTS
    ):
        raise CatalogStateError("invalid cached document counts")
    timestamp = document["accepted_at"]
    if (
        not isinstance(timestamp, str)
        or len(timestamp) != 20
        or not timestamp.endswith("Z")
    ):
        raise CatalogStateError("invalid cache acceptance timestamp")
    try:
        accepted = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise CatalogStateError("invalid cache acceptance timestamp") from error
    fingerprint = document["trust_fingerprint"]
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in fingerprint)
    ):
        raise CatalogStateError("invalid cached trust fingerprint")
    return (
        _decode(document["registry_envelope_b64"], "registry"),
        tuple(_decode(item, "module") for item in modules),
        tuple(_decode(item, "integration") for item in integrations),
        accepted,
        fingerprint,
    )


def _historical_time(envelopes: tuple[bytes, ...]) -> datetime:
    """Find one overlap for signed windows; only for validating old history."""
    try:
        windows = [parse_unverified_envelope(raw).claims.window for raw in envelopes]
    except CatalogContractError as error:
        raise CatalogStateError("invalid historical signed envelope") from error
    latest_issue = max(window.issued_at for window in windows)
    earliest_expiry = min(window.expires_at for window in windows)
    if latest_issue >= earliest_expiry:
        raise CatalogStateError("historical catalog never had a shared validity window")
    return latest_issue


def _authenticate(
    registry_envelope: bytes,
    module_envelopes: tuple[bytes, ...],
    integration_envelopes: tuple[bytes, ...],
    *,
    trust: TrustedKeyring,
    now: datetime,
    accepted_at: datetime,
    previous: CatalogSnapshot | None = None,
) -> CatalogSnapshot:
    if not isinstance(trust, TrustedKeyring):
        raise CatalogStateError("an independently pinned keyring is required")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CatalogStateError("an aware validation timestamp is required")
    if (
        len(module_envelopes) > _MAX_DOCUMENTS
        or len(integration_envelopes) > _MAX_DOCUMENTS
    ):
        raise CatalogStateError("too many signed catalog documents")
    previous_modules = (
        {item.claims.component_id: item for item in previous.modules}
        if previous is not None
        else {}
    )
    previous_integrations = (
        {item.claims.feature_id: item for item in previous.integrations}
        if previous is not None
        else {}
    )
    try:
        registry = verify_registry_document(
            registry_envelope,
            trust=trust,
            now=now,
            checkpoint=previous.registry.checkpoint if previous else None,
        )
        modules_list: list[VerifiedModuleDocument] = []
        for blob in module_envelopes:
            claim = parse_unverified_envelope(blob).claims
            if not isinstance(claim, ModuleReleaseClaims):
                raise CatalogStateError("expected signed module-release document")
            prior = previous_modules.get(claim.component_id)
            modules_list.append(
                verify_module_document(
                    blob,
                    registry=registry,
                    trust=trust,
                    now=now,
                    checkpoint=prior.checkpoint if prior else None,
                )
            )
        modules = tuple(modules_list)
        integrations_list: list[VerifiedIntegrationDocument] = []
        for blob in integration_envelopes:
            claim = parse_unverified_envelope(blob).claims
            if not isinstance(claim, IntegrationClaims):
                raise CatalogStateError("expected signed integration document")
            prior_integration = previous_integrations.get(claim.feature_id)
            integrations_list.append(
                verify_integration_document(
                    blob,
                    registry=registry,
                    trust=trust,
                    now=now,
                    checkpoint=prior_integration.checkpoint
                    if prior_integration
                    else None,
                )
            )
        integrations = tuple(integrations_list)
    except (CatalogVerificationError, CatalogContractError, AttributeError) as error:
        raise CatalogStateError("signed catalog failed verification") from error
    module_ids = [item.claims.component_id for item in modules]
    feature_ids = [item.claims.feature_id for item in integrations]
    if len(set(module_ids)) != len(module_ids):
        raise CatalogStateError("duplicate cached module identities")
    if len(set(feature_ids)) != len(feature_ids):
        raise CatalogStateError("duplicate cached feature identities")
    if not previous_modules.keys() <= set(module_ids):
        raise CatalogStateError("catalog update may not silently omit module history")
    if not previous_integrations.keys() <= set(feature_ids):
        raise CatalogStateError("catalog update may not silently omit feature history")
    return CatalogSnapshot(registry, modules, integrations, accepted_at)


def _deserialize(
    raw: bytes, *, trust: TrustedKeyring, now: datetime | None
) -> CatalogSnapshot:
    registry_blob, modules, integrations, accepted, fingerprint = _parse_cache(raw)
    if now is None:
        # Historical validation: signatures and delegated identities are checked
        # at the overlap of their signed windows. This does NOT certify present
        # freshness, and is never used as a production authorization path.
        all_envelopes = (registry_blob, *modules, *integrations)
        check_time = _historical_time(all_envelopes)
        last_expiry = min(
            parse_unverified_envelope(item).claims.window.expires_at
            for item in all_envelopes
        )
        if not check_time <= accepted < last_expiry:
            raise CatalogStateError("historical acceptance outside signed windows")
    else:
        check_time = now
    snapshot = _authenticate(
        registry_blob,
        modules,
        integrations,
        trust=trust,
        now=check_time,
        accepted_at=accepted,
    )
    if snapshot.registry.trust_fingerprint != fingerprint:
        raise CatalogStateError("cached trust fingerprint does not match pinned keys")
    if check_time < accepted and now is not None:
        raise CatalogStateError("local clock predates last accepted catalog")
    return snapshot


def load_catalog_cache(
    path: Path, *, trust: TrustedKeyring, now: datetime
) -> CatalogSnapshot | None:
    """Read and cryptographically REVERIFY cached envelopes at the current time."""
    file_path = _path_guard(path)
    raw = _read_raw(file_path)
    return None if raw is None else _deserialize(raw, trust=trust, now=now)


def save_catalog_cache(
    path: Path,
    *,
    registry_envelope: bytes,
    module_envelopes: tuple[bytes, ...],
    integration_envelopes: tuple[bytes, ...],
    trust: TrustedKeyring,
    now: datetime,
) -> CatalogSnapshot:
    """Validate and atomically replace one locally cached metadata snapshot.

    A lock serializes *cooperating* writers, never provides tamper resistance.
    The cache is not a protected monotonic anchor across full file deletion or
    restore; deployment must solve this before claiming strong rollback defense.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CatalogStateError("an aware validation timestamp is required")
    file_path = _path_guard(path)
    lock_path = file_path.with_name(file_path.name + ".lock")
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise CatalogStateError(
            "catalog cache is locked or cannot be updated"
        ) from error
    temp_path: Path | None = None
    try:
        os.close(fd)
        old_raw = _read_raw(file_path)
        previous = (
            _deserialize(old_raw, trust=trust, now=None)
            if old_raw is not None
            else None
        )
        if previous is not None and now.astimezone(timezone.utc) < previous.accepted_at:
            raise CatalogStateError("local clock rollback before previous acceptance")
        accepted = now.astimezone(timezone.utc).replace(microsecond=0)
        current = _authenticate(
            registry_envelope,
            module_envelopes,
            integration_envelopes,
            trust=trust,
            now=now,
            accepted_at=accepted,
            previous=previous,
        )
        data = {
            "record_type": _RECORD_TYPE,
            "schema_version": 1,
            "trust_fingerprint": current.registry.trust_fingerprint,
            "registry_envelope_b64": _encode(registry_envelope),
            "module_envelopes_b64": [_encode(blob) for blob in module_envelopes],
            "integration_envelopes_b64": [
                _encode(blob) for blob in integration_envelopes
            ],
            "accepted_at": accepted.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        serialized = (
            json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(serialized) > _MAX_SNAPSHOT:
            raise CatalogStateError("catalog snapshot exceeds cache size limit")
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=file_path.name + ".", suffix=".tmp", dir=file_path.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(temp_fd, "wb") as writer:
            writer.write(serialized)
            writer.flush()
            os.fsync(writer.fileno())
        _path_guard(file_path)
        os.replace(temp_path, file_path)
        temp_path = None
        return current
    except OSError as error:
        raise CatalogStateError(
            "could not atomically update signed catalog cache"
        ) from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


__all__ = (
    "CatalogSnapshot",
    "CatalogStateError",
    "load_catalog_cache",
    "save_catalog_cache",
)
