"""Slice 70: signed native candidate journal; never selection or activation."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import paper_data_suite.evergreen_plan_candidate_intent as module
from paper_data_suite.evergreen_plan_candidate_intent import (
    PlanCandidateIntentError,
    record_signed_plan_candidate_intent,
)

NOW = datetime(2026, 10, 25, 22, tzinfo=UTC)
TX = "a" * 32
CONSENT = "RECORD_SIGNED_CANDIDATE_VERIFIED_INTENT"


def _signed(raw: bytes) -> bytes:
    return json.dumps(
        {
            "envelope_version": 1,
            "payload_b64": base64.b64encode(raw).decode(),
            "signatures": [
                {
                    "key_id": "independent-root",
                    "algorithm": "ed25519",
                    "signature_b64": "a",
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "software"
    classroom = tmp_path / "classroom"
    wheels = root / "wheelhouse"
    stage = root / "candidate-builds" / TX
    stage.mkdir(parents=True)
    wheels.mkdir()
    classroom.mkdir()
    (classroom / "classroom.txt").write_bytes(b"original work remains intact")
    payload = json.dumps(
        {"issued_at": "2026-10-25T21:00:00Z", "expires_at": "2026-10-26T21:00:00Z"},
        sort_keys=True,
    ).encode()
    envelope = _signed(payload)
    digest = hashlib.sha256(payload).hexdigest()
    request = SimpleNamespace(
        transaction_id=TX,
        payload=payload,
        payload_sha256=digest,
        file_count=2,
        signed_lock_payload_sha256="f" * 64,
        pip_inventory_sha256="e" * 64,
    )
    installed = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        prepared_record=b"prepared",
        signed_lock_payload_sha256="f" * 64,
        pip_inventory_sha256="e" * 64,
        baseline_transaction_id="b" * 32,
        baseline_witness_revision=7,
    )
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256="c" * 64))
    witnessed = SimpleNamespace(transaction_id="b" * 32, witness_revision=7)
    signed = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        payload_sha256=digest,
        revision=4,
        binaries=("python", "quillan"),
    )
    observed = SimpleNamespace(
        transaction_id=TX,
        baseline_transaction_id="b" * 32,
        baseline_witness_revision=7,
        registry_payload_sha256="c" * 64,
        signed_lock_payload_sha256="f" * 64,
        pip_inventory_sha256="e" * 64,
        native_payload_sha256=digest,
        prepared_record_sha256=hashlib.sha256(b"prepared").hexdigest(),
        status="PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE",
        authority="NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY",
    )
    journal = SimpleNamespace(
        transaction_id=TX,
        phase=None,
        revision=1,
        stage_relative_path=f"candidate-builds/{TX}",
        wheelhouse_relative_path="wheelhouse",
        prepared_sha256=hashlib.sha256(b"prepared").hexdigest(),
        native_envelope_sha256=hashlib.sha256(envelope).hexdigest(),
        expected_previous_receipt_sha256=None,
    )
    commands: list[str] = []
    state: dict[str, Any] = {"journal": None}

    def native(*args: Any, **kwargs: Any) -> Any:
        commands.append("verify-root-native")
        assert args == (stage, wheels)
        assert kwargs["evidence_envelope"] == envelope
        return signed

    def regenerate(*args: Any, **kwargs: Any) -> Any:
        commands.append("remeasure-unsigned")
        assert args == (snapshot, witnessed, installed, root)
        assert kwargs["issued_at"] == datetime(2026, 10, 25, 21, tzinfo=UTC)
        assert kwargs["revision"] == 4
        return request

    def planned(*args: Any, **kwargs: Any) -> Any:
        commands.append("audit-plan-and-stage")
        assert args == (snapshot, witnessed, root)
        assert kwargs["stage_root"] == stage
        return observed

    def get_journal(*args: Any, **kwargs: Any) -> Any:
        commands.append("read-journal")
        return state["journal"]

    def write_journal(*args: Any, **kwargs: Any) -> Any:
        commands.append("persist-journal")
        assert args == (root,)
        assert kwargs["stage_root"] == stage
        assert kwargs["evidence_envelope"] == envelope
        state["journal"] = journal
        return journal

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "IsolatedPlanStageResult", SimpleNamespace)
    monkeypatch.setattr(module, "UnsignedNativeSigningRequest", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", native)
    monkeypatch.setattr(module, "prepare_unsigned_native_evidence_request", regenerate)
    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", planned)
    monkeypatch.setattr(module, "load_update_intent", get_journal)
    monkeypatch.setattr(module, "begin_verified_update_intent", write_journal)
    journal.phase = module.UpdatePhase.CANDIDATE_VERIFIED
    return {
        "args": dict(
            snapshot=snapshot,
            witnessed=witnessed,
            installed=installed,
            unsigned_request=request,
            software_root=root,
            classroom_workspace=classroom,
            wheelhouse=wheels,
            requested_targets={"quillan": "0.10.0"},
            python_minor="3.11",
            platform_tag="win_arm64",
            registry_envelope=b"registry",
            lock_envelope=b"lock",
            module_envelopes={"quillan": b"publisher"},
            native_envelope=envelope,
            trust=SimpleNamespace(),
            now=NOW,
            explicit_consent=CONSENT,
        ),
        "request": request,
        "installed": installed,
        "signed": signed,
        "snapshot": snapshot,
        "witnessed": witnessed,
        "observed": observed,
        "journal": journal,
        "state": state,
        "commands": commands,
        "stage": stage,
        "root": root,
        "classroom": classroom,
    }


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return record_signed_plan_candidate_intent(**{**ready["args"], **changes})


def test_real_candidate_journal_only_after_independent_signed_verification(
    ready: dict[str, Any],
) -> None:
    previous = (ready["classroom"] / "classroom.txt").read_bytes()
    with patch(
        "socket.create_connection", side_effect=AssertionError("unexpected network")
    ):
        result = run(ready)
    assert result.transaction_id == TX
    assert result.journal_revision == 1
    assert result.status == "CANDIDATE_VERIFIED_INTENT_NOT_ACTIVATED"
    assert result.authority == "NO_SELECTION_SWITCH_RECEIPT_WRITE_OR_LAUNCH_AUTHORITY"
    assert ready["commands"] == [
        "read-journal",
        "verify-root-native",
        "remeasure-unsigned",
        "audit-plan-and-stage",
        "persist-journal",
        "read-journal",
    ]
    assert (ready["classroom"] / "classroom.txt").read_bytes() == previous
    assert not (ready["root"] / "candidate-selection.json").exists()


@pytest.mark.parametrize(
    "alter",
    [
        {"explicit_consent": ""},
        {"explicit_consent": "yes"},
        {"native_envelope": b""},
        {"native_envelope": b"x" * (32 * 1024 + 1)},
        {"trust": None},
        {"now": datetime(2026, 10, 25)},
        {"module_envelopes": {"quillan": "not bytes"}},
        {"previous_receipt_sha256": "bad"},
        {"layout": "injected"},
    ],
)
def test_invalid_authority_refuses_before_reads(
    ready: dict[str, Any], alter: dict[str, Any]
) -> None:
    with pytest.raises(PlanCandidateIntentError):
        run(ready, **alter)
    assert ready["commands"] == []


def test_existing_journal_refuses_before_signer_call(ready: dict[str, Any]) -> None:
    ready["state"]["journal"] = ready["journal"]
    with pytest.raises(PlanCandidateIntentError, match="already exists"):
        run(ready)
    assert ready["commands"] == ["read-journal"]


def test_candidate_cannot_escape_software_root(ready: dict[str, Any]) -> None:
    ready["installed"].stage_root = ready["classroom"]
    with pytest.raises(PlanCandidateIntentError):
        run(ready)
    assert ready["commands"] == []


def test_candidate_requires_transaction_specific_stage(ready: dict[str, Any]) -> None:
    candidate = ready["root"] / "elsewhere"
    candidate.mkdir()
    ready["installed"].stage_root = candidate
    with pytest.raises(PlanCandidateIntentError, match="not isolated"):
        run(ready)
    assert ready["commands"] == []


def test_native_signer_refusal_never_writes(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(*args: Any, **kwargs: Any) -> None:
        raise module.NativeEvidenceError("signature invalid")

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", deny)
    with pytest.raises(PlanCandidateIntentError, match="could not be journaled"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


def test_signed_envelope_payload_mismatch_refuses(ready: dict[str, Any]) -> None:
    ready["request"].payload = b"forged"
    with pytest.raises(PlanCandidateIntentError, match="differs from request"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


def test_unsigned_request_must_be_recomputed(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    different = SimpleNamespace(payload=b"tampered")
    monkeypatch.setattr(
        module,
        "prepare_unsigned_native_evidence_request",
        lambda *a, **k: different,
    )
    with pytest.raises(PlanCandidateIntentError, match="changed from physical"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


def test_signed_native_revision_and_dates_only_from_verified_payload(
    ready: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready["signed"].revision = 5

    def revision_check(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["revision"] == 5
        return SimpleNamespace(payload=b"not the signed request")

    monkeypatch.setattr(
        module, "prepare_unsigned_native_evidence_request", revision_check
    )
    with pytest.raises(PlanCandidateIntentError, match="changed from physical"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


@pytest.mark.parametrize(
    "attribute",
    [
        "transaction_id",
        "baseline_transaction_id",
        "baseline_witness_revision",
        "registry_payload_sha256",
        "signed_lock_payload_sha256",
        "pip_inventory_sha256",
        "native_payload_sha256",
        "prepared_record_sha256",
        "status",
        "authority",
    ],
)
def test_staged_plan_mismatch_refuses_journal(
    ready: dict[str, Any],
    attribute: str,
) -> None:
    setattr(ready["observed"], attribute, "different")
    with pytest.raises(PlanCandidateIntentError, match="does not match plan"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


def test_native_signed_envelope_duplicate_key_refuses(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ready["args"]["native_envelope"] = (
        b'{"envelope_version":1,"envelope_version":1,"payload_b64":"a","signatures":[]}'
    )
    monkeypatch.setattr(
        module,
        "verify_signed_staged_native_evidence",
        lambda *args, **kwargs: ready["signed"],
    )
    with pytest.raises(PlanCandidateIntentError, match="duplicate signed evidence"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


def test_wrong_journal_phase_requires_reconciliation(ready: dict[str, Any]) -> None:
    ready["journal"].phase = module.UpdatePhase.ACTIVATION_INTENT
    with pytest.raises(PlanCandidateIntentError, match="needs reconciliation"):
        run(ready)
    assert "persist-journal" in ready["commands"]
    assert ready["state"]["journal"] is ready["journal"]


def test_wrong_persisted_receipt_expectation_refuses(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanCandidateIntentError, match="needs reconciliation"):
        run(ready, previous_receipt_sha256="9" * 64)
    assert "persist-journal" in ready["commands"]


def test_rejected_staged_plan_refuses_without_persisting(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise module.PlanStagedCandidateError("stage drift")

    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", refuse)
    with pytest.raises(PlanCandidateIntentError, match="could not be journaled"):
        run(ready)
    assert "persist-journal" not in ready["commands"]


def test_journal_write_failure_never_claims_success(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise module.UpdateJournalError("locked")

    monkeypatch.setattr(module, "begin_verified_update_intent", refuse)
    with pytest.raises(PlanCandidateIntentError, match="could not be journaled"):
        run(ready)
    assert ready["state"]["journal"] is None


def test_signed_envelope_revision_rollbacks_are_refused_by_signer_not_repaired(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def rollback(*args: Any, **kwargs: Any) -> None:
        raise module.NativeEvidenceError("native revision rollback")

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", rollback)
    with pytest.raises(PlanCandidateIntentError):
        run(ready)
    assert "persist-journal" not in ready["commands"]
