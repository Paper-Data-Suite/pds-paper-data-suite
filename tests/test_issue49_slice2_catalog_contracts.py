"""Issue #49 Slice 2: malformed signed-looking bytes remain untrusted."""

from __future__ import annotations

import base64
import copy
import json
from typing import Any

import pytest

from paper_data_suite.evergreen_catalog_contracts import (
    CatalogContractError,
    IntegrationClaims,
    ModuleReleaseClaims,
    RegistryClaims,
    parse_unsigned_claims,
    parse_unverified_envelope,
)

_DIGEST = "a" * 64
_SIG = base64.b64encode(b"\x42" * 64).decode("ascii")


def _window() -> dict[str, object]:
    return {
        "revision": 1,
        "issued_at": "2026-10-17T16:00:00Z",
        "expires_at": "2026-11-17T16:00:00Z",
    }


def _registry() -> dict[str, Any]:
    return {
        **_window(),
        "kind": "registry",
        "schema_version": 1,
        "modules": [
            {
                "component_id": "quillan",
                "repository": "Paper-Data-Suite/pds-quillan",
                "distribution": "quillan",
                "signing_key_ids": ["quillan-primary-2026"],
            },
            {
                "component_id": "portia",
                "repository": "Paper-Data-Suite/pds-portia",
                "distribution": "pds-portia",
                "signing_key_ids": ["portia-primary-2026"],
            },
        ],
        "integration_signing_key_ids": ["suite-integration-2026"],
    }


def _module() -> dict[str, Any]:
    return {
        **_window(),
        "kind": "module_release",
        "schema_version": 1,
        "component_id": "quillan",
        "repository": "Paper-Data-Suite/pds-quillan",
        "distribution": "quillan",
        "releases": [
            {
                "version": "0.10.6",
                "tag": "v0.10.6",
                "wheel": "quillan-0.10.6-py3-none-any.whl",
                "sha256": _DIGEST,
                "requires_python": ">=3.11,<3.15",
                "requires_dist": ["pds-core>=0.6.5,<0.7"],
                "console_script": "quillan",
                "console_target": "quillan.cli:main",
                "revoked": False,
            }
        ],
    }


def _integration() -> dict[str, Any]:
    return {
        **_window(),
        "kind": "integration",
        "schema_version": 1,
        "feature_id": "meridian.quillan-evidence",
        "result": "passed",
        "evidence_sha256": "b" * 64,
        "artifacts": [
            {"component_id": "core", "wheel_sha256": "c" * 64},
            {"component_id": "quillan", "wheel_sha256": _DIGEST},
            {"component_id": "meridian", "wheel_sha256": "d" * 64},
        ],
        "python_minors": ["3.11", "3.13"],
        "platforms": ["win_amd64", "win_arm64"],
    }


def _blob(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _envelope(
    document: dict[str, Any],
    *,
    signatures: list[dict[str, object]] | None = None,
) -> bytes:
    records = (
        signatures
        if signatures is not None
        else [
            {
                "key_id": "quillan-primary-2026",
                "algorithm": "ed25519",
                "signature_b64": _SIG,
            }
        ]
    )
    return _blob(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(_blob(document)).decode("ascii"),
            "signatures": records,
        }
    )


@pytest.mark.parametrize(
    ("factory", "expected_type"),
    [
        (_registry, RegistryClaims),
        (_module, ModuleReleaseClaims),
        (_integration, IntegrationClaims),
    ],
)
def test_three_strict_claim_types_preserve_signed_bytes_but_do_not_authenticate(
    factory: Any, expected_type: type[object]
) -> None:
    original = _blob(factory())
    envelope = parse_unverified_envelope(_envelope(factory()))
    assert envelope.payload_bytes == original
    assert isinstance(envelope.claims, expected_type)
    assert len(envelope.signatures) == 1
    assert len(envelope.signatures[0].signature) == 64
    assert envelope.signatures[0].key_id == "quillan-primary-2026"
    assert not hasattr(envelope, "trusted")
    assert not hasattr(envelope, "verified")
    assert not hasattr(envelope.claims, "can_launch")


def test_future_release_version_is_data_not_launcher_authorization() -> None:
    data = _module()
    data["releases"][0]["version"] = "42.0.0"
    data["releases"][0]["tag"] = "v42.0.0"
    claims = parse_unsigned_claims(_blob(data))
    assert isinstance(claims, ModuleReleaseClaims)
    assert claims.releases[0].version == "42.0.0"
    assert not hasattr(claims, "release_trust")


