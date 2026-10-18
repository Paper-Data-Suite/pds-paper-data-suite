"""Issue #49 Slice 10: synthetic signed executable provenance, never activation."""

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
    _encode,
    _private,
    _ring,
)
from test_issue49_slice9_virtualenv_runtime import _scene

from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)

_CONTEXT = b"pds-evergreen-staged-native-evidence-v1\x00"


def _evidence(
    scene: tuple[Path, Path, bytes, bytes, bytes, str],
    *,
    revision: int = 1,
    alter: dict[str, Any] | None = None,
    signers: tuple[str, ...] = ("root-primary",),
    raw_payload: bytes | None = None,
) -> bytes:
    root, _, _, _, record, layout = scene
    prepared = json.loads(record)
    folder = "Scripts" if layout == "windows" else "bin"
    interpreter = f"{folder}/python.exe" if folder == "Scripts" else f"{folder}/python"
    executables = [interpreter]
    console = f"{folder}/demo.exe" if folder == "Scripts" else f"{folder}/demo"
    executables.append(console)
    doc: dict[str, Any] = {
        "record_type": "pds_evergreen_staged_native_evidence",
        "schema_version": 1,
        "revision": revision,
        "issued_at": "2026-10-17T16:00:00Z",
        "expires_at": "2026-11-17T16:00:00Z",
        "transaction_id": prepared["transaction_id"],
        "registry_payload_sha256": prepared["registry_payload_sha256"],
        "lock_payload_sha256": prepared["lock_payload_sha256"],
        "trust_fingerprint": prepared["trust_fingerprint"],
        "python_minor": prepared["python_minor"],
        "platform": prepared["platform"],
        "files": [
            {
                "relative_path": filename,
                "sha256": hashlib.sha256((root / filename).read_bytes()).hexdigest(),
                "size": (root / filename).stat().st_size,
            }
            for filename in executables
        ],
    }
    if alter:
        doc.update(alter)
    payload = raw_payload if raw_payload is not None else _encode(doc)
    return _encode(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signatures": [
                {
                    "key_id": signer,
                    "algorithm": "ed25519",
                    "signature_b64": base64.b64encode(
                        _private(signer).sign(_CONTEXT + payload)
                    ).decode("ascii"),
                }
                for signer in signers
            ],
        }
    )


def _verify(
    scene: tuple[Path, Path, bytes, bytes, bytes, str],
    envelope: bytes,
    **kwargs: Any,
):
    root, wheels, registry, lock, record, layout = scene
    return verify_signed_staged_native_evidence(
        root,
        wheels,
        evidence_envelope=envelope,
        prepared_record=record,
        registry_envelope=registry,
        lock_envelope=lock,
        trust=_ring(),
        now=kwargs.pop("now", NOW),
        layout=layout,
        **kwargs,
    )


@pytest.mark.parametrize("layout", ["windows", "posix"])
def test_signed_exact_native_inventory_is_observation_only(
    tmp_path: Path, layout: str
) -> None:
    scene = _scene(tmp_path, layout=layout)
    envelope = _evidence(scene)
    output = _verify(scene, envelope)
    assert output.signers == ("root-primary",)
    assert output.transaction_id == "f" * 32
    assert len(output.binaries) == 2
    assert output.checkpoint.payload_sha256 == output.payload_sha256
    assert not hasattr(output, "can_launch")
    assert not hasattr(output, "activated")


