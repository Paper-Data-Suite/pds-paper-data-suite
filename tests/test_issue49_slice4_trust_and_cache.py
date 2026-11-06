"""Issue #49 Slice 4: digest-pinned trust and atomically verified local cache."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice3_signature_verification import (
    NOW,
    _integration,
    _module,
    _registry,
    _ring,
    _signed,
)

from paper_data_suite.evergreen_catalog_state import (
    CatalogStateError,
    load_catalog_cache,
    save_catalog_cache,
)
from paper_data_suite.evergreen_trust_provisioning import (
    TrustProvisioningError,
    load_digest_pinned_trust_policy,
)


def _policy() -> bytes:
    ring = _ring()
    return json.dumps(
        {
            "record_type": "pds_evergreen_pinned_keyring",
            "schema_version": 1,
            "revision": 1,
            "keys": [
                {
                    "key_id": key.key_id,
                    "public_key_b64": base64.b64encode(key.public_bytes).decode(
                        "ascii"
                    ),
                }
                for key in ring.keys
            ],
            "root_key_ids": list(ring.root_key_ids),
            "root_threshold": ring.root_threshold,
        },
        sort_keys=True,
    ).encode("utf-8")


def _policy_load(raw: bytes):
    return load_digest_pinned_trust_policy(
        raw, pinned_sha256=hashlib.sha256(raw).hexdigest()
    )


def _blobs(revision: int = 1) -> tuple[bytes, bytes, bytes]:
    return (
        _signed(_registry(revision), "root-primary"),
        _signed(_module(revision), "quillan-primary"),
        _signed(_integration(revision), "suite-integration"),
    )


def _save(path: Path, revision: int = 1, *, now=NOW):
    registry, module, integration = _blobs(revision)
    return save_catalog_cache(
        path,
        registry_envelope=registry,
        module_envelopes=(module,),
        integration_envelopes=(integration,),
        trust=_ring(),
        now=now,
    )


def test_exact_independently_pinned_policy_provisions_trusted_keyring() -> None:
    policy = _policy()
    result = _policy_load(policy)
    assert result.sha256 == hashlib.sha256(policy).hexdigest()
    assert result.policy_revision == 1
    assert result.keyring == _ring()
    assert not hasattr(result, "can_launch")


def test_wrong_root_policy_digest_fails_before_parsing() -> None:
    with pytest.raises(TrustProvisioningError, match="independent pin"):
        load_digest_pinned_trust_policy(_policy(), pinned_sha256="0" * 64)
    with pytest.raises(TrustProvisioningError, match="independent SHA-256"):
        load_digest_pinned_trust_policy(_policy(), pinned_sha256="bad")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update({"schema_version": 2}),
        lambda d: d.update({"revision": True}),
        lambda d: d.update({"root_key_ids": ["unknown-root"]}),
        lambda d: d.update({"root_threshold": 999}),
        lambda d: d.update({"root_threshold": True}),
        lambda d: d.update({"keys": []}),
        lambda d: d.update({"unknown": "bad"}),
        lambda d: d["keys"][0].update({"public_key_b64": "bad"}),
        lambda d: d["keys"].append(d["keys"][0]),
    ],
)
def test_pin_does_not_overrule_structural_security(mutate: Any) -> None:
    document = json.loads(_policy())
    mutate(document)
    raw = json.dumps(document).encode("utf-8")
    with pytest.raises(TrustProvisioningError):
        _policy_load(raw)


def test_duplicate_policy_json_key_rejected_even_when_digest_matches() -> None:
    raw = _policy().replace(
        b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1'
    )
    with pytest.raises(TrustProvisioningError):
        _policy_load(raw)


def test_real_signed_snapshot_persists_and_reverifies(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    snapshot = _save(file)
    assert snapshot.registry.claims.window.revision == 1
    assert len(snapshot.modules) == 1
    assert len(snapshot.integrations) == 1
    assert file.is_file()
    assert "private" not in file.read_text(encoding="utf-8")
    recovered = load_catalog_cache(file, trust=_ring(), now=NOW)
    assert recovered is not None
    assert recovered.registry == snapshot.registry
    assert recovered.modules == snapshot.modules
    assert recovered.integrations == snapshot.integrations
    assert not hasattr(recovered, "can_launch")


def test_empty_cache_is_not_trusted_or_pretended_present(tmp_path: Path) -> None:
    assert load_catalog_cache(tmp_path / "missing.json", trust=_ring(), now=NOW) is None


def test_revision_can_advance_but_lower_version_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file, revision=1)
    upgraded = _save(file, revision=2, now=NOW + timedelta(seconds=1))
    assert upgraded.registry.claims.window.revision == 2
    before = file.read_bytes()
    with pytest.raises(CatalogStateError, match="verification"):
        _save(file, revision=1, now=NOW + timedelta(seconds=2))
    assert file.read_bytes() == before


def test_same_revision_changed_signed_payload_is_equivocation(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file)
    before = file.read_bytes()
    altered = _module()
    altered["releases"][0]["sha256"] = "b" * 64
    registry, _, integration = _blobs()
    with pytest.raises(CatalogStateError, match="verification"):
        save_catalog_cache(
            file,
            registry_envelope=registry,
            module_envelopes=(_signed(altered, "quillan-primary"),),
            integration_envelopes=(integration,),
            trust=_ring(),
            now=NOW + timedelta(seconds=1),
        )
    assert file.read_bytes() == before


def test_unsigned_or_wrong_publisher_snapshot_never_written(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    registry, _, integration = _blobs()
    with pytest.raises(CatalogStateError, match="verification"):
        save_catalog_cache(
            file,
            registry_envelope=registry,
            module_envelopes=(_signed(_module(), "portia-primary"),),
            integration_envelopes=(integration,),
            trust=_ring(),
            now=NOW,
        )
    assert not file.exists()


def test_cache_rejects_modified_stored_signature_and_payload(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file)
    original = file.read_bytes()
    data = json.loads(original)
    data["registry_envelope_b64"] = base64.b64encode(b"garbage").decode()
    file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CatalogStateError):
        load_catalog_cache(file, trust=_ring(), now=NOW)


def test_cache_rejects_switched_independent_trust_roots(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file)
    original = file.read_bytes()
    from paper_data_suite.evergreen_catalog_verification import TrustedKeyring

    other = TrustedKeyring(_ring().keys, ("root-backup",), 1)
    with pytest.raises(CatalogStateError):
        load_catalog_cache(file, trust=other, now=NOW)
    assert file.read_bytes() == original


def test_expired_cache_cannot_authorize_new_online_metadata(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file)
    with pytest.raises(CatalogStateError, match="verification"):
        load_catalog_cache(file, trust=_ring(), now=NOW + timedelta(days=40))
    # The expired signed bytes remain on disk; installed-app availability must
    # be determined by a later, independently authenticated installation receipt.
    assert file.exists()


def test_local_clock_rollback_prevents_cache_replacement(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file, now=NOW + timedelta(seconds=2))
    old = file.read_bytes()
    with pytest.raises(CatalogStateError, match="clock rollback"):
        _save(file, now=NOW)
    assert file.read_bytes() == old


def test_stale_lock_refuses_mutation_without_overwriting(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    lock = tmp_path / "catalog.json.lock"
    lock.write_text("exists", encoding="utf-8")
    with pytest.raises(CatalogStateError, match="locked"):
        _save(file)
    assert lock.exists()
    assert not file.exists()


def test_symlinked_cache_destination_refuses_mutation(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"sensitive")
    link = tmp_path / "catalog.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(CatalogStateError, match="symlinks"):
        _save(link)
    assert outside.read_bytes() == b"sensitive"


def test_reject_cached_duplicate_json_and_unknown_fields(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file)
    raw = file.read_bytes()
    file.write_bytes(
        raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
    )
    with pytest.raises(CatalogStateError):
        load_catalog_cache(file, trust=_ring(), now=NOW)
    file.write_bytes(
        raw.replace(b'"schema_version":1', b'"schema_version":1,"unknown":1')
    )
    with pytest.raises(CatalogStateError):
        load_catalog_cache(file, trust=_ring(), now=NOW)


def test_reject_oversized_cache(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    file.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(CatalogStateError, match="size limit"):
        load_catalog_cache(file, trust=_ring(), now=NOW)


def test_missing_previous_document_is_not_silently_dropped(tmp_path: Path) -> None:
    file = tmp_path / "catalog.json"
    _save(file)
    before = file.read_bytes()
    registry, module, _ = _blobs(revision=2)
    with pytest.raises(CatalogStateError, match="omit feature"):
        save_catalog_cache(
            file,
            registry_envelope=registry,
            module_envelopes=(module,),
            integration_envelopes=(),
            trust=_ring(),
            now=NOW + timedelta(seconds=1),
        )
    assert file.read_bytes() == before
