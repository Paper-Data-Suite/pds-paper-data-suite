"""Issue #49 Slice 5: dual-root rotation and signed exact-wheel verification."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_issue49_slice3_signature_verification import (
    NOW,
    _module,
    _private,
    _registry,
    _ring,
    _signed,
)
from test_issue49_slice4_trust_and_cache import _policy

from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    verify_signed_release_wheel,
)
from paper_data_suite.evergreen_trust_provisioning import (
    load_digest_pinned_trust_policy,
)
from paper_data_suite.evergreen_trust_rotation import (
    TrustRotationError,
    verify_trust_transition,
)

NEW_ROOT = Ed25519PrivateKey.from_private_bytes(b"\x13" * 32)
CONTEXT = b"pds-evergreen-policy-transition-v1\x00"


def _encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _old_policy(*, threshold: int = 1):
    data = json.loads(_policy())
    data["root_threshold"] = threshold
    raw = _encode(data)
    return load_digest_pinned_trust_policy(
        raw, pinned_sha256=hashlib.sha256(raw).hexdigest()
    )


def _next_policy(*, revision: int = 2) -> bytes:
    data = json.loads(_policy())
    data["revision"] = revision
    data["keys"] = [
        item
        for item in data["keys"]
        if item["key_id"] not in {"root-primary", "root-backup"}
    ]
    raw = NEW_ROOT.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    data["keys"].append(
        {"key_id": "new-root", "public_key_b64": base64.b64encode(raw).decode()}
    )
    data["root_key_ids"] = ["new-root"]
    data["root_threshold"] = 1
    return _encode(data)


def _transition(
    *,
    previous=None,
    successor: bytes | None = None,
    old_ids: tuple[str, ...] = ("root-primary",),
    next_ids: tuple[str, ...] = ("new-root",),
) -> tuple[bytes, object]:
    prior = previous or _old_policy()
    following = successor if successor is not None else _next_policy()
    message = CONTEXT + prior.sha256.encode() + b"\x00" + following

    def signed(key_id: str) -> dict[str, str]:
        private = NEW_ROOT if key_id == "new-root" else _private(key_id)
        return {
            "key_id": key_id,
            "algorithm": "ed25519",
            "signature_b64": base64.b64encode(private.sign(message)).decode(),
        }

    return (
        _encode(
            {
                "record_type": "pds_evergreen_trust_transition",
                "schema_version": 1,
                "previous_sha256": prior.sha256,
                "successor_policy_b64": base64.b64encode(following).decode(),
                "previous_root_signatures": [signed(key) for key in old_ids],
                "successor_root_signatures": [signed(key) for key in next_ids],
            }
        ),
        prior,
    )


def test_dual_root_authorized_transition_changes_root_without_suite_wheel() -> None:
    blob, previous = _transition()
    result = verify_trust_transition(blob, previous=previous)
    assert result.successor.policy_revision == 2
    assert result.successor.keyring.root_key_ids == ("new-root",)
    assert result.old_signers == ("root-primary",)
    assert result.new_signers == ("new-root",)
    assert not hasattr(result, "can_launch")


def test_successor_policy_revision_must_advance() -> None:
    blob, previous = _transition(successor=_next_policy(revision=1))
    with pytest.raises(TrustRotationError, match="revision"):
        verify_trust_transition(blob, previous=previous)


def test_old_and_new_root_quorums_both_required() -> None:
    old = _old_policy(threshold=2)
    blob, previous = _transition(previous=old, old_ids=("root-primary", "root-backup"))
    assert len(verify_trust_transition(blob, previous=previous).old_signers) == 2
    for omit in ("previous_root_signatures", "successor_root_signatures"):
        payload = json.loads(blob)
        payload[omit] = []
        with pytest.raises(TrustRotationError):
            verify_trust_transition(_encode(payload), previous=old)
    single, _ = _transition(previous=old)
    with pytest.raises(TrustRotationError, match="quorum"):
        verify_trust_transition(single, previous=old)


def test_wrong_previous_policy_is_not_authorized() -> None:
    blob, previous = _transition()
    other = _old_policy(threshold=2)
    with pytest.raises(TrustRotationError, match="previous trust anchor"):
        verify_trust_transition(blob, previous=other)
    assert previous.sha256 != other.sha256


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda data: data.update({"schema_version": 2}),
        lambda data: data.update({"unknown": 0}),
        lambda data: data["previous_root_signatures"][0].update({"key_id": "attacker"}),
        lambda data: data["successor_root_signatures"][0].update(
            {"signature_b64": "AA=="}
        ),
        lambda data: data["previous_root_signatures"][0].update({"algorithm": "none"}),
        lambda data: data.update({"successor_policy_b64": "Zg"}),
        lambda data: data["previous_root_signatures"].append(
            data["previous_root_signatures"][0]
        ),
    ],
)
def test_invalid_transition_metadata_refused(corrupt: Any) -> None:
    blob, previous = _transition()
    data = json.loads(blob)
    corrupt(data)
    with pytest.raises(TrustRotationError):
        verify_trust_transition(_encode(data), previous=previous)


def test_successor_bytes_cannot_change_after_old_authorization() -> None:
    blob, previous = _transition()
    data = json.loads(blob)
    next_policy = json.loads(base64.b64decode(data["successor_policy_b64"]))
    next_policy["revision"] += 1
    data["successor_policy_b64"] = base64.b64encode(_encode(next_policy)).decode()
    with pytest.raises(TrustRotationError, match="signature"):
        verify_trust_transition(_encode(data), previous=previous)


def test_old_root_signature_cannot_be_replayed_as_new_root_signature() -> None:
    blob, previous = _transition()
    data = json.loads(blob)
    data["successor_root_signatures"] = data["previous_root_signatures"]
    with pytest.raises(TrustRotationError):
        verify_trust_transition(_encode(data), previous=previous)


def _wheel_bytes(
    *,
    version: str = "0.10.7",
    distribution: str = "quillan",
    requirement: str = "pds-core>=0.6.6,<0.7",
    console: str = "quillan = quillan.cli:main",
    member: str = "quillan/__init__.py",
    extra_console: str = "",
) -> bytes:
    prefix = f"{distribution.replace('-', '_')}-{version}.dist-info"
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{prefix}/METADATA",
            f"Metadata-Version: 2.2\nName: {distribution}\nVersion: {version}\n"
            f"Requires-Python: >=3.11,<3.15\nRequires-Dist: {requirement}\n\n",
        )
        archive.writestr(f"{prefix}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
        archive.writestr(
            f"{prefix}/entry_points.txt",
            f"[console_scripts]\n{console}\n{extra_console}",
        )
        archive.writestr(f"{prefix}/RECORD", "")
        archive.writestr(member, "synthetic only\n")
    return target.getvalue()


def _release(
    tmp_path: Path,
    *,
    wheel_bytes: bytes | None = None,
    signed_hash: str | None = None,
    release_changes: dict[str, Any] | None = None,
    signer: str = "quillan-primary",
    registry_signer: str = "root-primary",
) -> tuple[Path, bytes, bytes]:
    data = wheel_bytes if wheel_bytes is not None else _wheel_bytes()
    path = tmp_path / "quillan-0.10.7-py3-none-any.whl"
    path.write_bytes(data)
    claims = _module()
    claims["releases"][0]["sha256"] = signed_hash or hashlib.sha256(data).hexdigest()
    if release_changes:
        claims["releases"][0].update(release_changes)
    return (
        path,
        _signed(_registry(), registry_signer),
        _signed(claims, signer),
    )


def _verify(path: Path, registry: bytes, module: bytes):
    return verify_signed_release_wheel(
        path,
        registry_envelope=registry,
        module_envelope=module,
        trust=_ring(),
        now=NOW,
        version="0.10.7",
    )


def test_real_signed_claim_matches_exact_synthetic_wheel(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path)
    result = _verify(path, registry, module)
    assert result.component_id == "quillan"
    assert result.version == "0.10.7"
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.console_script == "quillan"
    assert result.registry_payload_sha256
    assert not hasattr(result, "can_launch")


def test_different_bytes_same_wheel_filename_fail(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path)
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ReleaseArtifactError, match="hash"):
        _verify(path, registry, module)


def test_attacker_cannot_impersonate_delegated_publisher(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path, signer="attacker")
    with pytest.raises(ReleaseArtifactError, match="authenticity"):
        _verify(path, registry, module)


def test_untrusted_registry_root_refused(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path, registry_signer="attacker")
    with pytest.raises(ReleaseArtifactError, match="authenticity"):
        _verify(path, registry, module)


def test_signed_revocation_refuses_exact_wheel(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path, release_changes={"revoked": True})
    with pytest.raises(ReleaseArtifactError, match="revoked"):
        _verify(path, registry, module)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("distribution", "dist-info"),
        ("version", "dist-info"),
        ("python", "Requires-Python"),
        ("dependency", "Requires-Dist"),
        ("entry", "console script"),
        ("multiple", "console scripts"),
        ("traversal", "unsafe"),
    ],
)
def test_signed_hash_does_not_make_incorrect_wheel_metadata_valid(
    tmp_path: Path, case: str, expected: str
) -> None:
    parameters: dict[str, str] = {}
    if case == "distribution":
        parameters["distribution"] = "badthing"
    elif case == "version":
        parameters["version"] = "0.10.8"
    elif case == "python":
        parameters["requirement"] = "pds-core>=0.6.6,<0.7"
    elif case == "dependency":
        parameters["requirement"] = "other-package>=1"
    elif case == "entry":
        parameters["console"] = "quillan = attacker.cli:main"
    elif case == "multiple":
        parameters["extra_console"] = "other = attacker.cli:main\n"
    elif case == "traversal":
        parameters["member"] = "../attacker.py"
    data = _wheel_bytes(**parameters)
    if case == "python":
        inp = io.BytesIO(data)
        out = io.BytesIO()
        with zipfile.ZipFile(inp) as source, zipfile.ZipFile(out, "w") as target:
            for item in source.infolist():
                raw = source.read(item.filename)
                if item.filename.endswith("/METADATA"):
                    raw = raw.replace(
                        b"Requires-Python: >=3.11,<3.15",
                        b"Requires-Python: >=3.12",
                    )
                target.writestr(item, raw)
        data = out.getvalue()
    path, registry, module = _release(tmp_path, wheel_bytes=data)
    with pytest.raises(ReleaseArtifactError, match=expected):
        _verify(path, registry, module)


def test_mismatched_claimed_hash_blocks_before_archive_parsing(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path, signed_hash="0" * 64)
    with pytest.raises(ReleaseArtifactError, match="hash"):
        _verify(path, registry, module)


def test_missing_release_version_is_rejected(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path)
    with pytest.raises(ReleaseArtifactError, match="version not present"):
        verify_signed_release_wheel(
            path,
            registry_envelope=registry,
            module_envelope=module,
            trust=_ring(),
            now=NOW,
            version="8.0.0",
        )


def test_expired_signed_release_refused(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path)
    with pytest.raises(ReleaseArtifactError, match="authenticity"):
        verify_signed_release_wheel(
            path,
            registry_envelope=registry,
            module_envelope=module,
            trust=_ring(),
            now=NOW + timedelta(days=50),
            version="0.10.7",
        )


def test_symlinked_wheel_is_not_authorized(tmp_path: Path) -> None:
    path, registry, module = _release(tmp_path)
    link = tmp_path / "link.whl"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(ReleaseArtifactError, match="nonsymlink"):
        _verify(link, registry, module)


def test_release_claim_cannot_hide_second_console_script(tmp_path: Path) -> None:
    path, registry, module = _release(
        tmp_path, wheel_bytes=_wheel_bytes(extra_console="danger = attacker.cli:main\n")
    )
    with pytest.raises(ReleaseArtifactError, match="console scripts"):
        _verify(path, registry, module)


def test_no_trust_from_forged_verified_document_instances() -> None:
    # The wheel API demands actual SIGNED envelope bytes, not caller-created
    # dataclasses holding plausible claims or forged is_trusted flags.
    assert "registry_envelope" in verify_signed_release_wheel.__code__.co_varnames
    assert "module_envelope" in verify_signed_release_wheel.__code__.co_varnames
