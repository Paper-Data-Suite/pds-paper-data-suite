"""Slice 71: a plan may arm only witnessed recovery-bound intent, never switch."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import paper_data_suite.evergreen_plan_activation_intent as module
from paper_data_suite.evergreen_plan_activation_intent import (
    PlanActivationIntentError,
    arm_plan_bound_witness_activation_intent,
)
from paper_data_suite.evergreen_plan_staged_candidate import PlanStagedCandidateError
from paper_data_suite.evergreen_update_journal import UpdatePhase
from paper_data_suite.evergreen_witness_activation_intent import (
    WitnessActivationIntentError,
)

NOW = datetime(2026, 10, 25, 23, tzinfo=UTC)
TX = "a" * 32
OLD = "b" * 32
CONSENT = "ARM_PLAN_WITNESS_ACTIVATION_INTENT_NO_SWITCH"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "software"
    classroom = tmp_path / "classroom"
    stage = root / "candidate-builds" / TX
    wheels = root / "wheelhouse"
    stage.mkdir(parents=True)
    wheels.mkdir()
    classroom.mkdir()
    classroom_data = classroom / "student-work.txt"
    classroom_data.write_text("NEVER ALTER")
    prior_observation = b"independently inspected previous installation"
    receipt_bytes = b"previous selected receipt bytes"
    evidence = (b"prepared", b"signed-registry", b"signed-lock", b"native-envelope")
    installed = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        prepared_record=evidence[0],
        signed_lock_payload_sha256="d" * 64,
        pip_inventory_sha256="e" * 64,
        baseline_transaction_id=OLD,
        baseline_witness_revision=8,
    )
    recorded = SimpleNamespace(
        transaction_id=TX,
        journal_revision=1,
        native_payload_sha256="f" * 64,
        pip_inventory_sha256="e" * 64,
        baseline_transaction_id=OLD,
        baseline_witness_revision=8,
    )
    witnessed = SimpleNamespace(
        transaction_id=OLD,
        generation=3,
        witness_revision=8,
        receipt_sha256=sha(receipt_bytes),
    )
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256="c" * 64))
    prior = SimpleNamespace(
        observation_record=prior_observation,
        wheelhouse=root / "prior-wheelhouse",
        prepared_record=b"old-prepared",
        registry_envelope=b"old-registry",
        lock_envelope=b"old-lock",
        native_envelope=b"old-native",
    )
    journal = SimpleNamespace(
        transaction_id=TX,
        phase=UpdatePhase.CANDIDATE_VERIFIED,
        revision=1,
        stage_relative_path="candidate-builds/" + TX,
        wheelhouse_relative_path="wheelhouse",
        prepared_sha256=sha(evidence[0]),
        registry_envelope_sha256=sha(evidence[1]),
        lock_envelope_sha256=sha(evidence[2]),
        native_envelope_sha256=sha(evidence[3]),
        expected_previous_receipt_sha256=sha(prior_observation),
    )
    verified_stage = SimpleNamespace(
        transaction_id=TX,
        baseline_transaction_id=OLD,
        baseline_witness_revision=8,
        registry_payload_sha256="c" * 64,
        signed_lock_payload_sha256="d" * 64,
        pip_inventory_sha256="e" * 64,
        native_payload_sha256="f" * 64,
        prepared_record_sha256=sha(evidence[0]),
        status="PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE",
        authority="NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY",
    )
    actions: list[str] = []
    state: dict[str, Any] = {"journal": journal}

    def current(*args: Any, **kwargs: Any) -> Any:
        actions.append("read-journal")
        assert args == (root,)
        assert kwargs["transaction_id"] == TX
        return state["journal"]

    def stage_check(*args: Any, **kwargs: Any) -> Any:
        actions.append("inspect-plan-stage")
        assert args == (snapshot, witnessed, root)
        assert kwargs["stage_root"] == stage
        assert kwargs["wheelhouse"] == wheels
        assert kwargs["module_envelopes"] == {"quillan": b"signed-publisher"}
        return verified_stage

    def arm(*args: Any, **kwargs: Any) -> Any:
        actions.append("witness-arm-under-lock")
        assert args == (root,)
        assert kwargs["expected_revision"] == 1
        assert kwargs["candidate"].prepared_record == evidence[0]
        assert kwargs["candidate"].native_envelope == evidence[3]
        assert kwargs["candidate_module_envelopes"] == {"quillan": b"signed-publisher"}
        assert kwargs["prior"] is prior
        assert kwargs["previous_receipt_bytes"] == receipt_bytes
        assert kwargs["minimum_witness_revision"] == 8
        assert kwargs["installation_id"] == "c" * 32
        state["journal"] = SimpleNamespace(
            **{**vars(journal), "phase": UpdatePhase.ACTIVATION_INTENT, "revision": 2}
        )
        return SimpleNamespace(
            transaction_id=TX,
            journal_revision=2,
            previous_generation=3,
            proposed_generation=4,
            witness_revision=9,
            previous_receipt_sha256=sha(receipt_bytes),
            candidate_pip_inventory_sha256="e" * 64,
        )

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "IsolatedPlanStageResult", SimpleNamespace)
    monkeypatch.setattr(module, "RecordedPlanCandidateIntent", SimpleNamespace)
    monkeypatch.setattr(module, "ClaimedPriorEvidence", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "load_update_intent", current)
    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", stage_check)
    monkeypatch.setattr(module, "arm_witness_bound_activation_intent", arm)
    args = dict(
        snapshot=snapshot,
        witnessed=witnessed,
        installed=installed,
        recorded=recorded,
        software_root=root,
        classroom_workspace=classroom,
        wheelhouse=wheels,
        requested_targets={"quillan": "0.10.0"},
        python_minor="3.11",
        platform_tag="win_arm64",
        registry_envelope=evidence[1],
        lock_envelope=evidence[2],
        module_envelopes={"quillan": b"signed-publisher"},
        native_envelope=evidence[3],
        prior=prior,
        prior_module_envelopes={"core": b"prior-publisher"},
        previous_receipt_bytes=receipt_bytes,
        witness_transport=lambda *a, **k: None,
        installation_id="c" * 32,
        pinned_public_key=b"K" * 32,
        expected_witness_id="independent-witness",
        trust=SimpleNamespace(),
        now=NOW,
        explicit_consent=CONSENT,
    )
    return dict(
        args=args,
        actions=actions,
        state=state,
        journal=journal,
        stage=verified_stage,
        recorded=recorded,
        installed=installed,
        witnessed=witnessed,
        prior=prior,
        root=root,
        classroom_data=classroom_data,
        receipt_bytes=receipt_bytes,
    )


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return arm_plan_bound_witness_activation_intent(**{**ready["args"], **changes})


def test_signed_plan_can_arm_only_inert_witnessed_intent(ready: dict[str, Any]) -> None:
    with patch("subprocess.run", side_effect=AssertionError("never execute")):
        result = run(ready)
    assert result.transaction_id == TX
    assert result.journal_revision == 2
    assert result.prior_generation == 3
    assert result.proposed_generation == 4
    assert result.witness_revision == 9
    assert result.previous_receipt_sha256 == sha(ready["receipt_bytes"])
    assert result.native_payload_sha256 == "f" * 64
    assert "NO_SELECTION_CAS" in result.authority
    assert ready["actions"] == [
        "read-journal",
        "inspect-plan-stage",
        "witness-arm-under-lock",
        "read-journal",
    ]
    assert ready["state"]["journal"].phase is UpdatePhase.ACTIVATION_INTENT
    assert ready["classroom_data"].read_text() == "NEVER ALTER"
    assert not (ready["root"] / "candidate-selection.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"explicit_consent": ""},
        {"explicit_consent": "yes"},
        {"installed": None},
        {"recorded": None},
        {"witnessed": None},
        {"prior": None},
        {"trust": None},
        {"installation_id": "not-an-id"},
        {"pinned_public_key": b"wrong"},
        {"native_envelope": "not bytes"},
        {"previous_receipt_bytes": b""},
        {"module_envelopes": {"quillan": "not bytes"}},
        {"now": datetime(2026, 10, 25)},
        {"now": NOW.replace(microsecond=42)},
        {"witness_transport": None},
    ],
)
def test_invalid_requests_refuse_before_journal_read(
    ready: dict[str, Any], changes: dict[str, Any]
) -> None:
    with pytest.raises(PlanActivationIntentError):
        run(ready, **changes)
    assert ready["actions"] == []


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("baseline_transaction_id", "9" * 32),
        ("baseline_witness_revision", 99),
        ("journal_revision", 2),
        ("native_payload_sha256", "x" * 64),
        ("pip_inventory_sha256", "0" * 64),
    ],
)
def test_changed_recorded_candidate_refuses_without_journal_read(
    ready: dict[str, Any], field: str, wrong: Any
) -> None:
    forged = SimpleNamespace(**{**vars(ready["recorded"]), field: wrong})
    with pytest.raises(PlanActivationIntentError):
        run(ready, recorded=forged)
    assert ready["actions"] == []


def test_previous_active_receipt_must_match_witness_baseline(
    ready: dict[str, Any],
) -> None:
    with pytest.raises(PlanActivationIntentError, match="baseline|receipt"):
        run(ready, previous_receipt_bytes=b"different signed receipt")
    assert ready["actions"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"phase": UpdatePhase.ACTIVATION_INTENT},
        {"expected_previous_receipt_sha256": None},
        {"prepared_sha256": "0" * 64},
        {"native_envelope_sha256": "1" * 64},
        {"wheelhouse_relative_path": "wrong"},
        {"revision": 9},
    ],
)
def test_wrong_or_replayed_journal_refuses_before_witness_query(
    ready: dict[str, Any], change: dict[str, Any]
) -> None:
    ready["state"]["journal"] = SimpleNamespace(**{**vars(ready["journal"]), **change})
    with pytest.raises(PlanActivationIntentError, match="journal"):
        run(ready)
    assert ready["actions"] == ["read-journal"]


def test_signed_plan_auditor_failure_refuses_without_arming(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def rejected(*args: Any, **kwargs: Any) -> Any:
        raise PlanStagedCandidateError("native bytes were changed")

    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", rejected)
    with pytest.raises(PlanActivationIntentError, match="refused"):
        run(ready)
    assert ready["actions"] == ["read-journal"]


@pytest.mark.parametrize(
    "attribute",
    [
        "native_payload_sha256",
        "signed_lock_payload_sha256",
        "pip_inventory_sha256",
        "prepared_record_sha256",
        "status",
        "authority",
    ],
)
def test_changed_stage_observation_refuses_before_witness(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, attribute: str
) -> None:
    stage = ready["stage"]
    wrong = "0" * 64 if attribute not in ("status", "authority") else "forged"
    changed = SimpleNamespace(**{**vars(stage), attribute: wrong})
    monkeypatch.setattr(
        module, "inspect_plan_bound_staged_candidate", lambda *a, **kw: changed
    )
    with pytest.raises(PlanActivationIntentError, match="stage|candidate"):
        run(ready)
    assert "witness-arm-under-lock" not in ready["actions"]


def test_external_witness_refusal_leaves_journal_unarmed(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def rejected(*args: Any, **kwargs: Any) -> Any:
        raise WitnessActivationIntentError("remote predecessor changed")

    monkeypatch.setattr(module, "arm_witness_bound_activation_intent", rejected)
    with pytest.raises(PlanActivationIntentError, match="refused"):
        run(ready)
    assert ready["state"]["journal"].phase is UpdatePhase.CANDIDATE_VERIFIED
    assert ready["actions"] == ["read-journal", "inspect-plan-stage"]


def test_postwrite_mismatch_requires_recovery_never_automatic_undo(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def ambiguous(*args: Any, **kwargs: Any) -> Any:
        current = ready["journal"]
        ready["state"]["journal"] = SimpleNamespace(
            **{**vars(current), "phase": UpdatePhase.ACTIVATION_INTENT, "revision": 2}
        )
        return SimpleNamespace(
            transaction_id=TX,
            journal_revision=2,
            previous_generation=3,
            proposed_generation=4,
            witness_revision=9,
            previous_receipt_sha256=sha(ready["receipt_bytes"]),
            candidate_pip_inventory_sha256="9" * 64,
        )

    monkeypatch.setattr(module, "arm_witness_bound_activation_intent", ambiguous)
    with pytest.raises(PlanActivationIntentError, match="reconciliation"):
        run(ready)
    assert ready["state"]["journal"].phase is UpdatePhase.ACTIVATION_INTENT


def test_missing_prior_observation_prevents_arming(ready: dict[str, Any]) -> None:
    changed_prior = SimpleNamespace(
        **{**vars(ready["prior"]), "observation_record": b"wrong"}
    )
    with pytest.raises(PlanActivationIntentError, match="prior binding"):
        run(ready, prior=changed_prior)
    assert ready["actions"] == ["read-journal"]


def test_candidate_and_wheelhouse_cannot_overlap(ready: dict[str, Any]) -> None:
    with pytest.raises(PlanActivationIntentError):
        run(ready, wheelhouse=ready["installed"].stage_root)
    assert "witness-arm-under-lock" not in ready["actions"]


def test_arming_replay_refuses_without_second_witness_call(
    ready: dict[str, Any],
) -> None:
    run(ready)
    first = ready["actions"].count("witness-arm-under-lock")
    with pytest.raises(PlanActivationIntentError, match="journal"):
        run(ready)
    assert ready["actions"].count("witness-arm-under-lock") == first == 1
