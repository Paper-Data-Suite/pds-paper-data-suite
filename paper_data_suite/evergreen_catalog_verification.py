"""Issue #49: cryptographic metadata authorization, not launch permission.

The caller must supply an independently trusted root/keyring (never a keyring
obtained from the catalog being verified). A verified document establishes only
signed metadata identity, NOT wheel authenticity, installation integrity,
persistent anti-rollback or a launch/integration permission.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, TypeAlias

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paper_data_suite.evergreen_catalog_contracts import (
    CatalogContractError,
    IntegrationClaims,
    MetadataWindow,
    ModuleReleaseClaims,
    RegistryClaims,
    UnverifiedEnvelope,
    parse_unverified_envelope,
)

_KEY_ID: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TRUST_KEYS: Final = 64


class CatalogVerificationError(ValueError):
    """Trust, delegated authorization, validity or revision verification failed."""


@dataclass(frozen=True, slots=True)
class TrustedPublicKey:
    """Pinned externally provisioned Ed25519 public key (32 raw bytes)."""

    key_id: str
    public_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not _KEY_ID.fullmatch(self.key_id):
            raise CatalogVerificationError("invalid pinned key ID")
        if type(self.public_bytes) is not bytes or len(self.public_bytes) != 32:
            raise CatalogVerificationError("invalid Ed25519 public key bytes")
        try:
            Ed25519PublicKey.from_public_bytes(self.public_bytes)
        except ValueError as error:
            raise CatalogVerificationError("invalid pinned public key") from error


@dataclass(frozen=True, slots=True)
class TrustedKeyring:
    """Preconfigured keys; NOT loaded or authorized from signed payload claims.

    Root signers alone may authorize the registry. Delegated signers must also
    appear under their exact component/role in a verified registry. No signer
    may occupy both roles or represent two distinct public-key identities.
    """

    keys: tuple[TrustedPublicKey, ...]
    root_key_ids: tuple[str, ...]
    root_threshold: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.keys) is not tuple
            or not 1 <= len(self.keys) <= _MAX_TRUST_KEYS
            or any(not isinstance(item, TrustedPublicKey) for item in self.keys)
        ):
            raise CatalogVerificationError("invalid trusted keyring")
        names = tuple(key.key_id for key in self.keys)
        if len(set(names)) != len(names):
            raise CatalogVerificationError("duplicate trusted key ID")
        if len(set(key.public_bytes for key in self.keys)) != len(self.keys):
            raise CatalogVerificationError("duplicate trusted public key bytes")
        if (
            type(self.root_key_ids) is not tuple
            or not self.root_key_ids
            or len(self.root_key_ids) != len(set(self.root_key_ids))
            or not set(self.root_key_ids).issubset(names)
        ):
            raise CatalogVerificationError("invalid root key selection")
        if type(self.root_threshold) is not int or not 1 <= self.root_threshold <= len(
            self.root_key_ids
        ):
            raise CatalogVerificationError("invalid root signature threshold")

    def key(self, key_id: str) -> TrustedPublicKey | None:
        return next((key for key in self.keys if key.key_id == key_id), None)


@dataclass(frozen=True, slots=True)
class RevisionCheckpoint:
    """Previously persisted revision/digest for exactly one metadata identity.

    This is a verifier input, not durable protected rollback state. The caller
    must maintain monotonically trusted checkpoints in a later implementation.
    """

    revision: int
    payload_sha256: str

    def __post_init__(self) -> None:
        if type(self.revision) is not int or not 1 <= self.revision <= 2**53 - 1:
            raise CatalogVerificationError("invalid checkpoint revision")
        if not isinstance(self.payload_sha256, str) or not _HASH.fullmatch(
            self.payload_sha256
        ):
            raise CatalogVerificationError("invalid checkpoint digest")


@dataclass(frozen=True, slots=True)
class VerifiedRegistryDocument:
    """Cryptographically root-authorized registry claims; not an install permit."""

    claims: RegistryClaims
    payload_sha256: str
    signer_ids: tuple[str, ...]
    checkpoint: RevisionCheckpoint
    trust_fingerprint: str


@dataclass(frozen=True, slots=True)
class VerifiedModuleDocument:
    """Module-delegated signed claims; wheel bytes have NOT been verified."""

    claims: ModuleReleaseClaims
    registry_payload_sha256: str
    payload_sha256: str
    signer_ids: tuple[str, ...]
    checkpoint: RevisionCheckpoint


@dataclass(frozen=True, slots=True)
class VerifiedIntegrationDocument:
    """Integration-signed claims; exact participant wheels NOT checked yet."""

    claims: IntegrationClaims
    registry_payload_sha256: str
    payload_sha256: str
    signer_ids: tuple[str, ...]
    checkpoint: RevisionCheckpoint


VerifiedDocument: TypeAlias = (
    VerifiedRegistryDocument | VerifiedModuleDocument | VerifiedIntegrationDocument
)


def _envelope(blob: bytes) -> UnverifiedEnvelope:
    try:
        return parse_unverified_envelope(blob)
    except CatalogContractError as error:
        raise CatalogVerificationError("malformed signed metadata envelope") from error


def _validity(
    window: MetadataWindow,
    now: datetime,
    checkpoint: RevisionCheckpoint | None,
    digest: str,
) -> RevisionCheckpoint:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CatalogVerificationError("current time must be timezone-aware")
    current = now.astimezone(timezone.utc)
    if not window.issued_at <= current < window.expires_at:
        raise CatalogVerificationError("signed metadata is not currently valid")
    if checkpoint is not None:
        if not isinstance(checkpoint, RevisionCheckpoint):
            raise CatalogVerificationError("invalid revision checkpoint")
        if window.revision < checkpoint.revision:
            raise CatalogVerificationError("signed metadata revision rollback")
        if (
            window.revision == checkpoint.revision
            and digest != checkpoint.payload_sha256
        ):
            raise CatalogVerificationError("signed metadata revision equivocation")
    return RevisionCheckpoint(window.revision, digest)


def _authorized_signers(
    envelope: UnverifiedEnvelope,
    ring: TrustedKeyring,
    allowed: frozenset[str],
    required: int,
) -> tuple[str, ...]:
    """Verify original signed bytes, reject any unknown/undelegated signer.

    There is no reliance on unverified key material from payload bytes. The
    envelope includes no public keys; those arrive only via the trusted ring.
    """
    approved: list[str] = []
    for signature in envelope.signatures:
        if signature.key_id not in allowed:
            raise CatalogVerificationError("signature key is not delegated for role")
        key = ring.key(signature.key_id)
        if key is None:
            raise CatalogVerificationError("delegated key is not in trusted keyring")
        try:
            Ed25519PublicKey.from_public_bytes(key.public_bytes).verify(
                signature.signature, envelope.payload_bytes
            )
        except (InvalidSignature, ValueError) as error:
            raise CatalogVerificationError("Ed25519 signature is invalid") from error
        approved.append(signature.key_id)
    if len(approved) < required:
        raise CatalogVerificationError("insufficient authorized signatures")
    return tuple(approved)


def _ensure_separate_delegations(
    registry: RegistryClaims, ring: TrustedKeyring
) -> None:
    """A root or one module's signer may not silently gain another role."""
    roles: dict[str, str] = {name: "root" for name in ring.root_key_ids}
    for module in registry.modules:
        for key_id in module.signing_key_ids:
            if ring.key(key_id) is None:
                raise CatalogVerificationError("unknown module delegation key")
            if key_id in roles:
                raise CatalogVerificationError("delegation crosses trusted roles")
            roles[key_id] = f"module:{module.component_id}"
    for key_id in registry.integration_signing_key_ids:
        if ring.key(key_id) is None:
            raise CatalogVerificationError("unknown integration delegation key")
        if key_id in roles:
            raise CatalogVerificationError("delegation crosses trusted roles")
        roles[key_id] = "integration"


