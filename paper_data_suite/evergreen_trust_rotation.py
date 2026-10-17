"""Issue #49: dual-authorized trust-policy transition, with no I/O.

This protocol verifies successor public-key policy bytes under BOTH the
previous trusted root quorum and the successor root quorum. Its only input
anchor is a caller-provisioned PinnedTrustPolicy, never catalog-supplied keys.
It does not install successor state, create keys, or grant launch authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Final, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_trust_provisioning import (
    PinnedTrustPolicy,
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)

_MAX_TRANSITION: Final = 64 * 1024
_MAX_POLICY: Final = 24 * 1024
_CONTEXT: Final = b"pds-evergreen-policy-transition-v1\x00"


class TrustRotationError(ValueError):
    """Successor keyring is not authorized by both root quorums."""


@dataclass(frozen=True, slots=True)
class AuthorizedTrustTransition:
    """Verified transition, NOT durable installation or protected rollback."""

    previous_sha256: str
    successor: PinnedTrustPolicy
    old_signers: tuple[str, ...]
    new_signers: tuple[str, ...]


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise TrustRotationError("duplicate transition JSON member")
        result[name] = value
    return result


def _decoded(value: object, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 4 * ((maximum + 2) // 3):
        raise TrustRotationError("invalid transition base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise TrustRotationError("invalid transition base64") from error
    if (
        not decoded
        or len(decoded) > maximum
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        raise TrustRotationError("noncanonical transition base64")
    return decoded


def _quorum(
    signatures: object, *, ring: TrustedKeyring, message: bytes
) -> tuple[str, ...]:
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 8:
        raise TrustRotationError("invalid root signature count")
    approved: list[str] = []
    for item in signatures:
        if not isinstance(item, dict) or item.keys() != {
            "key_id",
            "algorithm",
            "signature_b64",
        }:
            raise TrustRotationError("invalid root signature fields")
        signature = cast(dict[str, object], item)
        key_id = signature["key_id"]
        if (
            type(key_id) is not str
            or key_id not in ring.root_key_ids
            or key_id in approved
            or signature["algorithm"] != "ed25519"
        ):
            raise TrustRotationError("unauthorized or repeated root signer")
        raw = _decoded(signature["signature_b64"], maximum=64)
        if len(raw) != 64:
            raise TrustRotationError("invalid root signature length")
        key = ring.key(key_id)
        if key is None:
            raise TrustRotationError("missing root public key")
        try:
            Ed25519PublicKey.from_public_bytes(key.public_bytes).verify(raw, message)
        except (InvalidSignature, ValueError) as error:
            raise TrustRotationError("invalid root transition signature") from error
        approved.append(key_id)
    if len(approved) < ring.root_threshold:
        raise TrustRotationError("root signature quorum was not met")
    return tuple(approved)


def verify_trust_transition(
    data: bytes, *, previous: PinnedTrustPolicy
) -> AuthorizedTrustTransition:
    """Verify exact successor bytes with the prior root AND successor root.

    Signing message binds domain, old policy digest, and successor bytes. A
    valid transition is not automatically active: a later controlled installer
    must protect continuity and atomically activate the newly pinned policy.
    """
    if not isinstance(previous, PinnedTrustPolicy):
        raise TrustRotationError("independently pinned previous policy is required")
    if type(data) is not bytes or not 1 <= len(data) <= _MAX_TRANSITION:
        raise TrustRotationError("invalid transition size")
    try:
        parsed: object = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_json
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise TrustRotationError("invalid transition JSON") from error
    if not isinstance(parsed, dict) or parsed.keys() != {
        "record_type",
        "schema_version",
        "previous_sha256",
        "successor_policy_b64",
        "previous_root_signatures",
        "successor_root_signatures",
    }:
        raise TrustRotationError("invalid transition contract")
    transition = cast(dict[str, object], parsed)
    if (
        transition["record_type"] != "pds_evergreen_trust_transition"
        or type(transition["schema_version"]) is not int
        or transition["schema_version"] != 1
        or transition["previous_sha256"] != previous.sha256
    ):
        raise TrustRotationError("transition does not match previous trust anchor")
    successor_bytes = _decoded(transition["successor_policy_b64"], maximum=_MAX_POLICY)
    successor_hash = hashlib.sha256(successor_bytes).hexdigest()
    try:
        successor = load_digest_pinned_trust_policy(
            successor_bytes, pinned_sha256=successor_hash
        )
    except TrustProvisioningError as error:
        raise TrustRotationError("invalid successor trust policy") from error
    if successor.policy_revision <= previous.policy_revision:
        raise TrustRotationError("successor policy revision must advance")
    message = _CONTEXT + previous.sha256.encode("ascii") + b"\x00" + successor_bytes
    old_signers = _quorum(
        transition["previous_root_signatures"],
        ring=previous.keyring,
        message=message,
    )
    new_signers = _quorum(
        transition["successor_root_signatures"],
        ring=successor.keyring,
        message=message,
    )
    return AuthorizedTrustTransition(
        previous.sha256, successor, old_signers, new_signers
    )


__all__ = (
    "AuthorizedTrustTransition",
    "TrustRotationError",
    "verify_trust_transition",
)
