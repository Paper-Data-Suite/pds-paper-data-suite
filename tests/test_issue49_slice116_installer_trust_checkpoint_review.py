"""Slice 116: pinned-trust and checkpoint claims remain non-authorizing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_data_suite import (
    evergreen_windows_installer_trust_checkpoint_review as target,
)
from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
)
from paper_data_suite.evergreen_dependency_lock import DependencyLockError
from paper_data_suite.evergreen_trust_provisioning import TrustProvisioningError
from paper_data_suite.evergreen_windows_installer_intent import _PHASES
from paper_data_suite.evergreen_windows_installer_locked_wheelhouse import (
    InstallerLockedWheelhouseError,
    LockedInstallerWheelhouseReview,
)

_NAMES = ("paper-data-suite", "pds-core")
_TIME = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _intent() -> bytes:
    payload = {
        "schema": 1,
        "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
        "service_name": "PaperDataSuiteService",
        "transaction_id": "a" * 32,
        "catalog_sha256": "b" * 64,
        "recovery_basis_sha256": "f" * 64,
        "artifacts": [
            {"distribution": name, "version": "1.2.3", "sha256": "d" * 64}
            for name in _NAMES
        ],
        "requested_phases": list(_PHASES),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _closed(request: bytes) -> LockedInstallerWheelhouseReview:
    return LockedInstallerWheelhouseReview(
        status="SIGNED_CLOSED_WHEELHOUSE_MATCHES_UNTRUSTED_INSTALLER_INTENT_ONLY",
        request_sha256=hashlib.sha256(request).hexdigest(),
        registry_payload_sha256="b" * 64,
        signed_lock_payload_sha256="c" * 64,
        signed_lock_revision=5,
        python_minor="3.13",
        platform_tag="win-amd64",
        pds_distributions=_NAMES,
        external_dependency_distributions=("packaging",),
        dependency_edge_count=3,
    )


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    request = _intent()
    previous_registry = RevisionCheckpoint(3, "a" * 64)
    previous_lock = RevisionCheckpoint(4, "e" * 64)
    reg = SimpleNamespace(
        payload_sha256="b" * 64,
        trust_fingerprint="trust-fingerprint",
        checkpoint=RevisionCheckpoint(4, "b" * 64),
    )
    lock = SimpleNamespace(
        payload_sha256="c" * 64,
        registry_payload_sha256="b" * 64,
        trust_fingerprint="trust-fingerprint",
        roots=_NAMES,
        revision=5,
        checkpoint=RevisionCheckpoint(5, "c" * 64),
    )
    closed = _closed(request)
    pinned = SimpleNamespace(keyring=object(), sha256="7" * 64, policy_revision=2)
    monkeypatch.setattr(
        target, "load_digest_pinned_trust_policy", lambda *a, **kw: pinned
    )
    monkeypatch.setattr(target, "verify_registry_document", lambda *a, **kw: reg)
    monkeypatch.setattr(target, "verify_signed_dependency_lock", lambda *a, **kw: lock)
    monkeypatch.setattr(
        target, "review_installer_locked_wheelhouse", lambda *a, **kw: closed
    )
    return {
        "raw_intent": request,
        "candidates": (),
        "wheelhouse": tmp_path,
        "registry_envelope": b"registry-envelope",
        "lock_envelope": b"lock-envelope",
        "trust_policy_bytes": b"policy-bytes",
        "expected_policy_sha256": "7" * 64,
        "previous_registry": previous_registry,
        "previous_lock": previous_lock,
        "now": _TIME,
        "_registry": reg,
        "_lock": lock,
        "_closed": closed,
    }


def _review(ctx: dict[str, object]) -> target.InstallerTrustCheckpointReview:
    return target.review_installer_trust_and_checkpoints(
        **{key: value for key, value in ctx.items() if not key.startswith("_")}
    )


def test_complete_matching_evidence_is_only_non_authorizing_consistency(
    ctx: dict[str, object],
) -> None:
    review = _review(ctx)
    assert (
        review.status == "PINNED_TRUST_AND_REVISION_EVIDENCE_MATCH_SIGNED_WHEELS_ONLY"
    )
    assert review.artifact_distributions == _NAMES
    assert review.registry_revision == 4
    assert review.signed_lock_revision == 5
    assert review.dependency_edge_count == 3
    for name in (
        "pin_independently_provisioned",
        "checkpoint_custody_independently_established",
        "administrator_authenticated",
        "authorized_to_provision",
        "authorized_to_register_service",
        "authorized_to_publish_receipt",
        "authorized_to_activate_or_launch",
    ):
        assert getattr(review, name) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_intent", b"garbage"),
        ("registry_envelope", b""),
        ("registry_envelope", b"x" * (256 * 1024 + 1)),
        ("lock_envelope", b""),
        ("lock_envelope", b"x" * (48 * 1024 + 1)),
        ("trust_policy_bytes", b""),
        ("trust_policy_bytes", b"x" * (24 * 1024 + 1)),
        ("expected_policy_sha256", 2),
        ("previous_registry", None),
        ("previous_lock", None),
        ("wheelhouse", "not-a-path"),
        ("candidates", []),
        ("now", datetime(2026, 11, 1)),
    ],
    ids=(
        "malformed-intent",
        "empty-registry",
        "huge-registry",
        "empty-lock",
        "huge-lock",
        "empty-policy",
        "huge-policy",
        "bad-policy-pin",
        "missing-registry-checkpoint",
        "missing-lock-checkpoint",
        "bad-wheelhouse",
        "bad-candidates",
        "naive-time",
    ),
)
def test_invalid_inputs_refuse(
    ctx: dict[str, object], field: str, value: object
) -> None:
    ctx[field] = value
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("payload_sha256", "f" * 64),
        ("trust_fingerprint", "wrong"),
        ("checkpoint", RevisionCheckpoint(4, "a" * 64)),
        ("checkpoint", RevisionCheckpoint(2, "b" * 64)),
    ],
    ids=(
        "registry-hash",
        "registry-fingerprint",
        "registry-equivocation",
        "registry-rollback",
    ),
)
def test_registry_mismatch_refuses(
    ctx: dict[str, object], member: str, value: object
) -> None:
    setattr(ctx["_registry"], member, value)
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("registry_payload_sha256", "f" * 64),
        ("trust_fingerprint", "wrong"),
        ("roots", ("paper-data-suite",)),
        ("roots", _NAMES + (_NAMES[0],)),
        ("checkpoint", RevisionCheckpoint(5, "f" * 64)),
        ("checkpoint", RevisionCheckpoint(3, "c" * 64)),
    ],
    ids=(
        "lock-registry",
        "lock-fingerprint",
        "missing-root",
        "duplicate-root",
        "lock-equivocation",
        "lock-rollback",
    ),
)
def test_signed_lock_mismatch_refuses(
    ctx: dict[str, object], member: str, value: object
) -> None:
    setattr(ctx["_lock"], member, value)
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("status", "ADMIN_APPROVED"),
        ("registry_payload_sha256", "f" * 64),
        ("signed_lock_payload_sha256", "f" * 64),
        ("signed_lock_revision", 99),
        ("pds_distributions", ("paper-data-suite",)),
        ("request_sha256", "a" * 64),
        ("independently_pinned_root", True),
        ("independently_continuous_checkpoints", True),
        ("authenticated_administrator", True),
        ("authorized_to_provision", True),
        ("authorized_to_register_service", True),
        ("authorized_to_publish_receipt", True),
        ("authorized_to_activate_or_launch", True),
        ("authority", "ALLOW_INSTALL"),
    ],
    ids=(
        "status",
        "registry",
        "lock-hash",
        "lock-revision",
        "names",
        "request",
        "trust-flag",
        "checkpoint-flag",
        "admin-flag",
        "provision-flag",
        "service-flag",
        "receipt-flag",
        "launch-flag",
        "authority",
    ),
)
def test_forged_wheelhouse_review_refuses(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch, member: str, value: object
) -> None:
    changed = replace(ctx["_closed"], **{member: value})
    monkeypatch.setattr(
        target, "review_installer_locked_wheelhouse", lambda *a, **kw: changed
    )
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


def test_signature_or_wheelhouse_verifier_refusal_propagates(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*args: object, **kwargs: object) -> object:
        raise InstallerLockedWheelhouseError("forbidden")

    monkeypatch.setattr(target, "review_installer_locked_wheelhouse", reject)
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


def test_cli_never_admits_or_reads_user_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert target.main([]) == 2
    out = capsys.readouterr().out
    parsed = json.loads(out.split("\n" + target._NO_AUTHORITY)[0])
    assert parsed["independent_root_pin_provisioned"] is False
    assert parsed["protected_monotonic_checkpoints_established"] is False
    assert parsed["production_authority"] is False
    assert parsed["active_receipt_authority"] is False


def test_cli_rejects_apply_and_fake_pin() -> None:
    with pytest.raises(SystemExit) as raised:
        target.main(["--apply"])
    assert raised.value.code == 2
    with pytest.raises(SystemExit) as raised:
        target.main(["--policy-pin", "a" * 64])
    assert raised.value.code == 2


@pytest.mark.parametrize(
    ("dependency", "error"),
    [
        ("load_digest_pinned_trust_policy", TrustProvisioningError("bad pin")),
        ("verify_registry_document", CatalogVerificationError("bad signature")),
        ("verify_signed_dependency_lock", DependencyLockError("rollback")),
    ],
    ids=("wrong-pin", "wrong-signer", "lock-rollback"),
)
def test_provenance_verifier_failures_refuse(
    ctx: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
    error: ValueError,
) -> None:
    def reject(*args: object, **kwargs: object) -> object:
        raise error

    monkeypatch.setattr(target, dependency, reject)
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


def test_forged_policy_digest_refuses(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = SimpleNamespace(keyring=object(), sha256="0" * 64, policy_revision=2)
    monkeypatch.setattr(target, "load_digest_pinned_trust_policy", lambda *a, **k: bad)
    with pytest.raises(target.InstallerTrustCheckpointError):
        _review(ctx)


def test_verifiers_receive_explicit_previous_checkpoints(
    ctx: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    registry = ctx["_registry"]
    lock = ctx["_lock"]

    def reg(*args: object, **kwargs: object) -> object:
        observed["registry_checkpoint"] = kwargs["checkpoint"]
        return registry

    def dependency(*args: object, **kwargs: object) -> object:
        observed["lock_checkpoint"] = kwargs["checkpoint"]
        observed["lock_registry_checkpoint"] = kwargs["registry_checkpoint"]
        return lock

    monkeypatch.setattr(target, "verify_registry_document", reg)
    monkeypatch.setattr(target, "verify_signed_dependency_lock", dependency)
    _review(ctx)
    assert observed["registry_checkpoint"] is ctx["previous_registry"]
    assert observed["lock_registry_checkpoint"] is ctx["previous_registry"]
    assert observed["lock_checkpoint"] is ctx["previous_lock"]
