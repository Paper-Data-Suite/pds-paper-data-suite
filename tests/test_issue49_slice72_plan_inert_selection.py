"""Slice 72: witnessed plan selects only inert pointer with recovery capsule."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import paper_data_suite.evergreen_plan_inert_selection as module
from paper_data_suite.evergreen_plan_inert_selection import (
    PlanInertSelectionError,
    select_plan_bound_witness_inert_slot,
)
from paper_data_suite.evergreen_plan_staged_candidate import PlanStagedCandidateError
from paper_data_suite.evergreen_update_journal import UpdatePhase
from paper_data_suite.evergreen_witness_slot_transition import (
    WitnessSlotTransitionError,
)

TX = "a" * 32
OLD = "b" * 32
PIN = "z" * 32
NOW = datetime(2026, 10, 26, 4, tzinfo=UTC)
CONSENT = "SELECT_WITNESSED_PLAN_INERT_SLOT_PENDING_RECOVERY"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "software"
    classroom = tmp_path / "classroom"
    stage = root / "candidate-builds" / TX
    wheels = root / "signed-wheels"
    stage.mkdir(parents=True)
    wheels.mkdir()
    classroom.mkdir()
    (classroom / "classroom.txt").write_text("untouched", encoding="utf-8")
    pointer_path = root / "candidate-selection.json"
    snapshot = SimpleNamespace(registry=SimpleNamespace(payload_sha256="c" * 64))
    old_receipt = b"previous signed receipt"
    witnessed = SimpleNamespace(
        transaction_id=OLD,
        generation=3,
        witness_revision=7,
        receipt_sha256=sha(old_receipt),
    )
    installed = SimpleNamespace(
        transaction_id=TX,
        stage_root=stage,
        prepared_record=b"prepared",
        signed_lock_payload_sha256="d" * 64,
        pip_inventory_sha256="e" * 64,
        baseline_transaction_id=OLD,
        baseline_witness_revision=7,
    )
    recorded = SimpleNamespace(
        transaction_id=TX,
        journal_revision=1,
        native_payload_sha256="f" * 64,
        pip_inventory_sha256="e" * 64,
        baseline_transaction_id=OLD,
        baseline_witness_revision=7,
    )
    armed = SimpleNamespace(
        transaction_id=TX,
        journal_revision=2,
        prior_generation=3,
        proposed_generation=4,
        witness_revision=9,
        previous_receipt_sha256=sha(old_receipt),
        native_payload_sha256="f" * 64,
        pip_inventory_sha256="e" * 64,
    )
    prior = SimpleNamespace(observation_record=b"prior physical observation")
    journal = SimpleNamespace(
        transaction_id=TX,
        phase=UpdatePhase.ACTIVATION_INTENT,
        revision=2,
        stage_relative_path=f"candidate-builds/{TX}",
        wheelhouse_relative_path="signed-wheels",
        prepared_sha256=sha(b"prepared"),
        registry_envelope_sha256=sha(b"registry"),
        lock_envelope_sha256=sha(b"lock"),
        native_envelope_sha256=sha(b"native"),
        expected_previous_receipt_sha256=sha(prior.observation_record),
    )
    observed = SimpleNamespace(
        transaction_id=TX,
        baseline_transaction_id=OLD,
        baseline_witness_revision=7,
        registry_payload_sha256="c" * 64,
        signed_lock_payload_sha256="d" * 64,
        pip_inventory_sha256="e" * 64,
        native_payload_sha256="f" * 64,
        prepared_record_sha256=sha(b"prepared"),
        status="PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE",
        authority="NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY",
    )
    selection = SimpleNamespace(
        transaction_id=TX,
        stage_relative_path=f"candidate-builds/{TX}",
        prepared_sha256=journal.prepared_sha256,
        native_envelope_sha256=journal.native_envelope_sha256,
        generation=4,
    )
    pointer_bytes = b"canonical inert pointer bytes"
    pending = SimpleNamespace(
        transaction_id=TX,
        previous_bytes=b"previous pointer bytes",
        candidate_sha256=sha(pointer_bytes),
    )
    selected = SimpleNamespace(
        transaction_id=TX,
        previous_generation=3,
        selected_generation=4,
        witness_revision=10,
        previous_receipt_sha256=sha(old_receipt),
        selected_stage=f"candidate-builds/{TX}",
        status="INERT_SELECTION_PENDING_EXPLICIT_RECOVERY",
    )
    state: dict[str, Any] = {
        "selected": False,
        "pointer": pointer_bytes,
        "pending": pending,
    }
    calls: list[str] = []

    def check_plan(*args: Any, **kwargs: Any) -> Any:
        calls.append("plan-audit")
        assert args == (snapshot, witnessed, root)
        assert kwargs["stage_root"] == stage
        return observed

    def switch(*args: Any, **kwargs: Any) -> Any:
        calls.append("witness-locked-selector")
        assert args == (root,)
        assert kwargs["expected_revision"] == 2
        assert kwargs["minimum_witness_revision"] == 9
        assert kwargs["candidate"].prepared_record == b"prepared"
        assert kwargs["previous_receipt_bytes"] == old_receipt
        state["selected"] = True
        return selected

    def read_pending(*args: Any, **kwargs: Any) -> Any:
        calls.append("pending-capsule")
        return state["pending"] if state["selected"] else None

    def read_pointer(path: Path) -> bytes | None:
        calls.append("read-pointer")
        assert path == pointer_path
        return state["pointer"]

    monkeypatch.setattr(module, "CatalogSnapshot", SimpleNamespace)
    monkeypatch.setattr(module, "WitnessSelectedStageObservation", SimpleNamespace)
    monkeypatch.setattr(module, "IsolatedPlanStageResult", SimpleNamespace)
    monkeypatch.setattr(module, "RecordedPlanCandidateIntent", SimpleNamespace)
    monkeypatch.setattr(module, "PlanWitnessActivationIntent", SimpleNamespace)
    monkeypatch.setattr(module, "ClaimedPriorEvidence", SimpleNamespace)
    monkeypatch.setattr(module, "TrustedKeyring", SimpleNamespace)
    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", check_plan)
    monkeypatch.setattr(module, "select_witness_bound_candidate_slot", switch)
    monkeypatch.setattr(module, "read_pending_slot_recovery", read_pending)
    monkeypatch.setattr(module, "load_update_intent", lambda *a, **k: journal)
    monkeypatch.setattr(
        module, "_paths", lambda *a, **k: (root, pointer_path, root / "recovery")
    )
    monkeypatch.setattr(module, "_read", read_pointer)
    monkeypatch.setattr(module, "_parse_selection", lambda raw: selection)
    return {
        "args": {
            "snapshot": snapshot,
            "witnessed": witnessed,
            "installed": installed,
            "recorded": recorded,
            "armed": armed,
            "software_root": root,
            "classroom_workspace": classroom,
            "wheelhouse": wheels,
            "requested_targets": {"quillan": "0.10.0"},
            "python_minor": "3.11",
            "platform_tag": "win_arm64",
            "registry_envelope": b"registry",
            "lock_envelope": b"lock",
            "module_envelopes": {"quillan": b"publisher"},
            "native_envelope": b"native",
            "prior": prior,
            "prior_module_envelopes": {"core": b"prior-publisher"},
            "previous_receipt_bytes": old_receipt,
            "witness_transport": lambda *a, **k: b"signed witness",
            "installation_id": "c" * 32,
            "pinned_public_key": b"k" * 32,
            "expected_witness_id": "external_witness",
            "trust": SimpleNamespace(),
            "now": NOW,
            "explicit_consent": CONSENT,
        },
        "state": state,
        "journal": journal,
        "observed": observed,
        "selected": selected,
        "selection": selection,
        "armed": armed,
        "recorded": recorded,
        "witnessed": witnessed,
        "installed": installed,
        "calls": calls,
        "root": root,
        "classroom": classroom,
    }


def run(ready: dict[str, Any], **changes: Any) -> Any:
    return select_plan_bound_witness_inert_slot(**{**ready["args"], **changes})


def test_selection_requires_independent_witness_and_preserves_classroom(
    ready: dict[str, Any],
) -> None:
    classroom_file = ready["classroom"] / "classroom.txt"
    before = classroom_file.read_bytes()
    with (
        patch("subprocess.run", side_effect=AssertionError("must not execute")),
        patch("socket.create_connection", side_effect=AssertionError("must not fetch")),
    ):
        result = run(ready)
    assert result.transaction_id == TX
    assert result.journal_revision == 2
    assert result.predecessor_generation == 3
    assert result.selected_generation == 4
    assert result.witness_revision == 10
    assert result.status == "INERT_PLAN_SELECTION_PENDING_PROTECTED_RECONCILIATION"
    assert "NO_EXECUTION" in result.authority
    assert classroom_file.read_bytes() == before
    assert ready["calls"] == [
        "pending-capsule",
        "plan-audit",
        "witness-locked-selector",
        "pending-capsule",
        "read-pointer",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"explicit_consent": None},
        {"explicit_consent": "yes"},
        {"pinned_public_key": b"bad"},
        {"trust": None},
        {"now": datetime(2026, 10, 26)},
        {"now": NOW.replace(microsecond=1)},
        {"layout": "unknown"},
        {"installation_id": "not-hex"},
        {"module_envelopes": {"quillan": "not bytes"}},
        {"prior_module_envelopes": {}},
        {"requested_targets": []},
        {"previous_receipt_bytes": b""},
        {"witness_transport": None},
    ],
)
def test_invalid_inputs_refuse_before_witness_or_read(
    ready: dict[str, Any], changes: dict[str, Any]
) -> None:
    with pytest.raises(PlanInertSelectionError, match="inputs"):
        run(ready, **changes)
    assert ready["calls"] == []


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("journal_revision", 3),
        ("transaction_id", "c" * 32),
        ("prior_generation", 5),
        ("proposed_generation", 12),
        ("witness_revision", 1),
        ("previous_receipt_sha256", "f" * 64),
        ("native_payload_sha256", "1" * 64),
        ("pip_inventory_sha256", "1" * 64),
    ],
)
def test_changed_armed_identity_refuses_before_audit(
    ready: dict[str, Any], attribute: str, value: Any
) -> None:
    current = vars(ready["armed"]).copy()
    current[attribute] = value
    with pytest.raises(PlanInertSelectionError, match="armed"):
        run(ready, armed=SimpleNamespace(**current))
    assert ready["calls"] == []


@pytest.mark.parametrize(
    "field",
    [
        "stage_relative_path",
        "wheelhouse_relative_path",
        "native_envelope_sha256",
        "expected_previous_receipt_sha256",
        "revision",
    ],
)
def test_stale_journal_refuses_without_mutation(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    original = ready["journal"]
    current = vars(original).copy()
    current[field] = 99 if field == "revision" else "wrong"
    monkeypatch.setattr(
        module, "load_update_intent", lambda *a, **k: SimpleNamespace(**current)
    )
    with pytest.raises(PlanInertSelectionError, match="intent"):
        run(ready)
    assert "witness-locked-selector" not in ready["calls"]


def test_pending_capsule_refuses_before_plan_audit(ready: dict[str, Any]) -> None:
    ready["state"]["selected"] = True
    with pytest.raises(PlanInertSelectionError, match="pending"):
        run(ready)
    assert "plan-audit" not in ready["calls"]


def test_plan_audit_refusal_does_not_switch(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*a: Any, **k: Any) -> None:
        raise PlanStagedCandidateError("not authenticated")

    monkeypatch.setattr(module, "inspect_plan_bound_staged_candidate", reject)
    with pytest.raises(PlanInertSelectionError, match="refused"):
        run(ready)
    assert "witness-locked-selector" not in ready["calls"]


def test_changed_native_bytes_refuse_before_selection(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "inspect_plan_bound_staged_candidate",
        lambda *a, **k: SimpleNamespace(
            **{**vars(ready["observed"]), "native_payload_sha256": "1" * 64}
        ),
    )
    with pytest.raises(PlanInertSelectionError, match="candidate"):
        run(ready)
    assert "witness-locked-selector" not in ready["calls"]


def test_external_witness_refusal_never_falls_back(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*a: Any, **k: Any) -> None:
        raise WitnessSlotTransitionError("independent witness unavailable")

    monkeypatch.setattr(module, "select_witness_bound_candidate_slot", reject)
    with pytest.raises(PlanInertSelectionError, match="refused"):
        run(ready)
    assert ready["state"]["selected"] is False


@pytest.mark.parametrize(
    "drift",
    [
        "no-capsule",
        "no-previous-pointer",
        "capsule-digest",
        "selected-transaction",
        "wrong-generation",
        "reported-witness",
        "wrong-selected-stage",
        "pointer-disappeared",
    ],
)
def test_post_selection_discrepancy_requires_explicit_recovery(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    orig = ready["state"]
    if drift == "no-capsule":
        orig["pending"] = None
    elif drift == "no-previous-pointer":
        orig["pending"] = SimpleNamespace(
            **{**vars(orig["pending"]), "previous_bytes": None}
        )
    elif drift == "capsule-digest":
        orig["pending"] = SimpleNamespace(
            **{**vars(orig["pending"]), "candidate_sha256": "0" * 64}
        )
    elif drift == "selected-transaction":
        selected = SimpleNamespace(**{**vars(ready["selected"]), "transaction_id": OLD})
        monkeypatch.setattr(
            module, "select_witness_bound_candidate_slot", lambda *a, **k: selected
        )
    elif drift == "wrong-generation":
        monkeypatch.setattr(
            module,
            "_parse_selection",
            lambda *a: SimpleNamespace(
                **{**vars(ready["selection"]), "generation": 12}
            ),
        )
    elif drift == "reported-witness":
        monkeypatch.setattr(
            module,
            "select_witness_bound_candidate_slot",
            lambda *a, **k: SimpleNamespace(
                **{**vars(ready["selected"]), "witness_revision": 2}
            ),
        )
    elif drift == "wrong-selected-stage":
        monkeypatch.setattr(
            module,
            "_parse_selection",
            lambda *a: SimpleNamespace(
                **{**vars(ready["selection"]), "stage_relative_path": "other"}
            ),
        )
    elif drift == "pointer-disappeared":
        orig["pointer"] = None
    # Simulate that the existing selector performed its persisted writes, then
    # the post-write inspection sees a changed/corrupt local state.
    normal = module.select_witness_bound_candidate_slot

    def written(*args: Any, **kwargs: Any) -> Any:
        orig["selected"] = True
        return normal(*args, **kwargs)

    monkeypatch.setattr(module, "select_witness_bound_candidate_slot", written)
    with pytest.raises(PlanInertSelectionError, match="recovery"):
        run(ready)
    assert orig["selected"] is True


def test_no_implicit_fallback_or_production_launch_import() -> None:
    assert "select_plan_bound_witness_inert_slot" in module.__all__
    assert "launch_application" not in vars(module)
    assert "commit_independently_approved_successor" not in vars(module)
