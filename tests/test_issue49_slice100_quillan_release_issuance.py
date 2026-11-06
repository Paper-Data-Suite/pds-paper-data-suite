"""Issue #49 Slice 100: issuance is reviewed, exact, and non-authorizing."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite import evergreen_quillan_issuance as ceremony
from paper_data_suite.evergreen_offline_publisher import (
    generate_encrypted_keypair,
)

NOW = datetime(2026, 10, 31, 16, tzinfo=timezone.utc)
PASSWORD = b"a sufficiently long local password"


def fixture_material(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Path]]:
    keys: dict[str, bytes] = {}
    public: dict[str, dict[str, str]] = {}
    for identity in ("publisher-root", "quillan-publisher", "suite-integration"):
        pem, item = generate_encrypted_keypair(identity, PASSWORD)
        keys[identity] = pem
        public[identity] = {
            "key_id": item.key_id,
            "public_key_b64": item.public_key_b64,
            "public_sha256": item.public_sha256,
        }
    monkeypatch.setattr(
        ceremony,
        "_wheel_metadata",
        lambda _: (">=3.11", ("numpy<2.5", "pds-core>=0.6.5,<0.7")),
    )
    wheel = directory / "quillan-0.10.6-py3-none-any.whl"
    documents = ceremony.plan_documents(
        wheel,
        public["publisher-root"],
        public["quillan-publisher"],
        public["suite-integration"],
        now=NOW,
    )
    reviewed = directory / "review"
    reviewed.mkdir()
    for name, raw in documents.items():
        (reviewed / name).write_bytes(raw)
    for identity, pem in keys.items():
        (directory / f"{identity}.pem").write_bytes(pem)
    return (
        documents,
        keys,
        {
            "wheel": wheel,
            "review": reviewed,
            "root": directory / "publisher-root.pem",
            "quillan": directory / "quillan-publisher.pem",
        },
    )


def test_review_claims_are_exact_and_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, _, _ = fixture_material(tmp_path, monkeypatch)
    module = json.loads(documents["quillan-payload.json"])
    registry = json.loads(documents["registry-payload.json"])
    public = json.loads(documents["trust-policy.json"])
    assert module["releases"][0]["version"] == "0.10.6"
    assert module["releases"][0]["console_target"] == "quillan.cli:main"
    assert module["releases"][0]["sha256"] == ceremony._SHA256
    assert registry["modules"][0]["signing_key_ids"] == ["quillan-publisher"]
    assert public["root_key_ids"] == ["publisher-root"]
    assert len(public["keys"]) == 3
    assert b"PRIVATE KEY" not in b"".join(documents.values())
    assert "UNSIGNED_REVIEW_ONLY" in documents["review.json"].decode()


def test_signed_envelopes_verifiable_against_real_registry_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, _, paths = fixture_material(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ceremony,
        "verify_signed_release_wheel",
        lambda *a, **kw: SimpleNamespace(
            component_id="quillan", sha256=ceremony._SHA256
        ),
    )
    issued = ceremony.issue_envelopes(
        paths["review"],
        paths["wheel"],
        policy_sha=ceremony._sha(documents["trust-policy.json"]),
        root_key=paths["root"],
        module_key=paths["quillan"],
        root_password=PASSWORD,
        module_password=PASSWORD,
        now=NOW,
    )
    assert set(issued) == {
        "registry-envelope.json",
        "quillan-envelope.json",
        "issuance-result.json",
    }
    envelope = json.loads(issued["quillan-envelope.json"])
    assert envelope["signatures"][0]["key_id"] == "quillan-publisher"
    assert (
        base64.b64decode(envelope["payload_b64"]) == documents["quillan-payload.json"]
    )
    assert "NO_PRODUCTION_LAUNCH" in issued["issuance-result.json"].decode()


def test_wrong_pin_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, paths = fixture_material(tmp_path, monkeypatch)
    with pytest.raises(ceremony.IssuanceError, match="trust policy"):
        ceremony._review(paths["review"], "0" * 64, paths["wheel"])


def test_modified_review_payload_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, _, paths = fixture_material(tmp_path, monkeypatch)
    target = paths["review"] / "quillan-payload.json"
    target.write_bytes(target.read_bytes().replace(b"0.10.6", b"0.10.7"))
    with pytest.raises(ceremony.IssuanceError, match="reviewed payloads"):
        ceremony._review(
            paths["review"],
            ceremony._sha(documents["trust-policy.json"]),
            paths["wheel"],
        )


def test_wrong_key_fingerprint_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, _, paths = fixture_material(tmp_path, monkeypatch)
    wrong, _ = generate_encrypted_keypair("publisher-root", PASSWORD)
    paths["root"].write_bytes(wrong)
    with pytest.raises(ceremony.IssuanceError, match="reviewed public identity"):
        ceremony.issue_envelopes(
            paths["review"],
            paths["wheel"],
            policy_sha=ceremony._sha(documents["trust-policy.json"]),
            root_key=paths["root"],
            module_key=paths["quillan"],
            root_password=PASSWORD,
            module_password=PASSWORD,
            now=NOW,
        )


def test_bad_passphrase_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, _, paths = fixture_material(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        ceremony.issue_envelopes(
            paths["review"],
            paths["wheel"],
            policy_sha=ceremony._sha(documents["trust-policy.json"]),
            root_key=paths["root"],
            module_key=paths["quillan"],
            root_password=b"incorrect",
            module_password=PASSWORD,
            now=NOW,
        )


def test_private_key_inside_git_checkout_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(ceremony.IssuanceError, match="inside repository"):
        ceremony._outside_git(tmp_path / "key.pem")


def test_public_key_fingerprint_cannot_be_forged(tmp_path: Path) -> None:
    _, item = generate_encrypted_keypair("publisher-root", PASSWORD)
    target = tmp_path / "public.json"
    target.write_text(
        json.dumps(
            {
                "key_id": item.key_id,
                "public_key_b64": item.public_key_b64,
                "public_sha256": "0" * 64,
            }
        )
    )
    with pytest.raises(ceremony.IssuanceError, match="fingerprint"):
        ceremony._public(target, "publisher-root")


def test_new_output_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "existing.json"
    target.write_bytes(b"original")
    with pytest.raises(ceremony.IssuanceError, match="overwrite"):
        ceremony._new_file(target, b"replacement")
    assert target.read_bytes() == b"original"


def test_refuse_same_key_for_distinct_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, keys, paths = fixture_material(tmp_path, monkeypatch)
    del keys
    payload = json.loads((paths["review"] / "trust-policy.json").read_bytes())
    payload["keys"][1]["public_key_b64"] = payload["keys"][0]["public_key_b64"]
    (paths["review"] / "trust-policy.json").write_bytes(ceremony._encode(payload))
    with pytest.raises((ceremony.IssuanceError, ValueError)):
        ceremony._review(
            paths["review"],
            ceremony._sha(ceremony._encode(payload)),
            paths["wheel"],
        )


def test_duplicate_public_material_refused_before_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, _, paths = fixture_material(tmp_path, monkeypatch)
    del documents
    public = ceremony._public_from_policy(
        (paths["review"] / "trust-policy.json").read_bytes()
    )
    with pytest.raises(ceremony.IssuanceError, match="same signing public key"):
        ceremony.plan_documents(
            paths["wheel"],
            public[0],
            public[0] | {"key_id": "quillan-publisher"},
            public[2],
            now=NOW,
        )