def verify_registry_document(
    data: bytes,
    *,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
) -> VerifiedRegistryDocument:
    """Authenticate the registry using independently provisioned root keys.

    Caller-controlled `trust` MUST originate from a pinned deployment authority,
    not a downloaded registry, a command-line path or untrusted module metadata.
    """
    if not isinstance(trust, TrustedKeyring):
        raise CatalogVerificationError("trusted root/keyring is required")
    envelope = _envelope(data)
    if not isinstance(envelope.claims, RegistryClaims):
        raise CatalogVerificationError("expected root-signed registry")
    signers = _authorized_signers(
        envelope,
        trust,
        frozenset(trust.root_key_ids),
        trust.root_threshold,
    )
    _ensure_separate_delegations(envelope.claims, trust)
    digest = hashlib.sha256(envelope.payload_bytes).hexdigest()
    next_checkpoint = _validity(envelope.claims.window, now, checkpoint, digest)
    return VerifiedRegistryDocument(
        envelope.claims, digest, signers, next_checkpoint, _trust_fingerprint(trust)
    )


def _trust_fingerprint(trust: TrustedKeyring) -> str:
    """Bind a verified registry to the exact pinned role/key configuration."""
    digest = hashlib.sha256(b"pds-evergreen-trust-v1\0")
    for key in sorted(trust.keys, key=lambda item: item.key_id):
        digest.update(key.key_id.encode("ascii") + b"\0" + key.public_bytes)
    for key_id in sorted(trust.root_key_ids):
        digest.update(b"root\0" + key_id.encode("ascii") + b"\0")
    digest.update(str(trust.root_threshold).encode("ascii"))
    return digest.hexdigest()


