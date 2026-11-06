"""Slice 60: freshly audited staged bytes, never installed launch authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice58_catalog_preview as previous
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import paper_data_suite.evergreen_catalog_stage_correlation as module
from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelationError,
    inspect_catalog_bound_staged_bytes,
)
from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    RevisionCheckpoint,
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    ObservedPublisherPipCandidate,
    PublisherPipPreflightError,
)

NOW = datetime(2026, 10, 24, 21, tzinfo=UTC)
TX = "f" * 32
REGISTRY = "a" * 64
LOCK = "f" * 64
PUBLISHER = "d" * 64
PIP = "1" * 64
NATIVE = "2" * 64


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    snapshot = previous.fixture_snapshot()
    stage = tmp_path / "staged"
    wheels = tmp_path / "wheelhouse"
    stage.mkdir()
    wheels.mkdir()
    witness_file = stage / "untouched.txt"
    witness_file.write_text("staged data must not change")
    signing = Ed25519PrivateKey.generate()
    trust = TrustedKeyring(
        (
            TrustedPublicKey(
                "root-key",
                signing.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
            ),
        ),
        ("root-key",),
    )
    release = snapshot.modules[0].claims.releases[0]
    prepared = SimpleNamespace(
        transaction_id=TX,
        registry_payload_sha256=REGISTRY,
        trust_fingerprint=REGISTRY,
        lock_payload_sha256=LOCK,
        wheels=(
            SimpleNamespace(
                distribution="pds-quillan",
                version=release.version,
                filename=release.wheel,
                sha256=release.sha256,
            ),
            SimpleNamespace(
                distribution="packaging",
                version="24.0.0",
                filename="packaging-24.0.0-py3-none-any.whl",
                sha256="c" * 64,
            ),
        ),
    )
    calls: list[str] = []

    def registry_check(*args: Any, **kwargs: Any) -> Any:
        calls.append("registry")
        return snapshot.registry

    def module_check(*args: Any, **kwargs: Any) -> Any:
        calls.append("publisher")
        return snapshot.modules[0]

    def pip_check(*args: Any, **kwargs: Any) -> ObservedPublisherPipCandidate:
        calls.append("pip")
        assert args == (stage, wheels)
        assert kwargs["trust"] is trust
        assert kwargs["module_envelopes"] == {"quillan": b"signed module"}
        return ObservedPublisherPipCandidate(
            TX,
            stage,
            wheels,
            REGISTRY,
            LOCK,
            PIP,
            (("quillan", PUBLISHER),),
            (("pds-quillan", "quillan", "quillan.cli:main"),),
            ("packaging",),
            ("Scripts/quillan.exe",),
        )

    def native_check(*args: Any, **kwargs: Any) -> VerifiedNativeEvidence:
        calls.append("native")
        assert kwargs["evidence_envelope"] == b"signed native"
        return VerifiedNativeEvidence(
            TX,
            stage,
            2,
            NATIVE,
            ("root-key",),
            (),
            RevisionCheckpoint(2, NATIVE),
        )

    monkeypatch.setattr(module, "verify_registry_document", registry_check)
    monkeypatch.setattr(module, "verify_module_document", module_check)
    monkeypatch.setattr(module, "parse_unverified_prepared_record", lambda _: prepared)
    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", pip_check)
    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", native_check)
    args: dict[str, Any] = {
        "snapshot": snapshot,
        "stage_root": stage,
        "wheelhouse": wheels,
        "prepared_record": b"prepared",
        "registry_envelope": b"signed registry",
        "lock_envelope": b"signed lock",
        "module_envelopes": {"quillan": b"signed module"},
        "native_envelope": b"signed native",
        "trust": trust,
        "now": NOW,
    }
    return {
        "args": args,
        "prepared": prepared,
        "calls": calls,
        "file": witness_file,
    }


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return inspect_catalog_bound_staged_bytes(**{**ready["args"], **changes})


def test_authenticated_claims_correlate_to_two_fresh_staged_byte_audits(
    ready: dict[str, Any],
) -> None:
    with (
        patch("subprocess.run", side_effect=AssertionError("process")),
        patch("socket.create_connection", side_effect=AssertionError("network")),
    ):
        result = run(ready)
    assert result.transaction_id == TX
    assert result.pip_inventory_sha256 == PIP
    assert result.native_payload_sha256 == NATIVE
    assert len(result.modules) == 1
    assert result.modules[0].component_id == "quillan"
    assert result.modules[0].wheel_sha256 == "b" * 64
    assert result.status == "SIGNED_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
    assert result.authority == "NO_LAUNCH_RECEIPT_ACTIVATION_OR_UPDATE_AUTHORITY"
    assert ready["calls"] == ["registry", "publisher", "pip", "native", "pip", "native"]
    assert ready["file"].read_text() == "staged data must not change"
    for method in ("launch", "activate", "commit", "rollback", "update"):
        assert not hasattr(result, method)


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot", object()),
        ("stage_root", "not a Path"),
        ("wheelhouse", None),
        ("module_envelopes", {}),
        ("module_envelopes", {"quillan": "not bytes"}),
        ("now", datetime(2026, 10, 24, 21)),
        ("trust", None),
        ("native_envelope", None),
    ],
)
def test_invalid_inputs_refuse_before_any_audit(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(CatalogStageCorrelationError, match="inputs"):
        run(ready, **{field: value})
    assert ready["calls"] == []


def test_different_registry_refuses_before_pip(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module, "verify_registry_document", lambda *a, **k: SimpleNamespace()
    )
    with pytest.raises(CatalogStageCorrelationError, match="registry differs"):
        run(ready)
    assert "pip" not in ready["calls"]


def test_different_publisher_refuses_before_pip(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module, "verify_module_document", lambda *a, **k: SimpleNamespace()
    )
    with pytest.raises(CatalogStageCorrelationError, match="publisher envelope"):
        run(ready)
    assert "pip" not in ready["calls"]


def test_uncached_publisher_refuses(
    ready: dict[str, Any],
) -> None:
    with pytest.raises(CatalogStageCorrelationError, match="not present"):
        run(ready, module_envelopes={"scoreform": b"unknown module"})


@pytest.mark.parametrize("change", ["version", "sha256", "filename"])
def test_mismatched_wheel_refused_before_physical_audit(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    prepared = ready["prepared"]
    altered = SimpleNamespace(**{**vars(prepared.wheels[0]), change: "different"})
    monkeypatch.setattr(
        module,
        "parse_unverified_prepared_record",
        lambda _: SimpleNamespace(**{**vars(prepared), "wheels": (altered,)}),
    )
    with pytest.raises(CatalogStageCorrelationError, match="mismatched"):
        run(ready)
    assert "pip" not in ready["calls"]


def test_revoked_release_refused_before_audit(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = ready["args"]["snapshot"]
    revoked = replace(snapshot.modules[0].claims.releases[0], revoked=True)
    updated_module = replace(
        snapshot.modules[0],
        claims=replace(snapshot.modules[0].claims, releases=(revoked,)),
    )
    updated_snapshot = replace(snapshot, modules=(updated_module,))
    monkeypatch.setattr(
        module, "verify_module_document", lambda *a, **k: updated_module
    )
    with pytest.raises(CatalogStageCorrelationError, match="revoked"):
        run(ready, snapshot=updated_snapshot)
    assert "pip" not in ready["calls"]


def test_physical_audit_failure_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise PublisherPipPreflightError("modified staged file")

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", fail)
    with pytest.raises(CatalogStageCorrelationError, match="physical"):
        run(ready)


def test_native_signature_refusal_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise NativeEvidenceError("native not root signed")

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", fail)
    with pytest.raises(CatalogStageCorrelationError, match="physical"):
        run(ready)


def test_signature_refusal_before_physical_audit(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise CatalogVerificationError("signer rejected")

    monkeypatch.setattr(module, "verify_registry_document", fail)
    with pytest.raises(CatalogStageCorrelationError, match="publisher authorization"):
        run(ready)
    assert "pip" not in ready["calls"]


def test_changed_pip_inventory_between_reads_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = module.audit_publisher_bound_pip_candidate
    observed = 0

    def drifting(*args: Any, **kwargs: Any) -> ObservedPublisherPipCandidate:
        nonlocal observed
        observed += 1
        result = prior(*args, **kwargs)
        if observed == 2:
            return replace(result, pip_inventory_sha256="9" * 64)
        return result

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", drifting)
    with pytest.raises(CatalogStageCorrelationError, match="changed"):
        run(ready)


def test_changed_native_inventory_between_reads_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prior = module.verify_signed_staged_native_evidence
    observed = 0

    def drifting(*args: Any, **kwargs: Any) -> VerifiedNativeEvidence:
        nonlocal observed
        observed += 1
        result = prior(*args, **kwargs)
        if observed == 2:
            return replace(result, payload_sha256="9" * 64)
        return result

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", drifting)
    with pytest.raises(CatalogStageCorrelationError, match="changed"):
        run(ready)


def test_publisher_digest_mismatch_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = module.audit_publisher_bound_pip_candidate

    def changed(*args: Any, **kwargs: Any) -> ObservedPublisherPipCandidate:
        result = original(*args, **kwargs)
        return replace(result, publisher_digests=(("quillan", "0" * 64),))

    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", changed)
    with pytest.raises(CatalogStageCorrelationError, match="audited stage"):
        run(ready)


def test_dependent_external_wheel_does_not_fake_a_publisher(
    ready: dict[str, Any],
) -> None:
    report = run(ready)
    assert [row.component_id for row in report.modules] == ["quillan"]