def test_changed_executable_bytes_cannot_match_signed_digest(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    envelope = _evidence(scene)
    target = scene[0] / "Scripts/python.exe"
    target.write_bytes(target.read_bytes() + b"malicious code")
    with pytest.raises(NativeEvidenceError, match="size mismatch"):
        _verify(scene, envelope)


def test_changed_executable_same_size_cannot_match_signed_digest(
    tmp_path: Path,
) -> None:
    scene = _scene(tmp_path)
    envelope = _evidence(scene)
    target = scene[0] / "Scripts/python.exe"
    target.write_bytes(b"X" * target.stat().st_size)
    with pytest.raises(NativeEvidenceError, match="digest mismatch"):
        _verify(scene, envelope)


def test_altered_launcher_rejected_before_binary_pin(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    envelope = _evidence(scene)
    script = scene[0] / "Scripts/demo.exe"
    script.write_bytes(script.read_bytes() + b"drift")
    with pytest.raises(NativeEvidenceError, match="(staged virtualenv|digest|size)"):
        _verify(scene, envelope)


@pytest.mark.parametrize(
    "field",
    [
        "transaction_id",
        "registry_payload_sha256",
        "lock_payload_sha256",
        "trust_fingerprint",
    ],
)
def test_signed_evidence_is_bound_to_exact_prepared_identity(
    tmp_path: Path, field: str
) -> None:
    scene = _scene(tmp_path)
    bad = "1" * 32 if field == "transaction_id" else "1" * 64
    with pytest.raises(NativeEvidenceError, match="binding mismatch"):
        _verify(scene, _evidence(scene, alter={field: bad}))


def test_publisher_key_cannot_sign_native_root_attestation(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(NativeEvidenceError, match="unauthorized"):
        _verify(scene, _evidence(scene, signers=("quillan-primary",)))


def test_unsigned_or_duplicate_root_signers_not_authority(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(NativeEvidenceError, match="signature count"):
        _verify(scene, _evidence(scene, signers=()))
    with pytest.raises(NativeEvidenceError, match="duplicate"):
        _verify(scene, _evidence(scene, signers=("root-primary", "root-primary")))


def test_replay_checkpoint_and_signed_equivocation(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    before = _verify(scene, _evidence(scene))
    newer = _evidence(scene, revision=2)
    current = _verify(scene, newer, checkpoint=before.checkpoint)
    assert current.revision == 2
    with pytest.raises(NativeEvidenceError, match="rollback"):
        _verify(scene, _evidence(scene), checkpoint=current.checkpoint)
    with pytest.raises(NativeEvidenceError, match="equivocation"):
        _verify(
            scene,
            _evidence(scene, revision=2, alter={"expires_at": "2026-11-19T16:00:00Z"}),
            checkpoint=current.checkpoint,
        )


def test_stale_native_evidence_refused(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(NativeEvidenceError, match="expired"):
        _verify(
            scene,
            _evidence(scene, alter={"expires_at": "2026-10-18T16:00:00Z"}),
            now=NOW + timedelta(days=3),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": True},
        {"schema_version": 2},
        {"platform": "other"},
        {"python_minor": "3.99"},
        {"files": []},
    ],
)
def test_unsupported_native_claims_rejected(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    scene = _scene(tmp_path)
    with pytest.raises(NativeEvidenceError):
        _verify(scene, _evidence(scene, alter=change))


def test_missing_and_extra_executable_pins_fail_closed(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    existing = json.loads(base64.b64decode(json.loads(_evidence(scene))["payload_b64"]))
    only_python = dict(existing)
    only_python["files"] = only_python["files"][:1]
    with pytest.raises(NativeEvidenceError, match="inventory"):
        _verify(scene, _evidence(scene, raw_payload=_encode(only_python)))
    duplicate = dict(existing)
    duplicate["files"] = existing["files"] + existing["files"][:1]
    with pytest.raises(NativeEvidenceError, match="duplicate"):
        _verify(scene, _evidence(scene, raw_payload=_encode(duplicate)))
    traversal = dict(existing)
    traversal["files"] = [{**existing["files"][0], "relative_path": "../evil.exe"}]
    with pytest.raises(NativeEvidenceError, match="binary path"):
        _verify(scene, _evidence(scene, raw_payload=_encode(traversal)))


def test_signed_hash_cannot_be_patched_without_resigning(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    doc = json.loads(base64.b64decode(json.loads(_evidence(scene))["payload_b64"]))
    doc["files"][0]["sha256"] = "0" * 64
    old_envelope = json.loads(_evidence(scene))
    old_envelope["payload_b64"] = base64.b64encode(_encode(doc)).decode("ascii")
    with pytest.raises(NativeEvidenceError, match="signature"):
        _verify(scene, _encode(old_envelope))


def test_wrong_staged_transaction_cannot_inherit_authorization(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    doc = json.loads(base64.b64decode(json.loads(_evidence(scene))["payload_b64"]))
    doc["transaction_id"] = "b" * 32
    with pytest.raises(NativeEvidenceError, match="binding mismatch"):
        _verify(scene, _evidence(scene, raw_payload=_encode(doc)))


def test_no_changes_to_stage_after_valid_read_only_audit(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    envelope = _evidence(scene)
    before = {
        p.relative_to(scene[0]): p.read_bytes()
        for p in scene[0].rglob("*")
        if p.is_file()
    }
    _verify(scene, envelope)
    after = {
        p.relative_to(scene[0]): p.read_bytes()
        for p in scene[0].rglob("*")
        if p.is_file()
    }
    assert before == after


def test_reject_duplicate_json_members_even_if_signed(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    payload = _evidence(scene)
    doc = json.loads(payload)
    raw = _encode(doc).replace(
        b'"envelope_version":1',
        b'"envelope_version":1,"envelope_version":1',
    )
    with pytest.raises(NativeEvidenceError, match="duplicate"):
        _verify(scene, raw)