def test_revocation_record_may_be_parsed_without_silently_becoming_permission() -> None:
    data = _module()
    data["releases"][0]["revoked"] = True
    claims = parse_unsigned_claims(_blob(data))
    assert isinstance(claims, ModuleReleaseClaims)
    assert claims.releases[0].revoked is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update({"schema_version": 2}),
        lambda x: x.update({"kind": "arbitrary"}),
        lambda x: x.update({"revision": True}),
        lambda x: x.update({"revision": 0}),
        lambda x: x.update({"issued_at": "2026-10-17"}),
        lambda x: x.update({"issued_at": "2026-10-17T16:00:00+00:00"}),
        lambda x: x.update({"expires_at": "2026-10-16T16:00:00Z"}),
        lambda x: x.update({"expires_at": "2026-10-17T16:00:00Z"}),
        lambda x: x.update({"unrecognized": True}),
        lambda x: x.update({"releases": []}),
        lambda x: x.update({"component_id": "../evil"}),
        lambda x: x.update({"repository": "https://example.com/anything"}),
        lambda x: x.update({"distribution": "../other"}),
        lambda x: x["releases"][0].update({"tag": "v0.10.7"}),
        lambda x: x["releases"][0].update({"sha256": "A" * 64}),
        lambda x: x["releases"][0].update({"sha256": "z" * 64}),
        lambda x: x["releases"][0].update({"wheel": "../../evil.whl"}),
        lambda x: x["releases"][0].update({"console_target": "os.system"}),
        lambda x: x["releases"][0].update({"console_script": "../quillan"}),
        lambda x: x["releases"][0].update({"revoked": 1}),
        lambda x: x["releases"][0].update({"version": "0.11.0rc1"}),
        lambda x: x["releases"][0].update({"version": "0.11.0.dev1"}),
        lambda x: x["releases"][0].update({"requires_dist": ["dep"] * 100}),
        lambda x: x.update({"releases": x["releases"] * 2}),
    ],
)
def test_invalid_release_claims_are_rejected(mutation: Any) -> None:
    data = copy.deepcopy(_module())
    mutation(data)
    with pytest.raises(CatalogContractError):
        parse_unsigned_claims(_blob(data))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update({"modules": x["modules"] * 2}),
        lambda x: x["modules"][0].update({"signing_key_ids": []}),
        lambda x: x["modules"][0].update({"signing_key_ids": ["bad key"]}),
        lambda x: x["modules"][0].update({"distribution": "pds-portia"}),
        lambda x: x.update({"integration_signing_key_ids": []}),
        lambda x: x["modules"][0].update({"repository": "../../../foo"}),
    ],
)
def test_registry_rejects_unauthorized_shapes_and_duplicates(mutation: Any) -> None:
    data = copy.deepcopy(_registry())
    mutation(data)
    with pytest.raises(CatalogContractError):
        parse_unsigned_claims(_blob(data))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update({"result": "available"}),
        lambda x: x.update({"artifacts": x["artifacts"] * 2}),
        lambda x: x.update({"python_minors": ["3.10"]}),
        lambda x: x.update({"platforms": ["linux;sh"]}),
        lambda x: x.update({"evidence_sha256": "0"}),
        lambda x: x.update({"feature_id": "x"}),
    ],
)
def test_integration_attestation_claims_are_strict(mutation: Any) -> None:
    data = copy.deepcopy(_integration())
    mutation(data)
    with pytest.raises(CatalogContractError):
        parse_unsigned_claims(_blob(data))


def test_reject_duplicate_json_members_in_payload() -> None:
    payload = _blob(_module()).decode("utf-8")
    payload = payload.replace(
        '"kind":"module_release",', '"kind":"module_release","kind":"module_release",'
    )
    with pytest.raises(CatalogContractError, match="invalid signed payload JSON"):
        parse_unsigned_claims(payload.encode("utf-8"))


def test_reject_duplicate_json_members_in_envelope() -> None:
    blob = _envelope(_module()).decode("utf-8")
    blob = blob.replace(
        '"envelope_version":1,', '"envelope_version":1,"envelope_version":1,'
    )
    with pytest.raises(CatalogContractError):
        parse_unverified_envelope(blob.encode("utf-8"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update({"envelope_version": 2}),
        lambda x: x.update({"envelope_version": True}),
        lambda x: x.update({"signatures": []}),
        lambda x: x.update({"signatures": x["signatures"] * 2}),
        lambda x: x["signatures"][0].update({"algorithm": "none"}),
        lambda x: x["signatures"][0].update({"algorithm": "rsa"}),
        lambda x: x["signatures"][0].update({"key_id": "not trusted!"}),
        lambda x: x["signatures"][0].update({"signature_b64": "invalid ***"}),
        lambda x: x["signatures"][0].update(
            {"signature_b64": base64.b64encode(b"a" * 63).decode()}
        ),
        lambda x: x.update({"payload_b64": "YQ"}),
        lambda x: x.update({"unrecognized": 12}),
    ],
)
def test_bad_envelopes_rejected(mutation: Any) -> None:
    data = json.loads(_envelope(_module()))
    mutation(data)
    with pytest.raises(CatalogContractError):
        parse_unverified_envelope(_blob(data))


def test_reject_bad_input_types_and_payload_limits() -> None:
    with pytest.raises(CatalogContractError):
        parse_unverified_envelope(b"")
    with pytest.raises(CatalogContractError):
        parse_unverified_envelope(b" " * (192 * 1024 + 1))
    with pytest.raises(CatalogContractError):
        parse_unsigned_claims(b"x" * (128 * 1024 + 1))
    with pytest.raises(CatalogContractError):
        parse_unsigned_claims(b"\xff")
    with pytest.raises(CatalogContractError):
        parse_unsigned_claims(b"[]")


def test_invalid_signature_bytes_are_only_shape_checked_not_crypto_verified() -> None:
    # Correct-length garbage cannot become a signed approval by parsing.
    unverified = parse_unverified_envelope(_envelope(_module()))
    assert unverified.signatures[0].signature == b"\x42" * 64
    assert unverified.claims is not None
    assert type(unverified).__name__ == "UnverifiedEnvelope"
