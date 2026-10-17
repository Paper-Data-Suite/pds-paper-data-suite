"""Issue #49 unsigned views of future signed catalog documents.

Security boundary: PARSING IS NOT AUTHENTICATION. Returned values are never
trusted release identities, launch approvals, or verified attestations. They
must be checked by a separate cryptographic verifier and delegated trust policy.
No network, disk access, subprocess, or imported module execution occurs here.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, TypeAlias, cast

_MAX_ENVELOPE_BYTES: Final = 192 * 1024
_MAX_PAYLOAD_BYTES: Final = 128 * 1024
_MAX_SIGNATURES: Final = 8
_MAX_COMPONENTS: Final = 32
_MAX_RELEASES: Final = 64
_MAX_DEPENDENCIES: Final = 96
_ID_RE: Final = re.compile(r"[a-z][a-z0-9_-]{1,47}\Z")
_KEY_RE: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")
_DIST_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_REPO_RE: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_VERSION_RE: Final = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.post[0-9]+)?\Z")
_WHEEL_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,180}\.whl\Z")
_HASH_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_EP_RE: Final = re.compile(r"[a-z][a-z0-9_-]{1,47}\Z")
_TARGET_RE: Final = re.compile(r"[a-zA-Z_][\w.]*(?::[a-zA-Z_][\w.]*)\Z", re.ASCII)
_FEATURE_RE: Final = re.compile(r"[a-z][a-z0-9_.-]{2,95}\Z")


class CatalogContractError(ValueError):
    """A bounded, unsigned catalog document or signature envelope is malformed."""


@dataclass(frozen=True, slots=True)
class MetadataWindow:
    """Author-supplied validity window; checking current time is NOT parsing."""

    revision: int
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizedModuleClaim:
    """UNVERIFIED registry claim delegating one module to signer key IDs."""

    component_id: str
    repository: str
    distribution: str
    signing_key_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegistryClaims:
    """UNVERIFIED registry claims; cryptographic root authority is external."""

    window: MetadataWindow
    modules: tuple[AuthorizedModuleClaim, ...]
    integration_signing_key_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseClaim:
    """UNVERIFIED exact artifact authorization claim, never a launch permit."""

    version: str
    tag: str
    wheel: str
    sha256: str
    requires_python: str
    requires_dist: tuple[str, ...]
    console_script: str
    console_target: str
    revoked: bool


@dataclass(frozen=True, slots=True)
class ModuleReleaseClaims:
    """UNVERIFIED module-publisher claims requiring delegation validation."""

    window: MetadataWindow
    component_id: str
    repository: str
    distribution: str
    releases: tuple[ReleaseClaim, ...]


@dataclass(frozen=True, slots=True)
class ExactArtifactClaim:
    """UNVERIFIED precise artifact participation in one integration result."""

    component_id: str
    wheel_sha256: str


@dataclass(frozen=True, slots=True)
class IntegrationClaims:
    """UNVERIFIED exact cross-module attestation claims."""

    window: MetadataWindow
    feature_id: str
    evidence_sha256: str
    result: str
    artifacts: tuple[ExactArtifactClaim, ...]
    python_minors: tuple[str, ...]
    platforms: tuple[str, ...]


CatalogClaims: TypeAlias = RegistryClaims | ModuleReleaseClaims | IntegrationClaims


@dataclass(frozen=True, slots=True)
class UnverifiedSignature:
    """Parsed 64-byte Ed25519 signature, NOT a valid-signature assertion."""

    key_id: str
    signature: bytes


@dataclass(frozen=True, slots=True)
class UnverifiedEnvelope:
    """All data remains untrusted until an independent verifier authorizes it."""

    payload_bytes: bytes
    claims: CatalogClaims
    signatures: tuple[UnverifiedSignature, ...]


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise CatalogContractError("duplicate JSON member")
        result[name] = value
    return result


def _json_object(data: bytes, label: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(
            data.decode("utf-8"), object_pairs_hook=_reject_duplicates
        )
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise CatalogContractError(f"invalid {label} JSON") from error
    return _object(parsed, label)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CatalogContractError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise CatalogContractError(f"{label} contains non-string key")
    return cast(dict[str, object], value)


def _keys(data: dict[str, object], expected: frozenset[str], label: str) -> None:
    if data.keys() != expected:
        raise CatalogContractError(f"{label} fields do not match contract")


def _string(
    value: object,
    label: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 256,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CatalogContractError(f"invalid {label}")
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise CatalogContractError(f"invalid {label}")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise CatalogContractError(f"invalid {label}")
    return value


def _items(value: object, label: str, maximum: int) -> list[object]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise CatalogContractError(f"invalid {label} count")
    return cast(list[object], value)


def _unique(values: list[str], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise CatalogContractError(f"duplicate {label}")
    return tuple(values)


def _strings(
    value: object, label: str, maximum: int, *, pattern: re.Pattern[str] | None = None
) -> tuple[str, ...]:
    return _unique(
        [
            _string(item, label, pattern=pattern)
            for item in _items(value, label, maximum)
        ],
        label,
    )


def _sequence(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 2**53 - 1:
        raise CatalogContractError(f"invalid {label}")
    return value


def _timestamp(value: object, label: str) -> datetime:
    raw = _string(value, label)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", raw) is None:
        raise CatalogContractError(f"invalid {label}")
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise CatalogContractError(f"invalid {label}") from error


def _window(data: dict[str, object]) -> MetadataWindow:
    revision = _sequence(data["revision"], "revision")
    issued_at = _timestamp(data["issued_at"], "issued_at")
    expires_at = _timestamp(data["expires_at"], "expires_at")
    if expires_at <= issued_at:
        raise CatalogContractError("expiration must follow issuance")
    return MetadataWindow(revision, issued_at, expires_at)


def _kind(data: dict[str, object], expected: str, fields: frozenset[str]) -> None:
    _keys(
        data,
        fields | {"kind", "schema_version", "revision", "issued_at", "expires_at"},
        expected,
    )
    if (
        data["kind"] != expected
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise CatalogContractError("unsupported signed document kind/version")


def _module_claim(value: object) -> AuthorizedModuleClaim:
    data = _object(value, "authorized module")
    _keys(
        data,
        frozenset({"component_id", "repository", "distribution", "signing_key_ids"}),
        "authorized module",
    )
    return AuthorizedModuleClaim(
        _string(data["component_id"], "component_id", pattern=_ID_RE),
        _string(data["repository"], "repository", pattern=_REPO_RE),
        _string(data["distribution"], "distribution", pattern=_DIST_RE),
        _strings(data["signing_key_ids"], "signing key", 8, pattern=_KEY_RE),
    )


def _registry(data: dict[str, object]) -> RegistryClaims:
    _kind(data, "registry", frozenset({"modules", "integration_signing_key_ids"}))
    modules = tuple(
        _module_claim(value)
        for value in _items(data["modules"], "modules", _MAX_COMPONENTS)
    )
    _unique([module.component_id for module in modules], "component ID")
    _unique(
        [re.sub(r"[-_.]+", "-", module.distribution.lower()) for module in modules],
        "distribution",
    )
    return RegistryClaims(
        _window(data),
        modules,
        _strings(
            data["integration_signing_key_ids"],
            "integration signing key",
            8,
            pattern=_KEY_RE,
        ),
    )


def _release(value: object) -> ReleaseClaim:
    data = _object(value, "release")
    _keys(
        data,
        frozenset(
            {
                "version",
                "tag",
                "wheel",
                "sha256",
                "requires_python",
                "requires_dist",
                "console_script",
                "console_target",
                "revoked",
            }
        ),
        "release",
    )
    version = _string(data["version"], "release version", pattern=_VERSION_RE)
    tag = _string(data["tag"], "release tag")
    if tag != f"v{version}":
        raise CatalogContractError("release tag disagrees with version")
    dependencies_raw = data["requires_dist"]
    if (
        not isinstance(dependencies_raw, list)
        or len(dependencies_raw) > _MAX_DEPENDENCIES
    ):
        raise CatalogContractError("invalid requires_dist count")
    dependencies = _unique(
        [_string(item, "requires_dist", maximum=256) for item in dependencies_raw],
        "requires_dist",
    )
    revoked = data["revoked"]
    if not isinstance(revoked, bool):
        raise CatalogContractError("revoked must be boolean")
    return ReleaseClaim(
        version,
        tag,
        _string(data["wheel"], "wheel", pattern=_WHEEL_RE),
        _string(data["sha256"], "sha256", pattern=_HASH_RE),
        _string(data["requires_python"], "requires_python", maximum=128),
        dependencies,
        _string(data["console_script"], "console_script", pattern=_EP_RE),
        _string(data["console_target"], "console_target", pattern=_TARGET_RE),
        revoked,
    )


def _module_release(data: dict[str, object]) -> ModuleReleaseClaims:
    _kind(
        data,
        "module_release",
        frozenset({"component_id", "repository", "distribution", "releases"}),
    )
    releases = tuple(
        _release(value) for value in _items(data["releases"], "releases", _MAX_RELEASES)
    )
    _unique([release.version for release in releases], "release version")
    _unique([release.wheel for release in releases], "release wheel")
    return ModuleReleaseClaims(
        _window(data),
        _string(data["component_id"], "component_id", pattern=_ID_RE),
        _string(data["repository"], "repository", pattern=_REPO_RE),
        _string(data["distribution"], "distribution", pattern=_DIST_RE),
        releases,
    )


def _artifact(value: object) -> ExactArtifactClaim:
    data = _object(value, "exact artifact")
    _keys(data, frozenset({"component_id", "wheel_sha256"}), "exact artifact")
    return ExactArtifactClaim(
        _string(data["component_id"], "component_id", pattern=_ID_RE),
        _string(data["wheel_sha256"], "wheel_sha256", pattern=_HASH_RE),
    )


def _integration(data: dict[str, object]) -> IntegrationClaims:
    _kind(
        data,
        "integration",
        frozenset(
            {
                "feature_id",
                "evidence_sha256",
                "result",
                "artifacts",
                "python_minors",
                "platforms",
            }
        ),
    )
    artifacts = tuple(
        _artifact(item)
        for item in _items(data["artifacts"], "artifacts", _MAX_COMPONENTS)
    )
    _unique([item.component_id for item in artifacts], "integration component ID")
    result = _string(data["result"], "integration result")
    if result not in {"passed", "failed"}:
        raise CatalogContractError("unsupported integration result")
    return IntegrationClaims(
        _window(data),
        _string(data["feature_id"], "feature_id", pattern=_FEATURE_RE),
        _string(data["evidence_sha256"], "evidence_sha256", pattern=_HASH_RE),
        result,
        artifacts,
        _strings(
            data["python_minors"],
            "python_minors",
            10,
            pattern=re.compile(r"3\.(?:1[1-9]|[2-9][0-9])\Z"),
        ),
        _strings(
            data["platforms"],
            "platforms",
            16,
            pattern=re.compile(r"[a-z][a-z0-9_-]{1,31}\Z"),
        ),
    )


def parse_unsigned_claims(data: bytes) -> CatalogClaims:
    """Parse signed-payload bytes WITHOUT giving them signing authority."""
    if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_PAYLOAD_BYTES:
        raise CatalogContractError("signed payload exceeds contract size limits")
    document = _json_object(data, "signed payload")
    kind = document.get("kind")
    if kind == "registry":
        return _registry(document)
    if kind == "module_release":
        return _module_release(document)
    if kind == "integration":
        return _integration(document)
    raise CatalogContractError("unknown signed document kind")


def _base64(value: object, label: str, maximum: int) -> bytes:
    raw = _string(value, label, maximum=4 * ((maximum + 2) // 3))
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as error:
        raise CatalogContractError(f"invalid {label} base64") from error
    if (
        not decoded
        or len(decoded) > maximum
        or base64.b64encode(decoded).decode("ascii") != raw
    ):
        raise CatalogContractError(f"noncanonical or oversized {label}")
    return decoded


def parse_unverified_envelope(data: bytes) -> UnverifiedEnvelope:
    """Decode exact signed bytes; NEVER verify signatures or authorize releases.

    A future trusted verifier must verify the exact `payload_bytes` against a
    pinned trusted root + authorized delegations, anti-rollback, and expiry
    before projecting any claims into `LaunchPreflight` or the managed receipt.
    """
    if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_ENVELOPE_BYTES:
        raise CatalogContractError("envelope exceeds contract size limits")
    envelope = _json_object(data, "signature envelope")
    _keys(
        envelope,
        frozenset({"envelope_version", "payload_b64", "signatures"}),
        "signature envelope",
    )
    if (
        type(envelope["envelope_version"]) is not int
        or envelope["envelope_version"] != 1
    ):
        raise CatalogContractError("unsupported envelope version")
    payload = _base64(envelope["payload_b64"], "payload", _MAX_PAYLOAD_BYTES)
    signatures: list[UnverifiedSignature] = []
    for item in _items(envelope["signatures"], "signatures", _MAX_SIGNATURES):
        record = _object(item, "signature")
        _keys(record, frozenset({"key_id", "algorithm", "signature_b64"}), "signature")
        if record["algorithm"] != "ed25519":
            raise CatalogContractError("unsupported signature algorithm")
        key_id = _string(record["key_id"], "key_id", pattern=_KEY_RE)
        signature = _base64(record["signature_b64"], "signature", 64)
        if len(signature) != 64:
            raise CatalogContractError("Ed25519 signature must be exactly 64 bytes")
        signatures.append(UnverifiedSignature(key_id, signature))
    _unique([signature.key_id for signature in signatures], "signature key ID")
    return UnverifiedEnvelope(
        payload, parse_unsigned_claims(payload), tuple(signatures)
    )


__all__ = (
    "AuthorizedModuleClaim",
    "CatalogClaims",
    "CatalogContractError",
    "ExactArtifactClaim",
    "IntegrationClaims",
    "MetadataWindow",
    "ModuleReleaseClaims",
    "RegistryClaims",
    "ReleaseClaim",
    "UnverifiedEnvelope",
    "UnverifiedSignature",
    "parse_unsigned_claims",
    "parse_unverified_envelope",
)
