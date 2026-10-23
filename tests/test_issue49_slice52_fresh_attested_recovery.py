"""Slice 52: signed-service-first orchestration; still no activation authority."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import paper_data_suite.evergreen_fresh_attested_recovery as module
from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_forward_byte_requalification import (
    ForwardByteRequalificationError,
    ObservedForwardSuccessorBytes,
)
from paper_data_suite.evergreen_fresh_attested_recovery import (
    FreshAttestedRecoveryError,
    inspect_fresh_attested_forward_recovery,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_local_receipt_recovery import (
    ForwardRecoveryObservation,
    LocalReceiptRecoveryError,
)
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_service_recovery_attestation import (
    issue_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 22, 21, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
CHALLENGE = b"R" * 32


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        wheels,
        "3" * 64,
        "4" * 64,
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def ready(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    prior = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old-p",
        registry_envelope=b"old-r",
        lock_envelope=b"old-l",
        native_envelope=b"old-n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=4),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"new-p",
        registry_envelope=b"new-r",
        lock_envelope=b"new-l",
        native_envelope=b"new-n",
        generation=2,
        recorded_at=NOW - timedelta(minutes=1),
        previous=ExternallyPinnedReceiptHead(1, sha(prior)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, prior, successor)
    signed_state = WitnessWriterQuiescenceState(
        INSTALL,
        sha(serialize_witness_commit_request(request)),
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        sha(successor),
    )
    signer = Ed25519PrivateKey.generate()
    envelope = issue_service_recovery_attestation(
        request, signed_state, challenge=CHALLENGE, observed_at=NOW, sign=signer.sign
    )
    public = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    root = Ed25519PrivateKey.generate()
    trust = TrustedKeyring(
        (
            TrustedPublicKey(
                "root_key",
                root.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
            ),
        ),
        ("root_key",),
    )
    local = ForwardRecoveryObservation(
        NEXT,
        2,
        2,
        sha(successor),
        "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED",
    )
    observed = ObservedForwardSuccessorBytes(
        NEXT, 2, sha(successor), 2, "4" * 64, "3" * 64, "candidate/two"
    )
    calls: dict[str, int] = {"local": 0, "audit": 0}
    observations = [local, local]

    def local_read(*args: Any, **kwargs: Any) -> ForwardRecoveryObservation:
        calls["local"] += 1
        assert kwargs["transaction_id"] == NEXT
        assert kwargs["pinned_public_key"] == b"W" * 32
        return observations[min(calls["local"] - 1, len(observations) - 1)]

    def audited(*args: Any, **kwargs: Any) -> ObservedForwardSuccessorBytes:
        calls["audit"] += 1
        assert kwargs["transaction_id"] == NEXT
        assert kwargs["convergence"].finding == (
            "MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED"
        )
        assert kwargs["pinned_public_key"] == b"W" * 32
        return observed

    monkeypatch.setattr(module, "inspect_pending_forward_recovery", local_read)
    monkeypatch.setattr(module, "requalify_witnessed_successor_bytes", audited)
    inputs: dict[str, Any] = {
        "software_root": tmp_path / "software",
        "classroom_workspace": tmp_path / "classroom",
        "transaction_id": NEXT,
        "request": request,
        "signed_service_envelope": envelope,
        "challenge": CHALLENGE,
        "pinned_service_public_key": public,
        "witness_transport": lambda _: b"not-called-by-stubs",
        "pinned_witness_public_key": b"W" * 32,
        "candidate": ProposedCandidateEvidence(b"new-p", b"new-r", b"new-l", b"new-n"),
        "candidate_module_envelopes": {"quillan": b"publisher"},
        "trust": trust,
        "now": NOW,
    }
    return {
        "inputs": inputs,
        "calls": calls,
        "observations": observations,
        "local": local,
        "observed": observed,
        "request": request,
    }


def run(ready: dict[str, Any], **updates: Any) -> Any:
    return inspect_fresh_attested_forward_recovery(**{**ready["inputs"], **updates})


def test_success_requires_two_local_reads_and_one_audit(
    ready: dict[str, Any],
) -> None:
    result = run(ready)
    assert ready["calls"] == {"local": 2, "audit": 1}
    assert result.signed_local_reads == 2
    assert result.signed_requalification_reads == 1
    assert result.status == "FRESH_ATTESTED_FORWARD_REVIEW_ONLY_RECOVERY_STILL_PENDING"
    assert result.authority == "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_OR_CLEANUP_AUTHORITY"
    assert result.attested_handoff.forward_handoff.transaction_id == NEXT
    assert result.attested_handoff.service_envelope_sha256 == sha(
        ready["inputs"]["signed_service_envelope"]
    )
    for verb in ("launch", "activate", "rollback", "commit", "clear_recovery"):
        assert not hasattr(result, verb)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("signed_service_envelope", b"garbage"),
        ("challenge", b"wrong"),
        ("pinned_service_public_key", b"X" * 32),
        ("now", NOW + timedelta(seconds=60)),
        ("request", None),
    ],
)
def test_service_refusal_precedes_local_and_audits(
    ready: dict[str, Any], field: str, bad: Any
) -> None:
    with pytest.raises(FreshAttestedRecoveryError):
        run(ready, **{field: bad})
    assert ready["calls"] == {"local": 0, "audit": 0}


def test_unrelated_transaction_refused_before_local(ready: dict[str, Any]) -> None:
    with pytest.raises(FreshAttestedRecoveryError, match="different transaction"):
        run(ready, transaction_id="d" * 32)
    assert ready["calls"] == {"local": 0, "audit": 0}


@pytest.mark.parametrize(
    "status", ["PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED", "UNKNOWN"]
)
def test_local_head_refusal_before_byte_audit(
    ready: dict[str, Any], status: str
) -> None:
    ready["observations"][0] = replace(ready["local"], status=status)
    with pytest.raises(FreshAttestedRecoveryError):
        run(ready)
    assert ready["calls"] == {"local": 1, "audit": 0}


def test_local_read_exception_refuses_before_audit(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: Any, **kwargs: Any) -> None:
        raise LocalReceiptRecoveryError("witness offline")

    monkeypatch.setattr(module, "inspect_pending_forward_recovery", failed)
    with pytest.raises(FreshAttestedRecoveryError):
        run(ready)
    assert ready["calls"]["audit"] == 0


def test_readback_after_audit_must_equal_initial(ready: dict[str, Any]) -> None:
    ready["observations"][1] = replace(ready["local"], observed_receipt_sha256="0" * 64)
    with pytest.raises(FreshAttestedRecoveryError, match="changed"):
        run(ready)
    assert ready["calls"] == {"local": 2, "audit": 1}


def test_changed_byte_audit_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def changed(*args: Any, **kwargs: Any) -> Any:
        return replace(ready["observed"], native_payload_sha256="0" * 64)

    monkeypatch.setattr(module, "requalify_witnessed_successor_bytes", changed)
    with pytest.raises(FreshAttestedRecoveryError):
        run(ready)


def test_failed_physical_audit_never_finalizes(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise ForwardByteRequalificationError("replaced executable")

    monkeypatch.setattr(module, "requalify_witnessed_successor_bytes", refused)
    with pytest.raises(FreshAttestedRecoveryError):
        run(ready)
    assert ready["calls"]["local"] == 1


def test_elapsed_budget_refuses_long_operation(ready: dict[str, Any]) -> None:
    with patch.object(module.time, "monotonic", side_effect=[0.0, 31.0]):
        with pytest.raises(FreshAttestedRecoveryError, match="elapsed"):
            run(ready)


def test_read_only_without_user_workspace_access(
    ready: dict[str, Any], tmp_path: Any
) -> None:
    teacher = tmp_path / "classroom-data"
    teacher.mkdir()
    (teacher / "writing.txt").write_text("preserved")
    with (
        patch("subprocess.run", side_effect=AssertionError("run")),
        patch("socket.create_connection", side_effect=AssertionError("socket")),
        patch("pathlib.Path.write_bytes", side_effect=AssertionError("writes")),
    ):
        run(ready)
    assert (teacher / "writing.txt").read_text() == "preserved"


def test_replay_service_response_for_wrong_successor_fails(
    ready: dict[str, Any],
) -> None:
    wrong = replace(ready["request"], witness_id="other_witness")
    with pytest.raises(FreshAttestedRecoveryError):
        run(ready, request=wrong)
    assert ready["calls"]["local"] == 0
