"""Issue #49 Slice 103: root-attested disposable native bytes, fail closed."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from paper_data_suite import evergreen_signed_native_lab as native

NOW = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
PIN = "a" * 64
REGISTRY = b"registry-basis"
MODULE = b"module-basis"
PASSWORD = b"a sufficiently long passphrase"


def _lab(tmp_path: Path) -> Path:
    root = tmp_path / "historical_suite_010_quillan_0106_FULL_DEPS_LAB"
    scripts = root / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"MZ trusted python executable")
    (scripts / "quillan.exe").write_bytes(b"MZ trusted quillan launcher")
    return root


def _fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, bytes, bytes]:
    root = _lab(tmp_path)
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(PASSWORD),
    )
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    ring = SimpleNamespace(
        root_key_ids=("publisher-root",),
        root_threshold=1,
        key=lambda name: (
            SimpleNamespace(public_bytes=public) if name == "publisher-root" else None
        ),
    )
    monkeypatch.setattr(
        native, "_checked_basis", lambda **kwargs: (b"policy", REGISTRY, MODULE)
    )
    monkeypatch.setattr(
        native,
        "load_digest_pinned_trust_policy",
        lambda data, pinned_sha256: SimpleNamespace(keyring=ring),
    )

    def public_from_private(
        name: str, private_pem: bytes, password: bytes
    ) -> SimpleNamespace:
        loaded = serialization.load_pem_private_key(private_pem, password=password)
        assert isinstance(loaded, Ed25519PrivateKey)
        raw = loaded.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return SimpleNamespace(public_key_b64=base64.b64encode(raw).decode("ascii"))

    monkeypatch.setattr(native, "public_key_from_encrypted", public_from_private)
    return root, pem, public


def _prepare(root: Path) -> bytes:
    return native.prepare_native_lab_review(
        root,
        wheel=Path("wheel"),
        policy=Path("policy"),
        independent_policy_sha256=PIN,
        registry=Path("registry"),
        module=Path("module"),
        now=NOW,
    )


def _issue(root: Path, reviewed: bytes, pem: bytes) -> bytes:
    return native.issue_native_lab_envelope(
        root,
        reviewed=reviewed,
        root_private=pem,
        root_password=PASSWORD,
        wheel=Path("wheel"),
        policy=Path("policy"),
        independent_policy_sha256=PIN,
        registry=Path("registry"),
        module=Path("module"),
        now=NOW,
    )


def _inspect(
    root: Path, envelope: bytes, *, now: datetime = NOW
) -> native.NativeLabObservation:
    return native.inspect_native_lab_envelope(
        root,
        envelope=envelope,
        wheel=Path("wheel"),
        policy=Path("policy"),
        independent_policy_sha256=PIN,
        registry=Path("registry"),
        module=Path("module"),
        now=now,
    )


def test_genuine_root_signature_and_two_exact_executables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    envelope = _issue(root, _prepare(root), pem)
    observed = _inspect(root, envelope)
    assert observed.native_binary_digest_attested
    assert not observed.production_launch_authority
    assert observed.status.endswith("LAB_ONLY")
    assert len(observed.python_sha256) == 64
    assert len(observed.launcher_sha256) == 64


@pytest.mark.parametrize("filename", ["python.exe", "quillan.exe"])
def test_changed_executable_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    envelope = _issue(root, _prepare(root), pem)
    (root / "Scripts" / filename).write_bytes(b"MZ malicious substitute")
    with pytest.raises(native.NativeLabEvidenceError, match="changed"):
        _inspect(root, envelope)


def test_review_changes_prevent_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    document = json.loads(_prepare(root))
    document["wheel_sha256"] = "b" * 64
    with pytest.raises(native.NativeLabEvidenceError):
        _issue(root, native._encode(document), pem)


def test_signature_mutation_prevents_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    envelope = json.loads(_issue(root, _prepare(root), pem))
    envelope["signature"]["signature_b64"] = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(native.NativeLabEvidenceError, match="signature invalid"):
        _inspect(root, native._encode(envelope))


def test_expired_native_authorization_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    envelope = _issue(root, _prepare(root), pem)
    with pytest.raises(native.NativeLabEvidenceError, match="expired"):
        _inspect(root, envelope, now=NOW + timedelta(days=8))


def test_wrong_policy_hash_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    envelope = _issue(root, _prepare(root), pem)
    with pytest.raises(native.NativeLabEvidenceError, match="binding changed"):
        native.inspect_native_lab_envelope(
            root,
            envelope=envelope,
            wheel=Path("wheel"),
            policy=Path("policy"),
            independent_policy_sha256="b" * 64,
            registry=Path("registry"),
            module=Path("module"),
            now=NOW,
        )


def test_wrong_root_signing_key_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _fixture(monkeypatch, tmp_path)
    other = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(PASSWORD),
    )
    with pytest.raises(
        native.NativeLabEvidenceError, match="does not match pinned root"
    ):
        native.issue_native_lab_envelope(
            root,
            reviewed=_prepare(root),
            root_private=other,
            root_password=PASSWORD,
            wheel=Path("wheel"),
            policy=Path("policy"),
            independent_policy_sha256=PIN,
            registry=Path("registry"),
            module=Path("module"),
            now=NOW,
        )


def test_signer_identity_cannot_be_reassigned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pem, _ = _fixture(monkeypatch, tmp_path)
    envelope = json.loads(_issue(root, _prepare(root), pem))
    envelope["signature"]["key_id"] = "quillan-publisher"
    with pytest.raises(native.NativeLabEvidenceError, match="unauthorized"):
        _inspect(root, native._encode(envelope))


def test_duplicate_json_members_refused() -> None:
    with pytest.raises(native.NativeLabEvidenceError, match="duplicate"):
        native._json(b'{"signature":1,"signature":2}')


def test_non_lab_path_rejected(tmp_path: Path) -> None:
    wrong = tmp_path / "production"
    wrong.mkdir()
    with pytest.raises(native.NativeLabEvidenceError, match="disposable"):
        native._lab_files(wrong)


def test_new_file_does_not_overwrite(tmp_path: Path) -> None:
    file = tmp_path / "native-envelope.json"
    native._new_file(file, b"signed")
    with pytest.raises(native.NativeLabEvidenceError, match="overwrite"):
        native._new_file(file, b"replaced")
    assert file.read_bytes() == b"signed"


def test_signing_context_is_not_catalog_signature_context() -> None:
    assert native._CONTEXT != b"pds-evergreen-staged-native-evidence-v1\x00"
    assert native._CONTEXT.endswith(b"\x00")
