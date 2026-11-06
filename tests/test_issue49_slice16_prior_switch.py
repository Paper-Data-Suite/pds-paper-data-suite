"""Issue #49 Slice 16: guarded previous-slot selection; NEVER live activation."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from test_issue49_slice3_signature_verification import _ring
from test_issue49_slice14_prior_update import _two_sides
from test_issue49_slice15_prior_arming import _arm

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    read_candidate_selection,
    read_pending_slot_recovery,
    restore_previous_selection,
)
from paper_data_suite.evergreen_prior_switch import (
    PriorSwitchError,
    switch_armed_prior_bound_selection,
)
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    ProposedCandidateEvidence,
)
from paper_data_suite.evergreen_update_journal import UpdatePhase


def _go(scene, current, prior, **overrides):
    return switch_armed_prior_bound_selection(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=overrides.pop("transaction_id", scene.tx),
        expected_revision=overrides.pop("expected_revision", 2),
        candidate=current,
        prior=prior,
        trust=overrides.pop("trust", _ring()),
        now=overrides.pop("now", scene.inputs()["now"]),
        layout=scene.layout,
        **overrides,
    )


def _setup(tmp_path):
    scene, current, prior = _two_sides(tmp_path)
    _arm(scene, current, prior)
    return scene, current, prior


def test_armed_prior_bound_switch_is_inert_and_recoverable(tmp_path: Path) -> None:
    scene, current, prior = _setup(tmp_path)
    pointer = scene.manager / "candidate-selection.json"
    old_bytes = pointer.read_bytes()
    stage_files = {
        p.relative_to(scene.manager): p.read_bytes()
        for p in scene.manager.rglob("*")
        if p.is_file() and ("old-stage" in p.parts or p.is_relative_to(scene.stage))
    }
    new = _go(scene, current, prior)
    assert new.transaction_id == scene.tx
    assert new.generation == 5
    assert not hasattr(new, "can_launch")
    assert not hasattr(new, "is_active")
    assert scene.load().phase is UpdatePhase.ACTIVATION_INTENT
    recovery = read_pending_slot_recovery(
        scene.manager, classroom_workspace=scene.workspace
    )
    assert recovery is not None and recovery.previous_bytes == old_bytes
    with pytest.raises(ActivationSlotError, match="reconciliation"):
        read_candidate_selection(scene.manager, classroom_workspace=scene.workspace)
    assert stage_files == {
        p.relative_to(scene.manager): p.read_bytes()
        for p in scene.manager.rglob("*")
        if p.is_file() and ("old-stage" in p.parts or p.is_relative_to(scene.stage))
    }
    old = restore_previous_selection(
        scene.manager, classroom_workspace=scene.workspace, transaction_id=scene.tx
    )
    assert old is not None and old.generation == 4
    assert pointer.read_bytes() == old_bytes
    assert scene.stage.exists() and (scene.manager / "old-stage").exists()


def test_unarmed_journal_cannot_switch(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    with pytest.raises(PriorSwitchError, match="revision"):
        _go(scene, current, old, expected_revision=1)


def test_wrong_revision_and_transaction_do_not_change_pointer(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    pointer = (scene.manager / "candidate-selection.json").read_bytes()
    with pytest.raises(PriorSwitchError, match="armed"):
        _go(scene, current, old, expected_revision=3)
    with pytest.raises(PriorSwitchError, match="armed"):
        _go(scene, current, old, transaction_id="a" * 32)
    assert (scene.manager / "candidate-selection.json").read_bytes() == pointer


def test_prior_receipt_is_not_optional(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    doc = json.loads(scene.journal.read_bytes())
    doc["expected_previous_receipt_sha256"] = None
    scene.journal.write_bytes(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(PriorSwitchError, match="prior binding"):
        _go(scene, current, old)


def test_modified_candidate_executable_is_rejected(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    (scene.stage / "Scripts/python.exe").write_bytes(b"tampered candidate")
    with pytest.raises(PriorSwitchError, match="signed"):
        _go(scene, current, old)
    assert not (scene.manager / "pending-slot-recovery.json").exists()


def test_modified_previous_executable_is_rejected(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    (scene.manager / "old-stage/Scripts/python.exe").write_bytes(b"tampered prior")
    with pytest.raises(PriorSwitchError, match="signed"):
        _go(scene, current, old)


def test_forged_prior_record_hash_is_not_sufficient(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    modified = ClaimedPriorEvidence(
        old.observation_record + b" ",
        old.wheelhouse,
        old.prepared_record,
        old.registry_envelope,
        old.lock_envelope,
        old.native_envelope,
    )
    with pytest.raises(PriorSwitchError, match="source evidence"):
        _go(scene, current, modified)


def test_changed_candidate_source_envelope_fails(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    changed = ProposedCandidateEvidence(
        current.prepared_record,
        current.registry_envelope,
        current.lock_envelope,
        current.native_envelope + b" ",
    )
    with pytest.raises(PriorSwitchError, match="source evidence"):
        _go(scene, changed, old)


def test_swapped_previous_selection_generation_refused(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    pointer = scene.manager / "candidate-selection.json"
    doc = json.loads(pointer.read_bytes())
    doc["generation"] = 6
    pointer.write_bytes(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(PriorSwitchError, match="signed"):
        _go(scene, current, old)


def test_previous_selection_missing_refused(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    (scene.manager / "candidate-selection.json").unlink()
    with pytest.raises(PriorSwitchError, match="existing selected"):
        _go(scene, current, old)


def test_pending_selection_blocks_another_switch(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    _go(scene, current, old)
    with pytest.raises(PriorSwitchError, match="recovery"):
        _go(scene, current, old)


def test_prior_or_candidate_expiry_fails(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    with pytest.raises(PriorSwitchError, match="signed"):
        _go(scene, current, old, now=scene.inputs()["now"] + timedelta(days=60))


def test_selection_lock_and_journal_lock_are_respected(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    lock = scene.manager / "candidate-selection.lock"
    lock.write_bytes(b"busy")
    with pytest.raises(PriorSwitchError, match="locked"):
        _go(scene, current, old)
    lock.unlink()
    lock = scene.manager / "transactions" / f"{scene.tx}.lock"
    lock.write_bytes(b"busy")
    with pytest.raises(PriorSwitchError, match="locked"):
        _go(scene, current, old)
    assert not (scene.manager / "candidate-selection.lock").exists()
    assert lock.read_bytes() == b"busy"


def test_failure_after_recovery_capsule_keeps_exact_preimage(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    pointer = scene.manager / "candidate-selection.json"
    preimage = pointer.read_bytes()
    original = os.replace

    def interrupt(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == pointer:
            raise OSError("simulated power loss")
        original(src, dst)

    with patch("paper_data_suite.evergreen_activation_slots.os.replace", interrupt):
        with pytest.raises(PriorSwitchError, match="signed"):
            _go(scene, current, old)
    assert pointer.read_bytes() == preimage
    recovery = read_pending_slot_recovery(
        scene.manager, classroom_workspace=scene.workspace
    )
    assert recovery is not None and recovery.previous_bytes == preimage
    restore_previous_selection(
        scene.manager, classroom_workspace=scene.workspace, transaction_id=scene.tx
    )
    assert pointer.read_bytes() == preimage


def test_recovery_refuses_third_party_modified_pointer(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    _go(scene, current, old)
    pointer = scene.manager / "candidate-selection.json"
    pointer.write_bytes(b"not the selected candidate")
    with pytest.raises(ActivationSlotError, match="ambiguous"):
        restore_previous_selection(
            scene.manager, classroom_workspace=scene.workspace, transaction_id=scene.tx
        )


def test_no_classroom_workspace_mutation(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    private = scene.workspace / "private.txt"
    private.write_text("classroom work", encoding="utf8")
    _go(scene, current, old)
    assert private.read_text(encoding="utf8") == "classroom work"


def test_workspace_overlap_refused(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    with pytest.raises(PriorSwitchError, match="root"):
        switch_armed_prior_bound_selection(
            scene.manager,
            classroom_workspace=scene.manager / "old-stage",
            transaction_id=scene.tx,
            expected_revision=2,
            candidate=current,
            prior=old,
            trust=_ring(),
            now=scene.inputs()["now"],
            layout=scene.layout,
        )


def test_recovery_capsule_prior_sha_exact(tmp_path: Path) -> None:
    scene, current, old = _setup(tmp_path)
    pointer = scene.manager / "candidate-selection.json"
    before = pointer.read_bytes()
    _go(scene, current, old)
    record = read_pending_slot_recovery(
        scene.manager, classroom_workspace=scene.workspace
    )
    assert record is not None
    assert record.previous_sha256 == hashlib.sha256(before).hexdigest()
    assert record.candidate_sha256 == hashlib.sha256(pointer.read_bytes()).hexdigest()
