"""Slice 73: plan-bound successor draft; no service commit or local mutation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import paper_data_suite.evergreen_plan_successor_draft as module
from paper_data_suite.evergreen_plan_successor_draft import (
    PlanSuccessorDraftError,
    draft_plan_bound_successor_commit_request,
)

NOW = datetime(2026, 10, 26, 22, tzinfo=UTC)
TX = "a" * 32
INSTALL = "b" * 32
PRIOR = "c" * 32
CONSENT = "DRAFT_PLAN_WITNESS_SUCCESSOR_FOR_INDEPENDENT_REVIEW"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root, classroom = tmp_path / "software", tmp_path / "classroom"
    wheels = root / "wheelhouse"
    stage = root / "candidate-builds" / TX
    stage.mkdir(parents=True)
    wheels.mkdir()
    classroom.mkdir()
    (classroom / "student.txt").write_text("untouched")
    prev = b"prior receipt bytes"
    current = b"new successor receipt bytes"
    pointer_raw = b"candidate pointer bytes"
    former = b"previous pointer bytes"
    prepared, registry, lock, native = b"prepared", b"registry", b"lock", b"native"
    prior_observation = b"prior observation"
    pending = SimpleNamespace(
        transaction_id=TX,
        previous_bytes=former,
        previous_sha256=sha(former),
        candidate_sha256=sha(pointer_raw),
    )
    pointer = SimpleNamespace(
        transaction_id=TX,
        generation=8,
        stage_relative_path=f"candidate-builds/{TX}",
        prepared_sha256=sha(prepared),
        native_envelope_sha256=sha(native),
    )
    journal = SimpleNamespace(
        transaction_id=TX,
        phase=None,
        revision=2,
        stage_relative_path=f"candidate-builds/{TX}",
        wheelhouse_relative_path="wheelhouse",
        prepared_sha256=sha(prepared),
        registry_envelope_sha256=sha(registry),
        lock_envelope_sha256=sha(lock),
        native_envelope_sha256=sha(native),
        expected_previous_receipt_sha256=sha(prior_observation),
    )
    installed = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        prepared_record=prepared,
        baseline_transaction_id=PRIOR,
        baseline_witness_revision=6,
        pip_inventory_sha256="d" * 64,
        signed_lock_payload_sha256="e" * 64,
    )
    witness = SimpleNamespace(
        transaction_id=PRIOR,
        witness_revision=6,
        generation=7,
        receipt_sha256=sha(prev),
    )
    armed = SimpleNamespace(
        transaction_id=TX,
        journal_revision=2,
        prior_generation=7,
        proposed_generation=8,
        witness_revision=6,
        previous_receipt_sha256=sha(prev),
        native_payload_sha256="f" * 64,
        pip_inventory_sha256="d" * 64,
    )
    selected = SimpleNamespace(
        transaction_id=TX,
        journal_revision=2,
        predecessor_generation=7,
        selected_generation=8,
        witness_revision=6,
        predecessor_receipt_sha256=sha(prev),
        candidate_stage_relative_path=f"candidate-builds/{TX}",
    )
    recorded = SimpleNamespace(
        transaction_id=TX,
        journal_revision=1,
        baseline_transaction_id=PRIOR,
        baseline_witness_revision=6,
        pip_inventory_sha256="d" * 64,
        native_payload_sha256="f" * 64,
    )
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256="1" * 64))
    prior = SimpleNamespace(observation_record=prior_observation)
    observed = SimpleNamespace(
        transaction_id=TX,
        baseline_transaction_id=PRIOR,
        baseline_witness_revision=6,
        registry_payload_sha256="1" * 64,
        signed_lock_payload_sha256="e" * 64,
        pip_inventory_sha256="d" * 64,
        native_payload_sha256="f" * 64,
        prepared_record_sha256=sha(prepared),
        status="PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE",
        authority="NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY",
    )
    draft = SimpleNamespace(
        transaction_id=TX,
        previous_generation=7,
        proposed_generation=8,
        previous_receipt_sha256=sha(prev),
        expected_witness_revision=7,
        proposed_receipt_sha256=sha(current),
        receipt_bytes=current,
        status="DRAFT_ONLY_CHECKPOINT_NOT_COMMITTED_RECOVERY_STILL_PENDING",
    )
    receipt = SimpleNamespace(
        transaction_id=TX,
        generation=8,
        stage_relative_path=f"candidate-builds/{TX}",
        wheelhouse_relative_path="wheelhouse",
        prepared_sha256=sha(prepared),
        registry_sha256=sha(registry),
        lock_sha256=sha(lock),
        native_envelope_sha256=sha(native),
        native_payload_sha256="f" * 64,
        pip_inventory_sha256="d" * 64,
        previous_receipt_sha256=sha(prev),
    )
    request = SimpleNamespace(
        installation_id=INSTALL,
        witness_id="independent-witness",
        expected_witness_revision=7,
        predecessor_sha256=sha(prev),
        successor_sha256=sha(current),
    )
    state: dict[str, Any] = dict(
        journal=journal,
        pending=pending,
        pointer=pointer,
        pointer_raw=pointer_raw,
        observed=observed,
        draft=draft,
        receipt=receipt,
        request=request,
    )
    calls: list[str] = []

    def journal_read(*args: Any, **kwargs: Any) -> Any:
        calls.append("journal")
        return state["journal"]

    def pending_read(*args: Any, **kwargs: Any) -> Any:
        calls.append("pending")
        return state["pending"]

    def pointer_read(*args: Any, **kwargs: Any) -> bytes:
        calls.append("pointer")
        return state["pointer_raw"]

    def observe(*args: Any, **kwargs: Any) -> Any:
        calls.append("plan-audit")
        assert args == (snapshot, witness, root)
        assert kwargs["native_envelope"] == native
        return state["observed"]

    def draft_receipt(*args: Any, **kwargs: Any) -> Any:
        calls.append("double-audit-witness-draft")
        assert args == (root,)
        assert kwargs["minimum_witness_revision"] == selected.witness_revision
        return state["draft"]

    def make_request(*args: Any, **kwargs: Any) -> Any:
        calls.append("untrusted-commit-proposal")
        assert args == (state["draft"],)
        assert kwargs["previous_receipt_bytes"] == prev
        return state["request"]

    def serialize(request_arg: Any) -> bytes:
        calls.append("serialize-untrusted-proposal")
        assert request_arg is state["request"]
        return b"canonical request bytes"

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "IsolatedPlanStageResult", SimpleNamespace)
    monkeypatch.setattr(module, "RecordedPlanCandidateIntent", SimpleNamespace)
    monkeypatch.setattr(module, "PlanWitnessActivationIntent", SimpleNamespace)
    monkeypatch.setattr(module, "PlanPendingInertSelection", SimpleNamespace)
    monkeypatch.setattr(module, "ClaimedPriorEvidence", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "_safe_root", lambda *a: root)
    monkeypatch.setattr(
        module, "_relative_child", lambda r, p: p.relative_to(r).as_posix()
    )
    monkeypatch.setattr(module, "load_update_intent", journal_read)
    monkeypatch.setattr(module, "read_pending_slot_recovery", pending_read)
    monkeypatch.setattr(
        module,
        "_paths",
        lambda *a: (root, root / "selection.json", root / "recovery.json"),
    )
    monkeypatch.setattr(module, "_read", pointer_read)
    monkeypatch.setattr(module, "_parse_selection", lambda raw: state["pointer"])
    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", observe)
    monkeypatch.setattr(module, "draft_witness_bound_successor_receipt", draft_receipt)
    monkeypatch.setattr(
        module, "parse_untrusted_active_receipt", lambda raw: state["receipt"]
    )
    monkeypatch.setattr(module, "make_witness_commit_request", make_request)
    monkeypatch.setattr(module, "serialize_witness_commit_request", serialize)
    monkeypatch.setattr(
        module, "UpdatePhase", SimpleNamespace(ACTIVATION_INTENT=object())
    )
    journal.phase = module.UpdatePhase.ACTIVATION_INTENT
    args = dict(
        snapshot=snapshot,
        witnessed=witness,
        installed=installed,
        recorded=recorded,
        armed=armed,
        selected=selected,
        software_root=root,
        classroom_workspace=classroom,
        wheelhouse=wheels,
        requested_targets={"quillan": "0.10.0"},
        python_minor="3.12",
        platform_tag="win-arm64",
        registry_envelope=registry,
        lock_envelope=lock,
        module_envelopes={"core": b"module"},
        native_envelope=native,
        prior=prior,
        prior_module_envelopes={"core": b"old module"},
        previous_receipt_bytes=prev,
        witness_transport=lambda *a: None,
        installation_id=INSTALL,
        pinned_public_key=b"p" * 32,
        expected_witness_id="independent-witness",
        trust=SimpleNamespace(),
        now=NOW,
        explicit_consent=CONSENT,
    )
    return dict(
        args=args,
        calls=calls,
        state=state,
        root=root,
        classroom=classroom,
        installed=installed,
        witness=witness,
        selected=selected,
        armed=armed,
        recorded=recorded,
    )


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return draft_plan_bound_successor_commit_request(**{**ready["args"], **changes})


def test_positive_review_never_commits_or_writes(ready: dict[str, Any]) -> None:
    before = (ready["classroom"] / "student.txt").read_bytes()
    output = run(ready)
    assert output.transaction_id == TX
    assert output.request_sha256 == sha(b"canonical request bytes")
    assert output.serialized_request == b"canonical request bytes"
    assert output.proposed_generation == 8
    assert output.witness_revision == 7
    assert "UNSUBMITTED" in output.status
    assert "NO_CAS" in output.authority
    assert ready["calls"] == [
        "journal",
        "pending",
        "pointer",
        "plan-audit",
        "double-audit-witness-draft",
        "untrusted-commit-proposal",
        "serialize-untrusted-proposal",
        "journal",
        "pending",
        "pointer",
    ]
    assert (ready["classroom"] / "student.txt").read_bytes() == before
    assert list(ready["root"].glob("**/*.json")) == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("explicit_consent", ""),
        ("explicit_consent", "yes"),
        ("installation_id", "wrong"),
        ("pinned_public_key", b"bad"),
        ("native_envelope", "not bytes"),
        ("module_envelopes", {}),
        ("prior_module_envelopes", {"core": "bad"}),
        ("previous_receipt_bytes", b""),
        ("now", datetime(2026, 10, 26)),
        ("now", datetime(2026, 10, 26, 22, 0, 0, 1, tzinfo=UTC)),
        ("layout", "android"),
        ("trust", None),
    ],
)
def test_invalid_inputs_fail_before_observation(
    ready: dict[str, Any], key: str, value: Any
) -> None:
    with pytest.raises(PlanSuccessorDraftError, match="inputs"):
        run(ready, **{key: value})
    assert ready["calls"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("journal_revision", 3),
        ("selected_generation", 9),
        ("predecessor_generation", 6),
        ("predecessor_receipt_sha256", "0" * 64),
        ("candidate_stage_relative_path", "other"),
    ],
)
def test_mismatched_selection_refused(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    setattr(ready["selected"], field, value)
    with pytest.raises(PlanSuccessorDraftError):
        run(ready)
    assert "double-audit-witness-draft" not in ready["calls"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("prior_generation", 6),
        ("proposed_generation", 9),
        ("witness_revision", 99),
        ("native_payload_sha256", "0" * 64),
    ],
)
def test_armed_drift_refused(ready: dict[str, Any], field: str, value: Any) -> None:
    setattr(ready["armed"], field, value)
    with pytest.raises(PlanSuccessorDraftError):
        run(ready)
    assert ready["calls"] == []


def test_missing_recovery_capsule_blocks_draft(ready: dict[str, Any]) -> None:
    ready["state"]["pending"] = None
    with pytest.raises(PlanSuccessorDraftError, match="recovery-pending"):
        run(ready)
    assert "plan-audit" not in ready["calls"]


def test_changed_pending_pointer_hash_blocks_draft(ready: dict[str, Any]) -> None:
    ready["state"]["pending"].candidate_sha256 = "0" * 64
    with pytest.raises(PlanSuccessorDraftError, match="recovery-pending"):
        run(ready)


def test_changed_plan_audit_blocks_draft(ready: dict[str, Any]) -> None:
    ready["state"]["observed"].native_payload_sha256 = "0" * 64
    with pytest.raises(PlanSuccessorDraftError, match="candidate"):
        run(ready)
    assert "double-audit-witness-draft" not in ready["calls"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("previous_generation", 6),
        ("expected_witness_revision", 5),
        ("proposed_receipt_sha256", "0" * 64),
    ],
)
def test_draft_mismatch_blocks_request(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    setattr(ready["state"]["draft"], field, value)
    with pytest.raises(PlanSuccessorDraftError, match="draft"):
        run(ready)
    assert "untrusted-commit-proposal" not in ready["calls"]


def test_receipt_wrong_native_blocks_request(ready: dict[str, Any]) -> None:
    ready["state"]["receipt"].native_payload_sha256 = "0" * 64
    with pytest.raises(PlanSuccessorDraftError, match="receipt"):
        run(ready)


def test_request_wrong_predecessor_refused(ready: dict[str, Any]) -> None:
    ready["state"]["request"].predecessor_sha256 = "0" * 64
    with pytest.raises(PlanSuccessorDraftError, match="handoff"):
        run(ready)


def test_changed_journal_after_draft_refused(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = module.load_update_intent
    count = 0

    def changed(*args: Any, **kwargs: Any) -> Any:
        nonlocal count
        count += 1
        row = original(*args, **kwargs)
        return SimpleNamespace(revision=3) if count == 2 else row

    monkeypatch.setattr(module, "load_update_intent", changed)
    with pytest.raises(PlanSuccessorDraftError, match="handoff"):
        run(ready)


def test_external_drafter_refusal_is_wrapped(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise module.SuccessorReceiptDraftError("remote unavailable")

    monkeypatch.setattr(module, "draft_witness_bound_successor_receipt", refuse)
    with pytest.raises(PlanSuccessorDraftError, match="review refused"):
        run(ready)
    assert "untrusted-commit-proposal" not in ready["calls"]