def _registry_is_current(
    registry: VerifiedRegistryDocument, now: datetime, trust: TrustedKeyring
) -> None:
    if not isinstance(registry, VerifiedRegistryDocument):
        raise CatalogVerificationError("authenticated registry is required")
    if registry.trust_fingerprint != _trust_fingerprint(trust):
        raise CatalogVerificationError(
            "registry was verified with another trust policy"
        )
    _validity(registry.claims.window, now, registry.checkpoint, registry.payload_sha256)


def verify_module_document(
    data: bytes,
    *,
    registry: VerifiedRegistryDocument,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
) -> VerifiedModuleDocument:
    """Authorize module signer for exact component/repository/distribution.

    This verifies claims, not downloaded wheels or a runtime launch permission.
    """
    if not isinstance(trust, TrustedKeyring):
        raise CatalogVerificationError("trusted keyring is required")
    _registry_is_current(registry, now, trust)
    envelope = _envelope(data)
    if not isinstance(envelope.claims, ModuleReleaseClaims):
        raise CatalogVerificationError("expected module-release metadata")
    claim = envelope.claims
    matches = [
        item
        for item in registry.claims.modules
        if item.component_id == claim.component_id
    ]
    if len(matches) != 1:
        raise CatalogVerificationError("module is not registered")
    authority = matches[0]
    if (
        authority.repository != claim.repository
        or authority.distribution != claim.distribution
    ):
        raise CatalogVerificationError("module identity mismatches registry")
    signers = _authorized_signers(
        envelope, trust, frozenset(authority.signing_key_ids), 1
    )
    digest = hashlib.sha256(envelope.payload_bytes).hexdigest()
    next_checkpoint = _validity(claim.window, now, checkpoint, digest)
    return VerifiedModuleDocument(
        claim, registry.payload_sha256, digest, signers, next_checkpoint
    )


def verify_integration_document(
    data: bytes,
    *,
    registry: VerifiedRegistryDocument,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
) -> VerifiedIntegrationDocument:
    """Authenticate exact-scope claims under the integration-signing role.

    This does not assert that the referenced wheels actually match the claims.
    """
    if not isinstance(trust, TrustedKeyring):
        raise CatalogVerificationError("trusted keyring is required")
    _registry_is_current(registry, now, trust)
    envelope = _envelope(data)
    if not isinstance(envelope.claims, IntegrationClaims):
        raise CatalogVerificationError("expected integration metadata")
    signers = _authorized_signers(
        envelope,
        trust,
        frozenset(registry.claims.integration_signing_key_ids),
        1,
    )
    digest = hashlib.sha256(envelope.payload_bytes).hexdigest()
    next_checkpoint = _validity(envelope.claims.window, now, checkpoint, digest)
    return VerifiedIntegrationDocument(
        envelope.claims, registry.payload_sha256, digest, signers, next_checkpoint
    )


__all__ = (
    "CatalogVerificationError",
    "RevisionCheckpoint",
    "TrustedKeyring",
    "TrustedPublicKey",
    "VerifiedDocument",
    "VerifiedIntegrationDocument",
    "VerifiedModuleDocument",
    "VerifiedRegistryDocument",
    "verify_integration_document",
    "verify_module_document",
    "verify_registry_document",
)
