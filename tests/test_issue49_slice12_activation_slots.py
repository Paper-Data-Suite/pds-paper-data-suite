"""Issue #49 Slice 12: reversible inert selection, never live launcher activation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from test_issue49_slice11_update_journal import Scene

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    UntrustedSlotSelection,
    _selection_bytes,
    read_candidate_selection,
    read_pending_slot_recovery,
    restore_previous_selection,
    switch_verified_candidate_selection,
)
from paper_data_suite.evergreen_update_journal import begin_verified_update_intent


def _arm(scene: Scene) -> None:
    scene.begin()
    scene.arm()


def _switch(scene: Scene):
    return switch_verified_candidate_selection(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=scene.tx,
        prepared_record=scene.prepared,
        registry_envelope=scene.registry,
        lock_envelope=scene.lock,
        evidence_envelope=scene.evidence,
        trust=scene.inputs()["trust"],
        now=scene.inputs()["now"],
        layout=scene.layout,
    )


def _active(scene: Scene):
    return read_candidate_selection(scene.manager, classroom_workspace=scene.workspace)


def _pending(scene: Scene):
    return read_pending_slot_recovery(
        scene.manager, classroom_workspace=scene.workspace
    )


def _restore(scene: Scene):
    return restore_previous_selection(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=scene.tx,
    )


def test_journal_armed_stage_produces_inert_candidate_selection(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    stage_before = {
        path.relative_to(scene.stage): path.read_bytes()
        for path in scene.stage.rglob("*")
        if path.is_file()
    }
    output = _switch(scene)
    assert output.transaction_id == scene.tx
    assert output.generation == 1
    assert not hasattr(output, "can_launch")
    assert not hasattr(output, "trusted_receipt")
    assert _pending(scene) is not None
    with pytest.raises(ActivationSlotError, match="reconciliation"):
        _active(scene)
    assert stage_before == {
        path.relative_to(scene.stage): path.read_bytes()
        for path in scene.stage.rglob("*")
        if path.is_file()
    }
    assert scene.load().phase.value == "activation_intent"


def test_restore_initial_switch_removes_only_selection(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    _switch(scene)
    assert _restore(scene) is None
    assert _active(scene) is None
    assert _pending(scene) is None
    assert scene.stage.is_dir()
    assert scene.wheels.is_dir()
    assert scene.journal.exists()


def test_prepared_candidate_never_switches_without_armed_intent(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    with pytest.raises(ActivationSlotError, match="activation intent"):
        _switch(scene)
    assert not (scene.manager / "candidate-selection.json").exists()


def test_modifying_native_binary_after_intent_refuses_switch(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    interpreter = scene.stage / "Scripts/python.exe"
    interpreter.write_bytes(b"injected")
    with pytest.raises(ActivationSlotError, match="reauthentication"):
        _switch(scene)
    assert _pending(scene) is None


def test_untouched_preexisting_selection_is_saved_exactly(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    old = UntrustedSlotSelection("a" * 32, "old-stage", "a" * 64, "b" * 64, 7)
    pointer = scene.manager / "candidate-selection.json"
    (scene.manager / "old-stage").mkdir()
    old_raw = _selection_bytes(old)
    pointer.write_bytes(old_raw)
    newer = _switch(scene)
    assert newer.generation == 8
    assert pointer.read_bytes() != old_raw
    assert _pending(scene).previous_bytes == old_raw  # type: ignore[union-attr]
    assert _restore(scene) == old
    assert pointer.read_bytes() == old_raw
    assert _active(scene) == old


def test_recovery_after_crash_before_pointer_switch(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    selection = scene.manager / "candidate-selection.json"
    original = os.replace

    def inject(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if dst == selection:
            raise OSError("simulated power loss")
        original(src, dst)

    with patch("paper_data_suite.evergreen_activation_slots.os.replace", inject):
        with pytest.raises(ActivationSlotError, match="atomic write"):
            _switch(scene)
    assert not selection.exists()
    assert _pending(scene) is not None
    assert _restore(scene) is None
    assert _pending(scene) is None


def test_recovery_rejects_unexpected_third_party_selection(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    _switch(scene)
    pointer = scene.manager / "candidate-selection.json"
    pointer.write_bytes(b"malicious")
    with pytest.raises(ActivationSlotError, match="ambiguous"):
        _restore(scene)
    assert pointer.read_bytes() == b"malicious"
    assert _pending(scene) is not None


def test_incorrect_recovery_identity_preserves_state(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    _switch(scene)
    with pytest.raises(ActivationSlotError, match="transaction mismatch"):
        restore_previous_selection(
            scene.manager,
            classroom_workspace=scene.workspace,
            transaction_id="a" * 32,
        )
    assert _pending(scene) is not None


def test_pending_recovery_blocks_second_switch(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    _switch(scene)
    with pytest.raises(ActivationSlotError, match="needs recovery"):
        _switch(scene)


def test_existing_global_lock_blocks_switch(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    lock = scene.manager / "candidate-selection.lock"
    lock.write_text("busy")
    with pytest.raises(ActivationSlotError, match="already locked"):
        _switch(scene)
    assert lock.exists()


def test_malformed_journal_evidence_never_switches(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    journal = json.loads(scene.journal.read_bytes())
    journal["native_envelope_sha256"] = "0" * 64
    scene.journal.write_bytes(
        json.dumps(journal, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(ActivationSlotError, match="evidence differs"):
        _switch(scene)


def test_malformed_pending_marker_refuses_recovery_without_deletion(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    _switch(scene)
    marker = scene.manager / "pending-slot-recovery.json"
    marker.write_bytes(b'{"unknown":true}')
    with pytest.raises(ActivationSlotError, match="schema"):
        _restore(scene)
    assert marker.exists()


def test_software_workspace_overlap_refuses_selection(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    with pytest.raises(ActivationSlotError, match="software/classroom"):
        read_candidate_selection(
            scene.manager, classroom_workspace=scene.manager / "transactions"
        )


def test_previous_pointer_with_missing_physical_slot_refused(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    old = UntrustedSlotSelection("a" * 32, "nonexistent", "a" * 64, "b" * 64, 1)
    (scene.manager / "candidate-selection.json").write_bytes(_selection_bytes(old))
    with pytest.raises(ActivationSlotError, match="previous software slot"):
        _switch(scene)
    assert _pending(scene) is None


def test_prior_receipt_claim_cannot_be_satisfied_by_local_pointer(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    kwargs = scene.inputs()
    begin_verified_update_intent(
        scene.manager,
        stage_root=scene.stage,
        wheelhouse=scene.wheels,
        previous_receipt_sha256="a" * 64,
        **kwargs,
    )
    scene.arm()
    with pytest.raises(ActivationSlotError, match="previous receipt authority"):
        _switch(scene)


def test_recovery_is_idempotent_when_prior_preimage_is_already_present(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    prior = UntrustedSlotSelection("a" * 32, "old-stage", "a" * 64, "b" * 64, 1)
    (scene.manager / "old-stage").mkdir()
    pointer = scene.manager / "candidate-selection.json"
    raw = _selection_bytes(prior)
    pointer.write_bytes(raw)
    _switch(scene)
    # Simulate a crash after restoring the exact preimage but before marker deletion.
    pointer.write_bytes(raw)
    assert _restore(scene) == prior
    assert pointer.read_bytes() == raw
    assert _pending(scene) is None


def test_unsigned_selection_cannot_claim_activation(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    _arm(scene)
    _switch(scene)
    pointer = scene.manager / "candidate-selection.json"
    payload = json.loads(pointer.read_bytes())
    payload["can_launch"] = True
    pointer.write_bytes(json.dumps(payload).encode())
    with pytest.raises(ActivationSlotError, match="ambiguous"):
        _restore(scene)
    assert _pending(scene) is not None
