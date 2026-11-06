"""Slice 56: verified remote service exchange to real Slice-52 read-only flow."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice52_fresh_attested_recovery as earlier

import paper_data_suite.evergreen_fresh_attested_recovery as local_module
import paper_data_suite.evergreen_pinned_remote_recovery as module
from paper_data_suite.evergreen_fresh_attested_recovery import (
    FreshAttestedRecoveryError,
)
from paper_data_suite.evergreen_pinned_remote_recovery import (
    PinnedRemoteRecoveryError,
    inspect_pinned_remote_forward_recovery,
)
from paper_data_suite.evergreen_recovery_observation_https import (
    ProvisionedRecoveryObservationHttpsClient,
    RecoveryObservationHttpsError,
    SignedRecoveryServiceExchange,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    verify_service_recovery_attestation,
)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Real canonical receipts and real Ed25519 service signature. The earlier
    # Slice-52 fixture substitutes only local signed-head/physical inspectors;
    # their actual implementations are independently covered by prior slices.
    earlier_scene = earlier.ready.__wrapped__(tmp_path, monkeypatch)
    arguments = dict(earlier_scene["inputs"])
    original = arguments.pop("signed_service_envelope")
    nonce = arguments.pop("challenge")
    public = arguments.pop("pinned_service_public_key")
    signed = verify_service_recovery_attestation(
        original,
        request=arguments["request"],
        challenge=nonce,
        pinned_service_public_key=public,
        now=earlier.NOW,
    )
    client = ProvisionedRecoveryObservationHttpsClient(
        "https://recovery.example.test",
        tmp_path / "ca.pem",
        "a" * 64,
        tmp_path / "client.pem",
        tmp_path / "client.key",
        public,
    )
    exchange = SignedRecoveryServiceExchange(nonce, original, signed)
    calls: list[tuple[object, datetime]] = []
    payload: dict[str, Any] = {"exchange": exchange, "error": None}

    def fetch(
        self: ProvisionedRecoveryObservationHttpsClient, req: object, *, now: datetime
    ) -> SignedRecoveryServiceExchange:
        assert self is client
        calls.append((req, now))
        failure = payload["error"]
        if failure is not None:
            raise failure
        return payload["exchange"]

    monkeypatch.setattr(ProvisionedRecoveryObservationHttpsClient, "fetch", fetch)
    arguments["service_client"] = client
    return {
        "arguments": arguments,
        "earlier": earlier_scene,
        "calls": calls,
        "payload": payload,
        "signed": signed,
        "nonce": nonce,
        "raw": original,
    }


def run(scene: dict[str, Any], **updates: Any) -> Any:
    return inspect_pinned_remote_forward_recovery(**{**scene["arguments"], **updates})


def test_valid_remote_exchange_must_run_fresh_read_only_local_audits(
    scene: dict[str, Any],
) -> None:
    result = run(scene)
    assert scene["calls"] == [(scene["arguments"]["request"], earlier.NOW)]
    assert scene["earlier"]["calls"] == {"local": 2, "audit": 1}
    assert result.service_envelope_sha256 == hashlib.sha256(scene["raw"]).hexdigest()
    assert (
        result.fresh_observation.attested_handoff.service_observation == scene["signed"]
    )
    assert result.status == "PINNED_REMOTE_FORWARD_RECOVERY_REVIEW_ONLY"
    assert result.authority == (
        "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_OR_CLEANUP_AUTHORITY"
    )
    for name in ("activate", "rollback", "commit", "launch", "cleanup", "switch"):
        assert not hasattr(result, name)


@pytest.mark.parametrize(
    "change",
    [
        {"transaction_id": "e" * 32},
        {"request": None},
        {"service_client": object()},
        {"pinned_witness_public_key": b"short"},
        {"now": datetime(2026, 10, 22, 21)},
        {"now": earlier.NOW.replace(microsecond=1)},
        {"witness_transport": None},
        {"candidate_module_envelopes": None},
        {"software_root": "not-a-path"},
        {"candidate": None},
    ],
)
def test_invalid_inputs_refuse_without_service_contact(
    scene: dict[str, Any], change: dict[str, Any]
) -> None:
    with pytest.raises(PinnedRemoteRecoveryError):
        run(scene, **change)
    assert scene["calls"] == []
    assert scene["earlier"]["calls"] == {"local": 0, "audit": 0}


def test_service_transport_failure_precedes_local_reads(scene: dict[str, Any]) -> None:
    scene["payload"]["error"] = RecoveryObservationHttpsError("network unavailable")
    with pytest.raises(PinnedRemoteRecoveryError, match="pinned network"):
        run(scene)
    assert len(scene["calls"]) == 1
    assert scene["earlier"]["calls"] == {"local": 0, "audit": 0}


@pytest.mark.parametrize(
    "mutation",
    [
        {"challenge": b"X" * 32},
        {"challenge": b"short"},
        {"signed_envelope": b"not signed"},
        {"verified": None},
        {"status": "CAN_ACTIVATE"},
        {"authority": "CAN_COMMIT"},
    ],
)
def test_tampered_exchange_refused_before_local_read(
    scene: dict[str, Any], mutation: dict[str, Any]
) -> None:
    scene["payload"]["exchange"] = replace(scene["payload"]["exchange"], **mutation)
    with pytest.raises(PinnedRemoteRecoveryError):
        run(scene)
    assert len(scene["calls"]) == 1
    assert scene["earlier"]["calls"] == {"local": 0, "audit": 0}


def test_fabricated_verified_metadata_refuses_even_with_valid_signed_bytes(
    scene: dict[str, Any],
) -> None:
    false_verified = replace(scene["signed"], witness_revision=999)
    scene["payload"]["exchange"] = replace(
        scene["payload"]["exchange"], verified=false_verified
    )
    with pytest.raises(PinnedRemoteRecoveryError, match="verification"):
        run(scene)
    assert scene["earlier"]["calls"] == {"local": 0, "audit": 0}


def test_missing_signed_successor_refuses_after_remote_fetch(
    scene: dict[str, Any],
) -> None:
    scene["earlier"]["observations"][0] = replace(
        scene["earlier"]["local"], status="PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"
    )
    with pytest.raises(PinnedRemoteRecoveryError):
        run(scene)
    assert len(scene["calls"]) == 1
    assert scene["earlier"]["calls"] == {"local": 1, "audit": 0}


def test_physical_byte_audit_refusal_propagates_without_authority(
    scene: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise FreshAttestedRecoveryError("publisher digest mismatch")

    monkeypatch.setattr(local_module, "requalify_witnessed_successor_bytes", refused)
    with pytest.raises(PinnedRemoteRecoveryError):
        run(scene)
    assert len(scene["calls"]) == 1


def test_local_drift_after_audit_refuses(scene: dict[str, Any]) -> None:
    scene["earlier"]["observations"][1] = replace(
        scene["earlier"]["local"], observed_receipt_sha256="0" * 64
    )
    with pytest.raises(PinnedRemoteRecoveryError):
        run(scene)
    assert scene["earlier"]["calls"] == {"local": 2, "audit": 1}


def test_network_elapsed_budget_refuses_before_local_inspection(
    scene: dict[str, Any],
) -> None:
    with patch.object(module.time, "monotonic", side_effect=[0.0, 31.0]):
        with pytest.raises(PinnedRemoteRecoveryError, match="elapsed"):
            run(scene)
    assert scene["earlier"]["calls"] == {"local": 0, "audit": 0}


def test_bridge_uses_exact_client_pin_and_does_not_accept_raw_envelope_input(
    scene: dict[str, Any],
) -> None:
    with pytest.raises(TypeError):
        run(scene, signed_service_envelope=scene["raw"])
    assert scene["calls"] == []


def test_no_subprocess_or_local_mutation_in_review_bridge(
    scene: dict[str, Any], tmp_path: Path
) -> None:
    classroom = tmp_path / "classroom"
    classroom.mkdir()
    (classroom / "writing.txt").write_text("unmodified")
    with (
        patch("subprocess.run", side_effect=AssertionError("process")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("file mutation")),
    ):
        result = run(scene)
    assert result.status.endswith("REVIEW_ONLY")
    assert (classroom / "writing.txt").read_text() == "unmodified"
    assert len(scene["calls"]) == 1
