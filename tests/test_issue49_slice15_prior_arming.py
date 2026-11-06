"""Issue #49 Slice 15: two-sided, guarded intent only; NEVER activation."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from test_issue49_slice3_signature_verification import _ring
from test_issue49_slice14_prior_update import _two_sides

from paper_data_suite.evergreen_prior_arming import (
    PriorArmingError,
    arm_prior_bound_update_intent,
)
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    ProposedCandidateEvidence,
)
from paper_data_suite.evergreen_update_journal import UpdatePhase


def _arm(scene, candidate, prior, **kwargs):
    return arm_prior_bound_update_intent(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=kwargs.pop("transaction_id", scene.tx),
        expected_revision=kwargs.pop("expected_revision", 1),
        candidate=candidate,
        prior=prior,
        trust=kwargs.pop("trust", _ring()),
        now=kwargs.pop("now", scene.inputs()["now"]),
        layout=scene.layout,
        **kwargs,
    )


def test_two_sided_signed_observation_arms_only_intent(tmp_path: Path) -> None:
    scene, candidate, prior = _two_sides(tmp_path)
    original_pointer = (scene.manager / "candidate-selection.json").read_bytes()
    result = _arm(scene, candidate, prior)
    assert result.phase is UpdatePhase.ACTIVATION_INTENT
    assert result.revision == 2
    assert result.expected_previous_receipt_sha256 is not None
    assert scene.load() == result
    assert (scene.manager / "candidate-selection.json").read_bytes() == original_pointer
    assert not (scene.manager / "pending-slot-recovery.json").exists()
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "active")


def test_replay_cannot_arm_twice(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    _arm(scene, current, prior)
    with pytest.raises(PriorArmingError, match="unarmed"):
        _arm(scene, current, prior, expected_revision=2)
    assert scene.load().revision == 2


def test_stale_revision_rejected_unchanged(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    before = scene.journal.read_bytes()
    with pytest.raises(PriorArmingError, match="stale"):
        _arm(scene, current, prior, expected_revision=2)
    assert scene.journal.read_bytes() == before


def test_missing_prior_hash_refused(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    before = json.loads(scene.journal.read_bytes())
    before["expected_previous_receipt_sha256"] = None
    scene.journal.write_text(json.dumps(before, sort_keys=True, separators=(",", ":")))
    with pytest.raises(PriorArmingError, match="prior-bound"):
        _arm(scene, current, prior)
    assert scene.load().phase is UpdatePhase.CANDIDATE_VERIFIED


def test_changed_candidate_fails_before_intent(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    (scene.stage / "Scripts/python.exe").write_bytes(b"changed")
    with pytest.raises(PriorArmingError, match="prior-bound"):
        _arm(scene, current, prior)
    assert scene.load().revision == 1


def test_changed_prior_fails_before_intent(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    (scene.manager / "old-stage/Scripts/python.exe").write_bytes(b"changed")
    with pytest.raises(PriorArmingError, match="prior-bound"):
        _arm(scene, current, prior)
    assert scene.load().revision == 1


def test_modified_prior_observation_fails_closed(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    bad = ClaimedPriorEvidence(
        prior.observation_record + b" ",
        prior.wheelhouse,
        prior.prepared_record,
        prior.registry_envelope,
        prior.lock_envelope,
        prior.native_envelope,
    )
    with pytest.raises(PriorArmingError, match="prior-bound"):
        _arm(scene, current, bad)


def test_changed_candidate_envelope_fails_closed(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    bad = ProposedCandidateEvidence(
        current.prepared_record,
        current.registry_envelope,
        current.lock_envelope,
        current.native_envelope + b"!",
    )
    with pytest.raises(PriorArmingError, match="prior-bound"):
        _arm(scene, bad, prior)


def test_conflicting_selection_writer_lock_blocks(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    lock = scene.manager / "candidate-selection.lock"
    lock.write_text("occupied")
    try:
        with pytest.raises(PriorArmingError, match="selection lock"):
            _arm(scene, current, prior)
        assert lock.exists()
        assert scene.load().revision == 1
    finally:
        lock.unlink()


def test_conflicting_journal_writer_lock_blocks(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    lock = scene.manager / "transactions" / f"{scene.tx}.lock"
    lock.write_text("occupied")
    try:
        with pytest.raises(PriorArmingError, match="prior-bound"):
            _arm(scene, current, prior)
        assert not (scene.manager / "candidate-selection.lock").exists()
        assert scene.load().revision == 1
    finally:
        lock.unlink()


def test_pending_selection_recovery_blocks(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    marker = scene.manager / "pending-slot-recovery.json"
    marker.write_bytes(b"pending")
    with pytest.raises(PriorArmingError, match="unreconciled"):
        _arm(scene, current, prior)
    assert marker.exists()
    assert scene.load().revision == 1


def test_expired_native_evidence_cannot_arm(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    with pytest.raises(PriorArmingError, match="prior-bound"):
        _arm(scene, current, prior, now=scene.inputs()["now"] + timedelta(days=50))
    assert scene.load().revision == 1


def test_future_unsafe_clock_rejected(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    with pytest.raises(PriorArmingError, match="clock"):
        _arm(scene, current, prior, now=scene.inputs()["now"] - timedelta(days=1))


def test_naive_clock_rejected(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    with pytest.raises(PriorArmingError, match="timezone-aware"):
        _arm(scene, current, prior, now=scene.inputs()["now"].replace(tzinfo=None))


def test_wrong_transaction_preserves_original_state(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    with pytest.raises(PriorArmingError, match="stale"):
        _arm(scene, current, prior, transaction_id="a" * 32)
    assert scene.load().revision == 1


def test_atomic_replace_failure_keeps_prior_journal(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    before = scene.journal.read_bytes()
    with patch(
        "paper_data_suite.evergreen_update_journal.os.replace",
        side_effect=OSError("disk"),
    ):
        with pytest.raises(PriorArmingError, match="prior-bound"):
            _arm(scene, current, prior)
    assert scene.journal.read_bytes() == before
    assert not (scene.manager / "candidate-selection.lock").exists()
    assert not (scene.manager / "transactions" / f"{scene.tx}.lock").exists()


def test_no_classroom_mutation_or_stage_write(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    sensitive = scene.workspace / "students-private.txt"
    sensitive.write_text("never touch", encoding="utf-8")
    stage_before = {
        path.relative_to(scene.stage): path.read_bytes()
        for path in scene.stage.rglob("*")
        if path.is_file()
    }
    _arm(scene, current, prior)
    assert stage_before == {
        path.relative_to(scene.stage): path.read_bytes()
        for path in scene.stage.rglob("*")
        if path.is_file()
    }
    assert sensitive.read_text(encoding="utf-8") == "never touch"


def test_malformed_pending_marker_blocks_without_parsing(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    marker = scene.manager / "pending-slot-recovery.json"
    marker.write_bytes(b"bad marker")
    with pytest.raises(PriorArmingError, match="unreconciled"):
        _arm(scene, current, prior)


def test_no_overlapping_root_or_workspace(tmp_path: Path) -> None:
    scene, current, prior = _two_sides(tmp_path)
    with pytest.raises(PriorArmingError, match="software root"):
        arm_prior_bound_update_intent(
            scene.manager,
            classroom_workspace=scene.manager / "old-stage",
            transaction_id=scene.tx,
            expected_revision=1,
            candidate=current,
            prior=prior,
            trust=_ring(),
            now=scene.inputs()["now"],
            layout=scene.layout,
        )
