"""Offline Ed25519 publisher material and Issue #49 signed catalog issuance.

Private keys are password-encrypted PKCS#8; this module neither provisions a
production root nor authorizes launch. A publisher must separately pin and
protect the public trust policy and independently approve what gets signed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_KEY_ID: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")
_MAX_DOCUMENT: Final = 192 * 1024
_MAX_KEY: Final = 16 * 1024


class OfflinePublisherError(ValueError):
    """Invalid issuance input or key material; no release was authorized."""


@dataclass(frozen=True, slots=True)
class PublisherPublicKey:
    key_id: str
    public_key_b64: str
    public_sha256: str


def _key_id(value: str) -> str:
    if type(value) is not str or not _KEY_ID.fullmatch(value):
        raise OfflinePublisherError("invalid publisher key ID")
    return value


def _public(key_id: str, key: Ed25519PublicKey) -> PublisherPublicKey:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return PublisherPublicKey(
        key_id, base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()
    )


def generate_encrypted_keypair(
    key_id: str, password: bytes
) -> tuple[bytes, PublisherPublicKey]:
    """Create random publisher key, encrypted at rest; never write any file."""
    _key_id(key_id)
    if type(password) is not bytes or not 16 <= len(password) <= 1024:
        raise OfflinePublisherError("publisher key password must be 16-1024 bytes")
    key = Ed25519PrivateKey.generate()
    encrypted = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )
    return encrypted, _public(key_id, key.public_key())


def public_key_from_encrypted(
    key_id: str, encrypted_pem: bytes, password: bytes
) -> PublisherPublicKey:
    key = _load_key(key_id, encrypted_pem, password)
    return _public(key_id, key.public_key())


def _load_key(key_id: str, encrypted_pem: bytes, password: bytes) -> Ed25519PrivateKey:
    _key_id(key_id)
    if (
        type(encrypted_pem) is not bytes
        or not 1 <= len(encrypted_pem) <= _MAX_KEY
        or type(password) is not bytes
        or not 1 <= len(password) <= 1024
    ):
        raise OfflinePublisherError("invalid encrypted signing key input")
    try:
        result = serialization.load_pem_private_key(encrypted_pem, password=password)
    except (TypeError, ValueError) as error:
        raise OfflinePublisherError(
            "encrypted publisher key could not be opened"
        ) from error
    if not isinstance(result, Ed25519PrivateKey):
        raise OfflinePublisherError("publisher key is not Ed25519")
    return result


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise OfflinePublisherError("duplicate signed-document field")
        seen[key] = value
    return seen


def sign_catalog_payload(
    raw_payload: bytes, *, key_id: str, encrypted_pem: bytes, password: bytes
) -> bytes:
    """Sign exact reviewed catalog bytes; never claim production trust.

    The cryptographic envelope matches the existing catalog verifier contract.
    Registry delegation, release identity, and authority must be independently
    checked by the existing verifier using an independently pinned keyring.
    """
    key = _load_key(key_id, encrypted_pem, password)
    if type(raw_payload) is not bytes or not 1 <= len(raw_payload) <= _MAX_DOCUMENT:
        raise OfflinePublisherError("signed document outside bounds")
    try:
        data: object = json.loads(
            raw_payload.decode("utf-8"), object_pairs_hook=_unique
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise OfflinePublisherError("signed document is invalid JSON") from error
    if not isinstance(data, dict) or data.get("kind") not in {
        "registry",
        "module_release",
        "integration",
        "dependency_lock",
    }:
        raise OfflinePublisherError("unsupported signed catalog document kind")
    if data.get("schema_version") != 1 or type(data.get("schema_version")) is not int:
        raise OfflinePublisherError("unsupported signed catalog schema")
    signature = key.sign(raw_payload)
    envelope = {
        "envelope_version": 1,
        "payload_b64": base64.b64encode(raw_payload).decode("ascii"),
        "signatures": [
            {
                "key_id": key_id,
                "algorithm": "ed25519",
                "signature_b64": base64.b64encode(signature).decode("ascii"),
            }
        ],
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")


__all__ = (
    "OfflinePublisherError",
    "PublisherPublicKey",
    "generate_encrypted_keypair",
    "public_key_from_encrypted",
    "sign_catalog_payload",
)
