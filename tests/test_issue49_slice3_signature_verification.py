"""Issue #49 Slice 3: exact Ed25519 authenticity and delegation boundaries.

All private test seeds below are synthetic, never production publisher keys.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    TrustedPublicKey,
    VerifiedIntegrationDocument,
    VerifiedModuleDocument,
    VerifiedRegistryDocument,
    verify_integration_document,
    verify_module_document,
    verify_registry_document,
)

NOW = datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc)
# Synthetic fixture secrets, not deployable signing keys.
_SEEDS = {
    "root-primary": b"\x01" * 32,
    "root-backup": b"\x02" * 32,
    "quillan-primary": b"\x03" * 32,
    "portia-primary": b"\x04" * 32,
    "suite-integration": b"\x05" * 32,
    "attacker": b"\x06" * 32,
}


def _private(key_id: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_SEEDS[key_id])


def _public(key_id: str) -> TrustedPublicKey:
    data = (
        _private(key_id)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return TrustedPublicKey(key_id, data)


def _ring(*, threshold: int = 1) -> TrustedKeyring:
    return TrustedKeyring(
        tuple(_public(key_id) for key_id in _SEEDS),
        ("root-primary", "root-backup"),
        threshold,
    )


def _window(revision: int = 1) -> dict[str, object]:
    return {
        "revision": revision,
        "issued_at": "2026-10-17T16:00:00Z",
        "expires_at": "2026-11-17T16:00:00Z",
    }


def _registry(revision: int = 1) -> dict[str, Any]:
    return {
        "kind": "registry",
        "schema_version": 1,
        **_window(revision),
        "modules": [
            {
                "component_id": "quillan",
                "repository": "Paper-Data-Suite/pds-quillan",
                "distribution": "quillan",
                "signing_key_ids": ["quillan-primary"],
            },
            {
                "component_id": "portia",
                "repository": "Paper-Data-Suite/pds-portia",
                "distribution": "pds-portia",
                "signing_key_ids": ["portia-primary"],
            },
        ],
        "integration_signing_key_ids": ["suite-integration"],
    }


def _module(revision: int = 1) -> dict[str, Any]:
    return {
        "kind": "module_release",
        "schema_version": 1,
        **_window(revision),
        "component_id": "quillan",
        "repository": "Paper-Data-Suite/pds-quillan",
        "distribution": "quillan",
        "releases": [
            {
                "version": "0.10.7",
                "tag": "v0.10.7",
                "wheel": "quillan-0.10.7-py3-none-any.whl",
                "sha256": "a" * 64,
                "requires_python": ">=3.11,<3.15",
                "requires_dist": ["pds-core>=0.6.6,<0.7"],
                "console_script": "quillan",
                "console_target": "quillan.cli:main",
                "revoked": False,
            }
        ],
    }


def _integration(revision: int = 1) -> dict[str, Any]:
    return {
        "kind": "integration",
        "schema_version": 1,
        **_window(revision),
        "feature_id": "meridian.quillan-evidence",
        "evidence_sha256": "b" * 64,
        "result": "passed",
        "artifacts": [
            {"component_id": "quillan", "wheel_sha256": "a" * 64},
            {"component_id": "meridian", "wheel_sha256": "c" * 64},
        ],
        "python_minors": ["3.11", "3.13"],
        "platforms": ["win_amd64"],
    }


def _encode(document: dict[str, Any]) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


def _signed(
    document: dict[str, Any],
    *signer_ids: str,
    payload: bytes | None = None,
    signature_override: bytes | None = None,
) -> bytes:
    body = payload if payload is not None else _encode(document)
    signatures = [
        {
            "key_id": signer,
            "algorithm": "ed25519",
            "signature_b64": base64.b64encode(
                signature_override
                if signature_override is not None
                else _private(signer).sign(body)
            ).decode("ascii"),
        }
        for signer in signer_ids
    ]
    return _encode(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(body).decode("ascii"),
            "signatures": signatures,
        }
    )


def _verified_registry(
    *, ring: TrustedKeyring | None = None, revision: int = 1
) -> VerifiedRegistryDocument:
    return verify_registry_document(
        _signed(_registry(revision), "root-primary"),
        trust=ring or _ring(),
        now=NOW,
    )


def test_real_root_signature_verifies_exact_payload_bytes() -> None:
    envelope = _signed(_registry(), "root-primary")
    result = verify_registry_document(envelope, trust=_ring(), now=NOW)
    assert isinstance(result, VerifiedRegistryDocument)
    assert result.signer_ids == ("root-primary",)
    assert result.checkpoint.payload_sha256 == result.payload_sha256
    assert not hasattr(result, "can_launch")


def test_delegation_accepts_future_release_without_suite_version() -> None:
    result = verify_module_document(
        _signed(_module(), "quillan-primary"),
        registry=_verified_registry(),
        trust=_ring(),
        now=NOW,
    )
    assert isinstance(result, VerifiedModuleDocument)
    assert result.claims.releases[0].version == "0.10.7"
    assert result.signer_ids == ("quillan-primary",)
    assert not hasattr(result, "release_trust")
    assert not hasattr(result, "can_launch")


def test_valid_integration_signature_does_not_assert_installed_wheel_matches() -> None:
    result = verify_integration_document(
        _signed(_integration(), "suite-integration"),
        registry=_verified_registry(),
        trust=_ring(),
        now=NOW,
    )
    assert isinstance(result, VerifiedIntegrationDocument)
    assert result.claims.result == "passed"
    assert not hasattr(result, "permitted")


@pytest.mark.parametrize(
    ("document", "signer"),
    [
        (_registry, "quillan-primary"),
        (_registry, "attacker"),
        (_module, "root-primary"),
        (_module, "portia-primary"),
        (_module, "suite-integration"),
        (_module, "attacker"),
        (_integration, "quillan-primary"),
        (_integration, "root-primary"),
        (_integration, "attacker"),
    ],
)
def test_cross_role_or_forged_signer_refused(document: Any, signer: str) -> None:
    data = _signed(document(), signer)
    with pytest.raises(CatalogVerificationError):
        if document is _registry:
            verify_registry_document(data, trust=_ring(), now=NOW)
        elif document is _module:
            verify_module_document(
                data, registry=_verified_registry(), trust=_ring(), now=NOW
            )
        else:
            verify_integration_document(
                data, registry=_verified_registry(), trust=_ring(), now=NOW
            )


def test_valid_signature_for_wrong_payload_is_not_trusted() -> None:
    original = _encode(_module())
    modified = copy.deepcopy(_module())
    modified["releases"][0]["sha256"] = "b" * 64
    signature = _private("quillan-primary").sign(original)
    with pytest.raises(CatalogVerificationError, match="signature is invalid"):
        verify_module_document(
            _signed(modified, "quillan-primary", signature_override=signature),
            registry=_verified_registry(),
            trust=_ring(),
            now=NOW,
        )


def test_signature_verifies_exact_signed_bytes_not_reserialized_json() -> None:
    original = _encode(_module())
    other = json.dumps(_module(), indent=2, sort_keys=False).encode()
    assert original != other
    wrong = _private("quillan-primary").sign(original)
    with pytest.raises(CatalogVerificationError):
        verify_module_document(
            _signed(
                _module(), "quillan-primary", payload=other, signature_override=wrong
            ),
            registry=_verified_registry(),
            trust=_ring(),
            now=NOW,
        )
    result = verify_module_document(
        _signed(_module(), "quillan-primary", payload=other),
        registry=_verified_registry(),
        trust=_ring(),
        now=NOW,
    )
    assert result.payload_sha256 == hashlib.sha256(other).hexdigest()


def test_registry_root_signature_threshold_is_enforced() -> None:
    ring = _ring(threshold=2)
    with pytest.raises(CatalogVerificationError, match="insufficient"):
        verify_registry_document(
            _signed(_registry(), "root-primary"), trust=ring, now=NOW
        )
    approved = verify_registry_document(
        _signed(_registry(), "root-primary", "root-backup"), trust=ring, now=NOW
    )
    assert len(approved.signer_ids) == 2


def test_any_extra_invalid_or_undelegated_signature_fails_closed() -> None:
    with pytest.raises(CatalogVerificationError, match="not delegated"):
        verify_registry_document(
            _signed(_registry(), "root-primary", "attacker"),
            trust=_ring(),
            now=NOW,
        )
    raw = _private("root-primary").sign(_encode(_registry()))
    assert len(raw) == 64
    with pytest.raises(CatalogVerificationError, match="invalid"):
        verify_registry_document(
            _signed(
                _registry(), "root-primary", "root-backup", signature_override=b"x" * 64
            ),
            trust=_ring(),
            now=NOW,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda obj: obj["modules"][0].update({"signing_key_ids": ["root-primary"]}),
        lambda obj: obj["modules"][0].update(
            {"signing_key_ids": ["suite-integration"]}
        ),
        lambda obj: obj["modules"][0].update({"signing_key_ids": ["portia-primary"]}),
        lambda obj: obj.update({"integration_signing_key_ids": ["root-backup"]}),
        lambda obj: obj.update({"integration_signing_key_ids": ["attacker-unknown"]}),
    ],
)
def test_registry_cannot_delegate_root_cross_module_or_unknown_signer(
    mutation: Any,
) -> None:
    document = copy.deepcopy(_registry())
    mutation(document)
    with pytest.raises(CatalogVerificationError):
        verify_registry_document(
            _signed(document, "root-primary"), trust=_ring(), now=NOW
        )


def test_publisher_claim_cannot_retarget_registered_repository() -> None:
    document = _module()
    document["repository"] = "OtherOrg/pds-quillan"
    with pytest.raises(CatalogVerificationError, match="identity mismatches"):
        verify_module_document(
            _signed(document, "quillan-primary"),
            registry=_verified_registry(),
            trust=_ring(),
            now=NOW,
        )


def test_unregistered_component_cannot_be_added_by_own_signature() -> None:
    document = _module()
    document["component_id"] = "stranger"
    with pytest.raises(CatalogVerificationError, match="not registered"):
        verify_module_document(
            _signed(document, "quillan-primary"),
            registry=_verified_registry(),
            trust=_ring(),
            now=NOW,
        )


@pytest.mark.parametrize(
    "change",
    [
        timedelta(hours=-2),
        timedelta(days=40),
    ],
)
def test_expired_or_not_yet_issued_metadata_refused(change: timedelta) -> None:
    with pytest.raises(CatalogVerificationError, match="not currently valid"):
        verify_registry_document(
            _signed(_registry(), "root-primary"),
            trust=_ring(),
            now=NOW + change,
        )


def test_expired_registry_cannot_authorize_fresh_module_signature() -> None:
    with pytest.raises(CatalogVerificationError, match="not currently valid"):
        verify_module_document(
            _signed(_module(), "quillan-primary"),
            registry=_verified_registry(),
            trust=_ring(),
            now=NOW + timedelta(days=45),
        )


def test_invalid_clock_is_refused() -> None:
    with pytest.raises(CatalogVerificationError, match="timezone-aware"):
        verify_registry_document(
            _signed(_registry(), "root-primary"),
            trust=_ring(),
            now=datetime(2026, 10, 17, 17, 0),
        )


def test_revision_rollback_and_same_revision_equivocation_are_blocked() -> None:
    old = _verified_registry(revision=4)
    with pytest.raises(CatalogVerificationError, match="rollback"):
        verify_registry_document(
            _signed(_registry(3), "root-primary"),
            trust=_ring(),
            now=NOW,
            checkpoint=old.checkpoint,
        )
    changed = _registry(4)
    changed["integration_signing_key_ids"] = ["attacker"]
    with pytest.raises(CatalogVerificationError, match="equivocation"):
        verify_registry_document(
            _signed(changed, "root-primary"),
            trust=_ring(),
            now=NOW,
            checkpoint=old.checkpoint,
        )
    same = verify_registry_document(
        _signed(_registry(4), "root-primary"),
        trust=_ring(),
        now=NOW,
        checkpoint=old.checkpoint,
    )
    assert same.checkpoint == old.checkpoint
    new = verify_registry_document(
        _signed(_registry(5), "root-primary"),
        trust=_ring(),
        now=NOW,
        checkpoint=old.checkpoint,
    )
    assert new.checkpoint.revision == 5


def test_module_revision_rollback_is_independent_of_registry_revision() -> None:
    registry = _verified_registry(revision=5)
    first = verify_module_document(
        _signed(_module(4), "quillan-primary"),
        registry=registry,
        trust=_ring(),
        now=NOW,
    )
    with pytest.raises(CatalogVerificationError, match="rollback"):
        verify_module_document(
            _signed(_module(3), "quillan-primary"),
            registry=registry,
            trust=_ring(),
            now=NOW,
            checkpoint=first.checkpoint,
        )


def test_untrusted_second_keyring_cannot_substitute_delegated_public_key() -> None:
    original = _verified_registry()
    keys = []
    for item in _ring().keys:
        if item.key_id == "quillan-primary":
            # Replace with a unique attacker-controlled key; remove the original
            # attacker label to avoid deliberately duplicated public bytes.
            keys.append(TrustedPublicKey(item.key_id, _public("attacker").public_bytes))
        elif item.key_id != "attacker":
            keys.append(item)
    modified = TrustedKeyring(tuple(keys), _ring().root_key_ids)
    with pytest.raises(CatalogVerificationError, match="another trust policy"):
        verify_module_document(
            _signed(_module(), "quillan-primary"),
            registry=original,
            trust=modified,
            now=NOW,
        )


def test_keys_cannot_be_reused_across_trust_roles_or_ids() -> None:
    with pytest.raises(
        CatalogVerificationError, match="duplicate trusted public key bytes"
    ):
        TrustedKeyring(
            (
                _public("root-primary"),
                TrustedPublicKey("another-id", _public("root-primary").public_bytes),
            ),
            ("root-primary",),
        )
    with pytest.raises(
        CatalogVerificationError, match="invalid root signature threshold"
    ):
        replace(_ring(), root_threshold=3)
    with pytest.raises(
        CatalogVerificationError, match="invalid Ed25519 public key bytes"
    ):
        TrustedPublicKey("root-primary", b"X")


def test_bad_checkpoint_inputs_refused() -> None:
    with pytest.raises(CatalogVerificationError, match="invalid checkpoint revision"):
        RevisionCheckpoint(True, "a" * 64)  # type: ignore[arg-type]
    with pytest.raises(CatalogVerificationError, match="invalid checkpoint digest"):
        RevisionCheckpoint(1, "ABC")


def test_malformed_envelope_cannot_be_promoted_to_verified() -> None:
    with pytest.raises(CatalogVerificationError, match="malformed"):
        verify_registry_document(b"{}", trust=_ring(), now=NOW)


def test_signed_registry_is_not_sufficient_to_self_register_publisher_key() -> None:
    registry = _registry()
    registry["modules"][0]["signing_key_ids"] = ["unknown-publisher"]
    with pytest.raises(CatalogVerificationError, match="unknown module delegation key"):
        verify_registry_document(
            _signed(registry, "root-primary"), trust=_ring(), now=NOW
        )


def test_original_schema_parser_does_not_gain_crypto_authority() -> None:
    from paper_data_suite.evergreen_catalog_contracts import (
        parse_unverified_envelope,
    )

    unverified = parse_unverified_envelope(_signed(_module(), "attacker"))
    assert unverified.claims is not None
    assert not isinstance(unverified, VerifiedModuleDocument)
