"""Issue #49 Slice 99: offline issuer creates genuine compatible signatures."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest

from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
    verify_module_document,
    verify_registry_document,
)
from paper_data_suite.evergreen_offline_publisher import (
    OfflinePublisherError,
    generate_encrypted_keypair,
    public_key_from_encrypted,
    sign_catalog_payload,
)


def registry() -> bytes:
    return json.dumps(
        {
            "kind": "registry",
            "schema_version": 1,
            "revision": 1,
            "issued_at": "2026-10-31T00:00:00Z",
            "expires_at": "2026-11-30T00:00:00Z",
            "modules": [
                {
                    "component_id": "quillan",
                    "distribution": "quillan",
                    "repository": "Paper-Data-Suite/pds-quillan",
                    "signing_key_ids": ["quillan-publisher"],
                }
            ],
            "integration_signing_key_ids": ["suite-integration"],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_offline_root_signed_document_verifies_with_existing_catalog_verifier() -> None:
    secret, root = generate_encrypted_keypair(
        "publisher-root", b"correct horse battery staple"
    )
    _, delegated = generate_encrypted_keypair(
        "quillan-publisher", b"another very long passphrase"
    )
    _, integration = generate_encrypted_keypair(
        "suite-integration", b"third strong passphrase"
    )
    # Put delegated key into the ring, but only the independent root can sign registry.
    ring = TrustedKeyring(
        (
            TrustedPublicKey(root.key_id, base64.b64decode(root.public_key_b64)),
            TrustedPublicKey(
                delegated.key_id, base64.b64decode(delegated.public_key_b64)
            ),
            TrustedPublicKey(
                integration.key_id, base64.b64decode(integration.public_key_b64)
            ),
        ),
        (root.key_id,),
        1,
    )
    signed = sign_catalog_payload(
        registry(),
        key_id=root.key_id,
        encrypted_pem=secret,
        password=b"correct horse battery staple",
    )
    result = verify_registry_document(
        signed, trust=ring, now=datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    )
    assert result.signer_ids == (root.key_id,)
    assert result.claims.modules[0].component_id == "quillan"
    assert b"PRIVATE KEY" not in signed


def test_passphrase_protects_key_and_raw_bytes_roundtrip() -> None:
    secret, info = generate_encrypted_keypair(
        "publisher-root", b"a sufficiently long passphrase"
    )
    assert b"ENCRYPTED PRIVATE KEY" in secret
    assert info == public_key_from_encrypted(
        "publisher-root", secret, b"a sufficiently long passphrase"
    )
    with pytest.raises(OfflinePublisherError):
        public_key_from_encrypted("publisher-root", secret, b"wrong")


@pytest.mark.parametrize("invalid", ["", "XX", "a/b", " root", "x" * 65])
def test_key_identity_fail_closed(invalid: str) -> None:
    with pytest.raises(OfflinePublisherError):
        generate_encrypted_keypair(invalid, b"a sufficiently long passphrase")


def test_short_password_refused() -> None:
    with pytest.raises(OfflinePublisherError):
        generate_encrypted_keypair("publisher-root", b"weak")


def test_malformed_claim_does_not_get_signed() -> None:
    key, public = generate_encrypted_keypair(
        "publisher-root", b"a sufficiently long passphrase"
    )
    for claim in (b"{}", b'{"kind":"registry","kind":"registry"}', b"not json"):
        with pytest.raises(OfflinePublisherError):
            sign_catalog_payload(
                claim,
                key_id=public.key_id,
                encrypted_pem=key,
                password=b"a sufficiently long passphrase",
            )


def test_same_payload_has_stable_signature() -> None:
    key, public = generate_encrypted_keypair(
        "publisher-root", b"a sufficiently long passphrase"
    )
    one = sign_catalog_payload(
        registry(),
        key_id=public.key_id,
        encrypted_pem=key,
        password=b"a sufficiently long passphrase",
    )
    two = sign_catalog_payload(
        registry(),
        key_id=public.key_id,
        encrypted_pem=key,
        password=b"a sufficiently long passphrase",
    )
    assert one == two


def test_module_release_delegation_signed_with_actual_wheel_identity() -> None:
    root_pem, root = generate_encrypted_keypair(
        "publisher-root", b"a sufficiently long passphrase"
    )
    module_pem, module = generate_encrypted_keypair(
        "quillan-publisher", b"another very long passphrase"
    )
    _, integration = generate_encrypted_keypair(
        "suite-integration", b"third strong passphrase"
    )
    ring = TrustedKeyring(
        tuple(
            TrustedPublicKey(k.key_id, base64.b64decode(k.public_key_b64))
            for k in (root, module, integration)
        ),
        (root.key_id,),
        1,
    )
    now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    signed_registry = sign_catalog_payload(
        registry(),
        key_id=root.key_id,
        encrypted_pem=root_pem,
        password=b"a sufficiently long passphrase",
    )
    verified_registry = verify_registry_document(signed_registry, trust=ring, now=now)
    document = {
        "kind": "module_release",
        "schema_version": 1,
        "revision": 1,
        "issued_at": "2026-10-31T00:00:00Z",
        "expires_at": "2026-11-30T00:00:00Z",
        "component_id": "quillan",
        "repository": "Paper-Data-Suite/pds-quillan",
        "distribution": "quillan",
        "releases": [
            {
                "version": "0.10.6",
                "tag": "v0.10.6",
                "wheel": "quillan-0.10.6-py3-none-any.whl",
                "sha256": (
                    "7dbe975c969e60cfda9a8489154450"
                    + "f95c4dc58a8d75afcfad92e7a3c026afbb"
                ),
                "requires_python": ">=3.11",
                "requires_dist": [
                    "numpy<2.5",
                    "opencv-python",
                    "pds-core<0.7,>=0.6.5",
                    "pdf2image",
                    "pypdf<7,>=5",
                    "qrcode[pil]",
                    "reportlab",
                ],
                "console_script": "quillan",
                "console_target": "quillan.cli:main",
                "revoked": False,
            }
        ],
    }
    signed_module = sign_catalog_payload(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
        key_id=module.key_id,
        encrypted_pem=module_pem,
        password=b"another very long passphrase",
    )
    verified_module = verify_module_document(
        signed_module, registry=verified_registry, trust=ring, now=now
    )
    assert verified_module.claims.releases[0].version == "0.10.6"
    assert verified_module.signer_ids == ("quillan-publisher",)


def test_keygen_cli_uses_fresh_encrypted_files_only(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from paper_data_suite.evergreen_offline_publisher_cli import main

    root = Path(str(tmp_path))
    monkeypatch.setattr("getpass.getpass", lambda _: "a sufficiently long passphrase")
    private = root / "key.pem"
    public = root / "public.json"
    args = [
        "keygen",
        "--key-id",
        "publisher-root",
        "--private-file",
        str(private),
        "--public-file",
        str(public),
    ]
    assert main(args) == 0
    assert b"ENCRYPTED PRIVATE KEY" in private.read_bytes()
    assert json.loads(public.read_text())["key_id"] == "publisher-root"
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 1
