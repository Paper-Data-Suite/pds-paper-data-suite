"""Issue #49: digest-pinned Ed25519 trust-policy provisioning.

A caller MUST supply a trusted digest from independently shipped/reviewed code.
The policy bytes are not self-authenticating; this API NEVER accepts an
untrusted catalog-provided hash as an anchor. Production keys are not shipped.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, cast

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    TrustedKeyring,
    TrustedPublicKey,
)

_MAX_POLICY_BYTES: Final = 24 * 1024
_SHA256: Final = re.compile(r"[0-9a-f]{64}\Z")


class TrustProvisioningError(ValueError):
    """A policy does not match its independent pin or strict keyring contract."""


@dataclass(frozen=True, slots=True)
class PinnedTrustPolicy:
    """Digest-matched policy holding only Ed25519 PUBLIC keys."""

    keyring: TrustedKeyring
    sha256: str
    policy_revision: int


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TrustProvisioningError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise TrustProvisioningError("duplicate trust policy JSON member")
        result[name] = value
    return result


def _public_bytes(value: object) -> bytes:
    if not isinstance(value, str) or len(value) != 44:
        raise TrustProvisioningError("invalid public key encoding")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise TrustProvisioningError("invalid public key base64") from error
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != value:
        raise TrustProvisioningError("invalid Ed25519 public key encoding")
    return raw


def load_digest_pinned_trust_policy(
    data: bytes, *, pinned_sha256: str
) -> PinnedTrustPolicy:
    """Build keyring ONLY when policy bytes match an independently trusted pin.

    No signed update or root rotation is implied. A future root-delegation
    protocol must independently authenticate a successor trust policy.
    """
    if type(data) is not bytes or not 1 <= len(data) <= _MAX_POLICY_BYTES:
        raise TrustProvisioningError("invalid trust policy size")
    if type(pinned_sha256) is not str or not _SHA256.fullmatch(pinned_sha256):
        raise TrustProvisioningError("invalid independent SHA-256 trust pin")
    digest = hashlib.sha256(data).hexdigest()
    if digest != pinned_sha256:
        raise TrustProvisioningError("trust policy does not match independent pin")
    try:
        document = _object(
            json.loads(data.decode("utf-8"), object_pairs_hook=_unique_json),
            "trust policy",
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise TrustProvisioningError("invalid trust policy JSON") from error
    if document.keys() != {
        "record_type",
        "schema_version",
        "revision",
        "keys",
        "root_key_ids",
        "root_threshold",
    }:
        raise TrustProvisioningError("unexpected trust policy fields")
    if (
        document["record_type"] != "pds_evergreen_pinned_keyring"
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
    ):
        raise TrustProvisioningError("unsupported trust policy identity")
    revision = document["revision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise TrustProvisioningError("invalid trust policy revision")
    keys_value = document["keys"]
    if not isinstance(keys_value, list) or not 1 <= len(keys_value) <= 64:
        raise TrustProvisioningError("invalid public key count")
    keys: list[TrustedPublicKey] = []
    for value in keys_value:
        item = _object(value, "key")
        if item.keys() != {"key_id", "public_key_b64"}:
            raise TrustProvisioningError("unexpected public key fields")
        try:
            keys.append(
                TrustedPublicKey(
                    cast(str, item["key_id"]),
                    _public_bytes(item["public_key_b64"]),
                )
            )
        except CatalogVerificationError as error:
            raise TrustProvisioningError("invalid trusted public key") from error
    roots = document["root_key_ids"]
    if (
        not isinstance(roots, list)
        or not 1 <= len(roots) <= 64
        or any(type(value) is not str for value in roots)
    ):
        raise TrustProvisioningError("invalid root key IDs")
    try:
        keyring = TrustedKeyring(
            tuple(keys),
            tuple(cast(list[str], roots)),
            cast(int, document["root_threshold"]),
        )
    except CatalogVerificationError as error:
        raise TrustProvisioningError("invalid trusted keyring") from error
    return PinnedTrustPolicy(keyring, digest, revision)


__all__ = (
    "PinnedTrustPolicy",
    "TrustProvisioningError",
    "load_digest_pinned_trust_policy",
)
