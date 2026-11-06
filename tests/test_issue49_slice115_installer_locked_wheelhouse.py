"""Slice 115: signed dependency closure is compared with exact installer claims."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite import evergreen_windows_installer_locked_wheelhouse as target
from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_dependency_lock import DependencyLockError
from paper_data_suite.evergreen_windows_installer_intent import _PHASES
from paper_data_suite.evergreen_windows_installer_signed_wheel_bridge import (
    InstallerSignedWheelBridgeError,
    SignedWheelBridgeReview,
    SignedWheelCandidate,
)

_NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
_NAMES = ("paper-data-suite", "pds-core", "quillan", "scoreform")
_DIGESTS = tuple(char * 64 for char in "def0")
_FILES = (
    "paper_data_suite-1.2.3-py3-none-any.whl",
    "pds_core-1.2.3-py3-none-any.whl",
    "quillan-1.2.3-py3-none-any.whl",
    "scoreform-1.2.3-py3-none-any.whl",
)


def _trust() -> TrustedKeyring:
    key = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return TrustedKeyring((TrustedPublicKey("root-test", raw),), ("root-test",))


def _raw() -> bytes:
    payload = {
        "schema": 1,
        "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
        "service_name": "PaperDataSuiteService",
        "transaction_id": "a" * 32,
        "catalog_sha256": "b" * 64,
        "recovery_basis_sha256": "c" * 64,
        "artifacts": [
            {"distribution": name, "version": "1.2.3", "sha256": digest}
            for name, digest in zip(_NAMES, _DIGESTS, strict=True)
        ],
        "requested_phases": list(_PHASES),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _wheels(root: Path) -> tuple[SignedWheelCandidate, ...]:
    return tuple(
        SignedWheelCandidate(name, root / filename, b"publisher")
        for name, filename in zip(_NAMES, _FILES, strict=True)
    )


def _closed():
    wheels = [
        SimpleNamespace(
            distribution=name,
            version="1.2.3",
            sha256=digest,
            filename=filename,
        )
        for name, digest, filename in zip(_NAMES, _DIGESTS, _FILES, strict=True)
    ]
    wheels.append(
        SimpleNamespace(
            distribution="packaging",
            version="25.0",
            sha256="9" * 64,
            filename="packaging-25.0-py3-none-any.whl",
        )
    )
    return SimpleNamespace(
        lock=SimpleNamespace(
            registry_payload_sha256="b" * 64,
            roots=_NAMES,
            payload_sha256="a" * 64,
            revision=3,
            python_minor="3.13",
            platform="win-arm64",
        ),
        inspection=SimpleNamespace(
            wheels=tuple(wheels),
            dependency_edges=(("paper-data-suite", "pds-core"),),
        ),
    )


def _matched(raw: bytes) -> SignedWheelBridgeReview:
    return SignedWheelBridgeReview(
        status="SIGNED_WHEEL_BYTES_MATCH_UNTRUSTED_INTENT_ONLY",
        request_sha256=hashlib.sha256(raw).hexdigest(),
        registry_payload_sha256="b" * 64,
        matched_distributions=_NAMES,
        matched_wheel_sha256=_DIGESTS,
    )


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    raw = _raw()
    wheelhouse = tmp_path / "closed"
    wheelhouse.mkdir()
    monkeypatch.setattr(
        target, "verify_signed_locked_wheelhouse", lambda *a, **kw: _closed()
    )
    monkeypatch.setattr(
        target, "review_installer_signed_wheels", lambda *a, **kw: _matched(raw)
    )
    return {
        "raw_intent": raw,
        "candidates": _wheels(wheelhouse),
        "wheelhouse": wheelhouse,
        "registry_envelope": b"registry",
        "lock_envelope": b"lock",
        "trust": _trust(),
        "now": _NOW,
    }


def test_signed_closure_still_has_no_install_authority(ctx: dict[str, object]) -> None:
    review = target.review_installer_locked_wheelhouse(**ctx)
    assert (
        review.status
        == "SIGNED_CLOSED_WHEELHOUSE_MATCHES_UNTRUSTED_INSTALLER_INTENT_ONLY"
    )
    assert review.pds_distributions == _NAMES
    assert review.external_dependency_distributions == ("packaging",)
    assert review.dependency_edge_count == 1
    assert review.signed_lock_revision == 3
    for field in (
        "independently_pinned_root",
        "independently_continuous_checkpoints",
        "authenticated_administrator",
        "authorized_to_provision",
        "authorized_to_register_service",
        "authorized_to_publish_receipt",
        "authorized_to_activate_or_launch",
    ):
        assert getattr(review, field) is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("registry_payload_sha256", "f" * 64),
        ("roots", ("paper-data-suite", "pds-core")),
        ("roots", _NAMES + ("packaging",)),
        ("roots", _NAMES + (_NAMES[0],)),
    ],
)
def test_lock_registry_roots_mismatch_refuses(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    closed = _closed()
    setattr(closed.lock, field, value)
    monkeypatch.setattr(
        target, "verify_signed_locked_wheelhouse", lambda *a, **kw: closed
    )
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**ctx)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "8.8.8"),
        ("sha256", "e" * 64),
        ("filename", "other.whl"),
    ],
)
def test_single_locked_wheel_mismatch_refuses(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    closed = _closed()
    setattr(closed.inspection.wheels[2], field, value)
    monkeypatch.setattr(
        target, "verify_signed_locked_wheelhouse", lambda *a, **kw: closed
    )
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**ctx)


@pytest.mark.parametrize("extra", ["pds-evil", "quillan"])
def test_unrequested_pds_or_duplicate_refused(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch, extra: str
) -> None:
    closed = _closed()
    wheels = list(closed.inspection.wheels)
    wheels.append(
        SimpleNamespace(
            distribution=extra, version="1.0.0", sha256="1" * 64, filename="other.whl"
        )
    )
    closed.inspection.wheels = tuple(wheels)
    monkeypatch.setattr(
        target, "verify_signed_locked_wheelhouse", lambda *a, **kw: closed
    )
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**ctx)


def test_candidate_from_other_wheelhouse_refuses(ctx: dict[str, object]) -> None:
    vals = ctx.copy()
    items = list(vals["candidates"])
    items[0] = replace(items[0], wheel_path=Path("foreign") / _FILES[0])
    vals["candidates"] = tuple(items)
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**vals)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_sha256", "f" * 64),
        ("registry_payload_sha256", "e" * 64),
        ("status", "ADMIN_APPROVED"),
        ("matched_distributions", ("paper-data-suite",)),
        ("matched_wheel_sha256", ("f" * 64,)),
        ("authorized_to_provision", True),
        ("authorized_to_activate_or_launch", True),
    ],
)
def test_signed_wheel_review_inconsistency_refuses(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    review = replace(_matched(_raw()), **{field: value})
    monkeypatch.setattr(
        target, "review_installer_signed_wheels", lambda *a, **kw: review
    )
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**ctx)


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidates", ()),
        ("lock_envelope", b""),
        ("lock_envelope", b"x" * (48 * 1024 + 1)),
        ("registry_envelope", b""),
        ("wheelhouse", "not-a-path"),
        ("trust", None),
        ("now", datetime(2026, 11, 1)),
    ],
    ids=(
        "no-candidates",
        "empty-lock",
        "oversized-lock",
        "empty-registry",
        "invalid-wheelhouse",
        "missing-trust",
        "naive-time",
    ),
)
def test_bad_boundary_inputs_refuse(
    ctx: dict[str, object], field: str, value: object
) -> None:
    vals = {**ctx, field: value}
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**vals)


@pytest.mark.parametrize("kind", ["lock", "wheels"])
def test_underlying_signature_or_closure_failure_refuses(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    def bad(*args: object, **kwargs: object) -> object:
        if kind == "lock":
            raise DependencyLockError("invalid signed lock")
        raise InstallerSignedWheelBridgeError("invalid wheel bytes")

    name = (
        "verify_signed_locked_wheelhouse"
        if kind == "lock"
        else "review_installer_signed_wheels"
    )
    monkeypatch.setattr(target, name, bad)
    with pytest.raises(target.InstallerLockedWheelhouseError):
        target.review_installer_locked_wheelhouse(**ctx)


def test_cli_remains_non_authorizing(capsys: pytest.CaptureFixture[str]) -> None:
    assert target.main([]) == 2
    output = capsys.readouterr().out
    payload = json.loads(output.split("\n" + target._NO_AUTHORITY)[0])
    assert payload["root_trust_independently_pinned"] is False
    assert payload["persistent_rollback_checkpoints_established"] is False
    assert payload["production_authority"] is False
    assert payload["active_receipt_authority"] is False


def test_cli_has_no_apply_mode() -> None:
    with pytest.raises(SystemExit) as raised:
        target.main(["--apply"])
    assert raised.value.code == 2
