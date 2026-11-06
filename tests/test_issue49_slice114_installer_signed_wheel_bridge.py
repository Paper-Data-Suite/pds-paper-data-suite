"""Slice 114: wheel bytes must match intent under fresh signature checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite import evergreen_windows_installer_signed_wheel_bridge as target
from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    VerifiedReleaseWheel,
)
from paper_data_suite.evergreen_windows_installer_intent import _PHASES

_NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
_DISTS = ("paper-data-suite", "pds-core", "quillan", "scoreform")


def _trust() -> TrustedKeyring:
    public = (
        Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    return TrustedKeyring((TrustedPublicKey("root-test", public),), ("root-test",))


def _raw() -> bytes:
    obj = {
        "schema": 1,
        "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
        "service_name": "PaperDataSuiteService",
        "transaction_id": "a" * 32,
        "catalog_sha256": "b" * 64,
        "recovery_basis_sha256": "c" * 64,
        "artifacts": [
            {"distribution": dist, "version": "1.2.3", "sha256": ch * 64}
            for dist, ch in zip(_DISTS, "def0", strict=True)
        ],
        "requested_phases": list(_PHASES),
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _sources() -> tuple[target.SignedWheelCandidate, ...]:
    return tuple(
        target.SignedWheelCandidate(name, Path(f"{name}-wheel.whl"), b"signed")
        for name in _DISTS
    )


def _review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate: object = None,
    candidates: tuple[target.SignedWheelCandidate, ...] | None = None,
) -> target.SignedWheelBridgeReview:
    calls: list[str] = []

    def verifier(path: Path, **kwargs: object) -> VerifiedReleaseWheel:
        assert kwargs["registry_envelope"] == b"catalog"
        assert kwargs["module_envelope"] == b"signed"
        assert kwargs["now"] == _NOW
        assert kwargs["version"] == "1.2.3"
        assert isinstance(kwargs["trust"], TrustedKeyring)
        name = path.name.removesuffix("-wheel.whl")
        calls.append(name)
        wheel = VerifiedReleaseWheel(
            name,
            name,
            "1.2.3",
            path.name,
            ("def0"[_DISTS.index(name)]) * 64,
            "f" * 64,
            "b" * 64,
            (),
            "console",
            "package:main",
        )
        return mutate(wheel) if callable(mutate) else wheel

    monkeypatch.setattr(target, "verify_signed_release_wheel", verifier)
    result = target.review_installer_signed_wheels(
        _raw(),
        candidates=candidates if candidates is not None else _sources(),
        registry_envelope=b"catalog",
        trust=_trust(),
        now=_NOW,
    )
    assert calls == list(_DISTS)
    return result


def test_all_four_real_distribution_claims_require_fresh_wheel_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review(monkeypatch)
    assert review.status == "SIGNED_WHEEL_BYTES_MATCH_UNTRUSTED_INTENT_ONLY"
    assert review.matched_distributions == _DISTS
    assert review.request_sha256 == hashlib.sha256(_raw()).hexdigest()
    assert review.registry_payload_sha256 == "b" * 64
    assert review.signer_context == "CALLER_KEYRING_NOT_INDEPENDENTLY_PINNED"
    assert review.monotonic_checkpoints == "NOT_INDEPENDENTLY_VERIFIED"
    assert review.administrator_identity == "NOT_AUTHENTICATED"
    assert review.recovery_basis == "UNVERIFIED_REQUEST_CLAIM"
    assert review.authorized_to_provision is False
    assert review.authorized_to_register_service is False
    assert review.authorized_to_publish_receipt is False
    assert review.authorized_to_activate_or_launch is False
    assert review.authority == target._NO_AUTHORITY


@pytest.mark.parametrize(
    "field,value",
    [
        ("distribution", "pds-quillan"),
        ("distribution", "scoreform"),
        ("version", "2.0.0"),
        ("sha256", "0" * 64),
        ("registry_payload_sha256", "0" * 64),
    ],
)
def test_any_signed_wheel_mismatch_refuses(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    with pytest.raises(target.InstallerSignedWheelBridgeError, match="differs"):
        _review(monkeypatch, mutate=lambda x: replace(x, **{field: value}))


@pytest.mark.parametrize(
    "bad",
    [
        (),
        _sources()[:2],
        _sources() + _sources()[:1],
        tuple(reversed(_sources())),
        tuple(replace(x, wheel_path=Path("dup.whl")) for x in _sources()),
        tuple(replace(x, module_envelope=b"") for x in _sources()),
        tuple(replace(x, module_envelope=b"x" * 262145) for x in _sources()),
    ],
)
def test_incorrect_candidate_set_refuses(bad: object) -> None:
    with pytest.raises(target.InstallerSignedWheelBridgeError):
        target.review_installer_signed_wheels(
            _raw(),
            candidates=bad,
            registry_envelope=b"catalog",
            trust=_trust(),
            now=_NOW,
        )


@pytest.mark.parametrize("raw", [b"", b"{}", b"not-json", _raw() + b"\n"])
def test_bad_intent_refuses(raw: bytes) -> None:
    with pytest.raises(
        target.InstallerSignedWheelBridgeError, match="invalid installer intent"
    ):
        target.review_installer_signed_wheels(
            raw,
            candidates=_sources(),
            registry_envelope=b"catalog",
            trust=_trust(),
            now=_NOW,
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("registry_envelope", b""),
        ("registry_envelope", b"x" * 262145),
        ("trust", object()),
        ("now", datetime(2026, 11, 1)),
        ("now", "2026-11-01"),
    ],
    ids=(
        "empty-registry",
        "oversized-registry",
        "bad-trust",
        "naive-time",
        "string-time",
    ),
)
def test_bad_independent_context_refuses(key: str, value: object) -> None:
    args: dict[str, object] = {
        "candidates": _sources(),
        "registry_envelope": b"catalog",
        "trust": _trust(),
        "now": _NOW,
    }
    args[key] = value
    with pytest.raises(target.InstallerSignedWheelBridgeError):
        target.review_installer_signed_wheels(_raw(), **args)  # type: ignore[arg-type]


def test_release_verification_failure_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def refusal(*args: object, **kwargs: object) -> object:
        raise ReleaseArtifactError("signature mismatch")

    monkeypatch.setattr(target, "verify_signed_release_wheel", refusal)
    with pytest.raises(
        target.InstallerSignedWheelBridgeError, match="verification failed"
    ):
        target.review_installer_signed_wheels(
            _raw(),
            candidates=_sources(),
            registry_envelope=b"catalog",
            trust=_trust(),
            now=_NOW,
        )


def test_duplicate_signed_module_identity_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def verifier(path: Path, **kwargs: object) -> VerifiedReleaseWheel:
        name = path.name.removesuffix("-wheel.whl")
        return VerifiedReleaseWheel(
            "same-module",
            name,
            "1.2.3",
            path.name,
            "def0"[_DISTS.index(name)] * 64,
            "f" * 64,
            "b" * 64,
            (),
            "console",
            "package:main",
        )

    monkeypatch.setattr(target, "verify_signed_release_wheel", verifier)
    with pytest.raises(target.InstallerSignedWheelBridgeError, match="duplicate"):
        target.review_installer_signed_wheels(
            _raw(),
            candidates=_sources(),
            registry_envelope=b"catalog",
            trust=_trust(),
            now=_NOW,
        )


def test_no_cli_apply_or_path_argument() -> None:
    with pytest.raises(SystemExit) as result:
        target.main(["--apply"])
    assert result.value.code == 2
    with pytest.raises(SystemExit) as result:
        target.main(["--wheel", "untrusted.whl"])
    assert result.value.code == 2


def test_cli_is_non_authorizing(capsys: pytest.CaptureFixture[str]) -> None:
    assert target.main([]) == 2
    output = capsys.readouterr().out
    assert '"production_authority": false' in output
    assert '"privileged_installer_implemented": false' in output
    assert target._NO_AUTHORITY in output


def test_wheel_filesystem_read_failure_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        raise PermissionError("wheel cannot be read")

    monkeypatch.setattr(target, "verify_signed_release_wheel", unavailable)
    with pytest.raises(
        target.InstallerSignedWheelBridgeError, match="verification failed"
    ):
        target.review_installer_signed_wheels(
            _raw(),
            candidates=_sources(),
            registry_envelope=b"catalog",
            trust=_trust(),
            now=_NOW,
        )
