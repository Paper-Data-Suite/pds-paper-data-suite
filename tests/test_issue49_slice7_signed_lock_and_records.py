"""Issue #49 Slice 7: genuine root signatures and non-authorizing stage records."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import sysconfig
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice3_signature_verification import (
    NOW,
    _encode,
    _private,
    _registry,
    _ring,
    _signed,
)
from test_issue49_slice6_wheelhouse import _add

from paper_data_suite.evergreen_dependency_lock import (
    DependencyLockError,
    verify_signed_dependency_lock,
    verify_signed_locked_wheelhouse,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
    prepare_composition_record,
    serialize_prepared_record,
    verify_prepared_record_against_wheelhouse,
)

_CONTEXT = b"pds-evergreen-wheelhouse-lock-v1\x00"
_TX = "a" * 32


def _registry_bytes(*, revision: int = 1) -> bytes:
    return _signed(_registry(revision), "root-primary")


def _claims(pins: tuple[Any, ...], *, revision: int = 1) -> dict[str, Any]:
    return {
        "record_type": "pds_evergreen_dependency_lock",
        "schema_version": 1,
        "revision": revision,
        "issued_at": "2026-10-17T16:00:00Z",
        "expires_at": "2026-11-17T16:00:00Z",
        "registry_payload_sha256": hashlib.sha256(_encode(_registry())).hexdigest(),
        "python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sysconfig.get_platform().lower(),
        "roots": ["demo-app"],
        "wheels": [{"filename": pin.filename, "sha256": pin.sha256} for pin in pins],
    }


def _signed_lock(
    claims: dict[str, Any],
    *signers: str,
    body: bytes | None = None,
    missing_domain: bool = False,
) -> bytes:
    payload = body if body is not None else _encode(claims)
    message = payload if missing_domain else _CONTEXT + payload
    return _encode(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signatures": [
                {
                    "key_id": signer,
                    "algorithm": "ed25519",
                    "signature_b64": base64.b64encode(
                        _private(signer).sign(message)
                    ).decode("ascii"),
                }
                for signer in signers
            ],
        }
    )


def _setup(folder: Path) -> tuple[bytes, bytes, dict[str, Any]]:
    app = _add(folder)
    core = _add(folder, name="demo-core", version="2.4.0", requirements=())
    claims = _claims((app, core))
    return _registry_bytes(), _signed_lock(claims, "root-primary"), claims


def _verify(registry: bytes, lock: bytes, **kwargs: Any):
    return verify_signed_dependency_lock(
        lock, registry_envelope=registry, trust=_ring(), now=NOW, **kwargs
    )


def _wheelhouse(folder: Path, registry: bytes, lock: bytes, **kwargs: Any):
    return verify_signed_locked_wheelhouse(
        folder,
        lock_envelope=lock,
        registry_envelope=registry,
        trust=_ring(),
        now=NOW,
        **kwargs,
    )


def test_root_signed_locked_closure_is_wheelhouse_only(tmp_path: Path) -> None:
    registry, envelope, _ = _setup(tmp_path)
    result = _wheelhouse(tmp_path, registry, envelope)
    assert result.inspection.roots == ("demo-app",)
    assert len(result.inspection.wheels) == 2
    assert result.inspection.dependency_edges == (("demo-app", "demo-core"),)
    assert result.lock.signers == ("root-primary",)
    assert result.lock.checkpoint.payload_sha256 == result.lock.payload_sha256
    assert not hasattr(result.lock, "can_launch")
    assert not hasattr(result, "installed")


def test_exact_same_signed_lock_checkpoint_is_idempotent(tmp_path: Path) -> None:
    registry, envelope, _ = _setup(tmp_path)
    first = _verify(registry, envelope)
    second = _verify(registry, envelope, checkpoint=first.checkpoint)
    assert second == first


def test_higher_revision_advances_checkpoint(tmp_path: Path) -> None:
    registry, envelope, claims = _setup(tmp_path)
    first = _verify(registry, envelope)
    claims["revision"] = 2
    next_doc = _signed_lock(claims, "root-primary")
    updated = _verify(registry, next_doc, checkpoint=first.checkpoint)
    assert updated.revision == 2
    with pytest.raises(DependencyLockError, match="rollback"):
        _verify(registry, envelope, checkpoint=updated.checkpoint)


def test_same_revision_different_signed_body_refused(tmp_path: Path) -> None:
    registry, envelope, claims = _setup(tmp_path)
    before = _verify(registry, envelope)
    claims["roots"] = ["demo-core"]
    with pytest.raises(DependencyLockError, match="equivocation"):
        _verify(
            registry,
            _signed_lock(claims, "root-primary"),
            checkpoint=before.checkpoint,
        )


def test_pinned_registry_identity_cannot_be_swapped(tmp_path: Path) -> None:
    registry, envelope, claims = _setup(tmp_path)
    claims["registry_payload_sha256"] = "b" * 64
    with pytest.raises(DependencyLockError, match="different registry"):
        _verify(registry, _signed_lock(claims, "root-primary"))


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda x: x.update({"schema_version": 2}), "identity"),
        (lambda x: x.update({"revision": True}), "revision"),
        (lambda x: x.update({"revision": -1}), "revision"),
        (lambda x: x.update({"roots": []}), "roots"),
        (lambda x: x.update({"roots": ["demo-app", "demo_app"]}), "duplicate"),
        (lambda x: x.update({"wheels": []}), "wheel count"),
        (lambda x: x.update({"wheels": x["wheels"] * 2}), "duplicate"),
        (lambda x: x["wheels"][0].update({"sha256": "B" * 64}), "wheel pin"),
        (lambda x: x["wheels"][0].update({"filename": "../evil.whl"}), "wheel pin"),
        (lambda x: x.update({"python_minor": "3.10"}), "python minor"),
        (lambda x: x.update({"platform": "windows-wrong"}), "different platform"),
        (lambda x: x.update({"expires_at": "2026-10-16T00:00:00Z"}), "expired"),
        (lambda x: x.update({"issued_at": "2026-10-18T00:00:00Z"}), "expired"),
        (lambda x: x.update({"new_field": "unexpected"}), "contract"),
    ],
)
def test_invalid_even_if_root_signed(
    tmp_path: Path, mutation: Any, expected: str
) -> None:
    registry, _, original = _setup(tmp_path)
    claims = copy.deepcopy(original)
    mutation(claims)
    with pytest.raises(DependencyLockError, match=expected):
        _verify(registry, _signed_lock(claims, "root-primary"))


@pytest.mark.parametrize("signer", ["attacker", "quillan-primary", "suite-integration"])
def test_non_root_key_cannot_sign_lock(tmp_path: Path, signer: str) -> None:
    registry, _, claims = _setup(tmp_path)
    with pytest.raises(DependencyLockError, match="unauthorized"):
        _verify(registry, _signed_lock(claims, signer))


def test_signature_must_be_domain_separated(tmp_path: Path) -> None:
    registry, _, claims = _setup(tmp_path)
    with pytest.raises(DependencyLockError, match="signature"):
        _verify(registry, _signed_lock(claims, "root-primary", missing_domain=True))


def test_both_root_signers_required_when_threshold_two(tmp_path: Path) -> None:
    _, envelope, claims = _setup(tmp_path)
    both_registry = _signed(_registry(), "root-primary", "root-backup")
    with pytest.raises(DependencyLockError, match="insufficient"):
        verify_signed_dependency_lock(
            envelope,
            registry_envelope=both_registry,
            trust=_ring(threshold=2),
            now=NOW,
        )
    lock = _signed_lock(claims, "root-primary", "root-backup")
    result = verify_signed_dependency_lock(
        lock, registry_envelope=both_registry, trust=_ring(threshold=2), now=NOW
    )
    assert len(result.signers) == 2


def test_forged_payload_or_signature_is_rejected(tmp_path: Path) -> None:
    registry, envelope, claims = _setup(tmp_path)
    changed = copy.deepcopy(claims)
    changed["revision"] = 3
    corrupted = json.loads(envelope)
    corrupted["payload_b64"] = base64.b64encode(_encode(changed)).decode()
    with pytest.raises(DependencyLockError, match="signature"):
        _verify(registry, _encode(corrupted))
    assert _verify(registry, envelope).revision == 1


@pytest.mark.parametrize(
    "change",
    ["wrong-keys", "bad-base64", "duplicate-signer", "no-signatures", "unknown-field"],
)
def test_bad_signed_envelope_fails(tmp_path: Path, change: str) -> None:
    registry, envelope, _ = _setup(tmp_path)
    obj = json.loads(envelope)
    if change == "wrong-keys":
        obj["envelope_version"] = True
    elif change == "bad-base64":
        obj["payload_b64"] = "AA"
    elif change == "duplicate-signer":
        obj["signatures"] *= 2
    elif change == "no-signatures":
        obj["signatures"] = []
    else:
        obj["unknown"] = 1
    with pytest.raises(DependencyLockError):
        _verify(registry, _encode(obj))


def test_duplicate_json_members_rejected(tmp_path: Path) -> None:
    registry, envelope, _ = _setup(tmp_path)
    blob = envelope.replace(
        b'"envelope_version":1', b'"envelope_version":1,"envelope_version":1'
    )
    with pytest.raises(DependencyLockError, match="invalid.*JSON"):
        _verify(registry, blob)


def test_mismatched_signed_hash_cannot_authorize_tampered_wheel(tmp_path: Path) -> None:
    registry, envelope, _ = _setup(tmp_path)
    path = tmp_path / "demo_app-1.0.0-py3-none-any.whl"
    path.write_bytes(path.read_bytes() + b"injected bytes")
    with pytest.raises(DependencyLockError, match="byte/dependency"):
        _wheelhouse(tmp_path, registry, envelope)


def test_even_signed_extra_wheel_must_be_reachable(tmp_path: Path) -> None:
    app = _add(tmp_path)
    core = _add(tmp_path, name="demo-core", version="2.4.0", requirements=())
    spare = _add(tmp_path, name="spare", requirements=())
    claims = _claims((app, core, spare))
    with pytest.raises(DependencyLockError, match="byte/dependency"):
        _wheelhouse(tmp_path, _registry_bytes(), _signed_lock(claims, "root-primary"))


def _prepared(tmp_path: Path) -> tuple[bytes, bytes, bytes]:
    registry, lock, _ = _setup(tmp_path)
    candidate = prepare_composition_record(
        tmp_path,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
        transaction_id=_TX,
    )
    return registry, lock, serialize_prepared_record(candidate)


def test_prepared_record_round_trip_is_not_installed_receipt(tmp_path: Path) -> None:
    registry, lock, data = _prepared(tmp_path)
    record = parse_unverified_prepared_record(data)
    assert record.transaction_id == _TX
    assert record.lock_revision == 1
    assert len(record.wheels) == 2
    assert record.dependency_edges == (("demo-app", "demo-core"),)
    assert b'"phase":"prepared_not_installed"' in data
    assert not hasattr(record, "can_launch")
    assert not hasattr(record, "installed")
    assert (
        verify_prepared_record_against_wheelhouse(
            data,
            tmp_path,
            registry_envelope=registry,
            lock_envelope=lock,
            trust=_ring(),
            now=NOW,
        )
        == record
    )


def test_caller_cannot_self_authenticate_changed_record(tmp_path: Path) -> None:
    registry, lock, data = _prepared(tmp_path)
    values = json.loads(data)
    values["wheels"][0]["sha256"] = "b" * 64
    forged = _encode(values)
    assert parse_unverified_prepared_record(forged).wheels[0].sha256 == "b" * 64
    with pytest.raises(PreparedRecordError, match="mismatches"):
        verify_prepared_record_against_wheelhouse(
            forged,
            tmp_path,
            registry_envelope=registry,
            lock_envelope=lock,
            trust=_ring(),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda x: x.update({"phase": "installed"}), "phase"),
        (lambda x: x.update({"schema_version": 2}), "phase"),
        (lambda x: x.update({"transaction_id": "bad"}), "transaction ID"),
        (lambda x: x.update({"lock_revision": True}), "revision"),
        (lambda x: x.update({"unknown": 1}), "unknown"),
        (lambda x: x.update({"roots": []}), "roots"),
        (lambda x: x.update({"wheels": []}), "wheel count"),
        (lambda x: x.update({"dependency_edges": [["a"]]}), "edge"),
        (lambda x: x.update({"prepared_at": "yesterday"}), "prepared_at"),
    ],
)
def test_invalid_prepared_records_refused(
    tmp_path: Path, change: Any, error: str
) -> None:
    _, _, data = _prepared(tmp_path)
    values = json.loads(data)
    change(values)
    with pytest.raises(PreparedRecordError, match=error):
        parse_unverified_prepared_record(_encode(values))


def test_prepared_record_requires_canonical_format(tmp_path: Path) -> None:
    _, _, data = _prepared(tmp_path)
    obj = json.loads(data)
    noncanonical = json.dumps(obj, indent=2).encode()
    with pytest.raises(PreparedRecordError, match="canonical"):
        parse_unverified_prepared_record(noncanonical)


def test_prepared_record_future_time_refused(tmp_path: Path) -> None:
    registry, lock, data = _prepared(tmp_path)
    with pytest.raises(PreparedRecordError, match="future"):
        verify_prepared_record_against_wheelhouse(
            data,
            tmp_path,
            registry_envelope=registry,
            lock_envelope=lock,
            trust=_ring(),
            now=NOW - timedelta(seconds=1),
        )


def test_replay_prepared_record_after_wheel_edit_fails(tmp_path: Path) -> None:
    registry, lock, data = _prepared(tmp_path)
    wheel = tmp_path / "demo_core-2.4.0-py3-none-any.whl"
    wheel.write_bytes(wheel.read_bytes() + b"tampered")
    with pytest.raises(DependencyLockError):
        verify_prepared_record_against_wheelhouse(
            data,
            tmp_path,
            registry_envelope=registry,
            lock_envelope=lock,
            trust=_ring(),
            now=NOW,
        )


def test_record_refuses_signed_lock_revision_change(tmp_path: Path) -> None:
    registry, lock, data = _prepared(tmp_path)
    claims = json.loads(base64.b64decode(json.loads(lock)["payload_b64"]))
    claims["revision"] += 1
    updated = _signed_lock(claims, "root-primary")
    with pytest.raises(PreparedRecordError, match="mismatches"):
        verify_prepared_record_against_wheelhouse(
            data,
            tmp_path,
            registry_envelope=registry,
            lock_envelope=updated,
            trust=_ring(),
            now=NOW,
        )


def test_no_live_install_or_workspace_side_effects(tmp_path: Path) -> None:
    registry, lock, _ = _prepared(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    prepare_composition_record(
        tmp_path,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=NOW,
        transaction_id=_TX,
    )
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
