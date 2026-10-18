"""Issue #49 Slice 14: prior/update continuity preflight, never activation."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_issue49_slice3_signature_verification import _ring
from test_issue49_slice10_signed_native_evidence import _evidence
from test_issue49_slice11_update_journal import Scene

from paper_data_suite.evergreen_activation_slots import (
    UntrustedSlotSelection,
    _selection_bytes,
)
from paper_data_suite.evergreen_previous_install import capture_previous_slot_record
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    PriorUpdateError,
    ProposedCandidateEvidence,
    verify_prior_bound_candidate,
)
from paper_data_suite.evergreen_update_journal import (
    UpdatePhase,
    begin_verified_update_intent,
)


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def _two_sides(
    tmp_path: Path,
) -> tuple[Scene, ProposedCandidateEvidence, ClaimedPriorEvidence]:
    scene = Scene(tmp_path)
    old_stage = scene.manager / "old-stage"
    old_wheels = scene.manager / "old-wheels"
    shutil.copytree(scene.stage, old_stage)
    shutil.copytree(scene.wheels, old_wheels)
    old_record_json = json.loads(scene.prepared)
    old_record_json["transaction_id"] = "a" * 32
    old_prepared = _canonical(old_record_json)
    old_evidence = _evidence(
        (old_stage, old_wheels, scene.registry, scene.lock, old_prepared, scene.layout)
    )
    pointer = UntrustedSlotSelection(
        "a" * 32,
        "old-stage",
        hashlib.sha256(old_prepared).hexdigest(),
        hashlib.sha256(old_evidence).hexdigest(),
        4,
    )
    (scene.manager / "candidate-selection.json").write_bytes(_selection_bytes(pointer))
    old_record = capture_previous_slot_record(
        scene.manager,
        classroom_workspace=scene.workspace,
        wheelhouse=old_wheels,
        prepared_record=old_prepared,
        registry_envelope=scene.registry,
        lock_envelope=scene.lock,
        evidence_envelope=old_evidence,
        trust=_ring(),
        now=scene.inputs()["now"],
        layout=scene.layout,
    )
    current = ProposedCandidateEvidence(
        scene.prepared, scene.registry, scene.lock, scene.evidence
    )
    previous = ClaimedPriorEvidence(
        old_record,
        old_wheels,
        old_prepared,
        scene.registry,
        scene.lock,
        old_evidence,
    )
    begin_verified_update_intent(
        scene.manager,
        stage_root=scene.stage,
        wheelhouse=scene.wheels,
        previous_receipt_sha256=hashlib.sha256(old_record).hexdigest(),
        **scene.inputs(),
    )
    return scene, current, previous


def _verify(
    scene: Scene,
    current: ProposedCandidateEvidence,
    old: ClaimedPriorEvidence,
    **kwargs: Any,
):
    return verify_prior_bound_candidate(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=kwargs.pop("transaction_id", scene.tx),
        expected_revision=kwargs.pop("expected_revision", 1),
        candidate=current,
        prior=old,
        trust=kwargs.pop("trust", _ring()),
        now=kwargs.pop("now", scene.inputs()["now"]),
        layout=scene.layout,
        **kwargs,
    )


def test_two_sided_preflight_rechecks_distinct_signed_software(tmp_path: Path) -> None:
    scene, candidate, prior = _two_sides(tmp_path)
    observed = _verify(scene, candidate, prior)
    assert observed.candidate_transaction_id == scene.tx
    assert observed.prior_transaction_id == "a" * 32
    assert observed.prior_generation == 4
    assert (
        observed.prior_record_sha256
        == hashlib.sha256(prior.observation_record).hexdigest()
    )
    assert observed.candidate_stage_relative_path == scene.stage.name
    assert observed.prior_stage_relative_path == "old-stage"
    assert scene.load().phase is UpdatePhase.CANDIDATE_VERIFIED
    assert not hasattr(observed, "can_launch")
    assert not hasattr(observed, "is_active")
    assert not hasattr(observed, "trusted_previous_receipt")


def test_preflight_is_read_only_and_never_imports_staged_programs(
    tmp_path: Path,
) -> None:
    scene, current, old = _two_sides(tmp_path)
    classroom = scene.workspace / "never-touch.txt"
    classroom.write_text("private classroom content", encoding="utf-8")
    before = {
        p.relative_to(scene.manager): p.read_bytes()
        for p in scene.manager.rglob("*")
        if p.is_file()
    }
    _verify(scene, current, old)
    assert before == {
        p.relative_to(scene.manager): p.read_bytes()
        for p in scene.manager.rglob("*")
        if p.is_file()
    }
    assert classroom.read_text(encoding="utf-8") == "private classroom content"


def test_prior_record_must_match_exact_journal_hash(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    bad = ClaimedPriorEvidence(
        old.observation_record + b" ",
        old.wheelhouse,
        old.prepared_record,
        old.registry_envelope,
        old.lock_envelope,
        old.native_envelope,
    )
    with pytest.raises(PriorUpdateError, match="prior record"):
        _verify(scene, current, bad)


def test_missing_prior_hash_cannot_bootstrap_its_own_trust(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    journal = json.loads(scene.journal.read_bytes())
    journal["expected_previous_receipt_sha256"] = None
    scene.journal.write_bytes(_canonical(journal))
    with pytest.raises(PriorUpdateError, match="no previous receipt binding"):
        _verify(scene, current, old)


def test_swapped_previous_pointer_fails_binding(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    pointer = scene.manager / "candidate-selection.json"
    data = json.loads(pointer.read_bytes())
    data["generation"] += 1
    pointer.write_bytes(_canonical(data))
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(scene, current, old)


def test_pending_recovery_refuses_candidate_and_previous(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    (scene.manager / "pending-slot-recovery.json").write_bytes(b"pending")
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(scene, current, old)


def test_modified_prior_binary_fails_even_when_record_hash_matches(
    tmp_path: Path,
) -> None:
    scene, current, old = _two_sides(tmp_path)
    (scene.manager / "old-stage/Scripts/python.exe").write_bytes(b"tampered")
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(scene, current, old)


def test_modified_candidate_binary_fails(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    (scene.stage / "Scripts/python.exe").write_bytes(b"tampered")
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(scene, current, old)


def test_candidate_signed_envelope_must_match_journal(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    mutated = ProposedCandidateEvidence(
        current.prepared_record,
        current.registry_envelope,
        current.lock_envelope,
        current.native_envelope + b" ",
    )
    with pytest.raises(PriorUpdateError, match="candidate evidence differs"):
        _verify(scene, mutated, old)


def test_prior_signed_envelope_must_reverify(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    mutated = ClaimedPriorEvidence(
        old.observation_record,
        old.wheelhouse,
        old.prepared_record,
        old.registry_envelope,
        old.lock_envelope,
        b"{}",
    )
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(scene, current, mutated)


def test_stale_revision_and_wrong_transaction_refused(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    with pytest.raises(PriorUpdateError, match="stale"):
        _verify(scene, current, old, expected_revision=2)
    with pytest.raises(PriorUpdateError, match="stale"):
        _verify(scene, current, old, transaction_id="b" * 32)


def test_preflight_may_not_reclassify_armed_transaction(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    scene.arm()
    with pytest.raises(PriorUpdateError, match="unarmed"):
        _verify(scene, current, old, expected_revision=2)


def test_no_false_approval_from_expired_online_metadata(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(scene, current, old, now=scene.inputs()["now"] + timedelta(days=50))


def test_fake_provenance_objects_are_not_accepted(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    with pytest.raises(PriorUpdateError, match="both raw"):
        _verify(scene, current, object())  # type: ignore[arg-type]
    with pytest.raises(PriorUpdateError, match="both raw"):
        _verify(scene, object(), old)  # type: ignore[arg-type]


def test_previous_wheelhouse_must_be_original_signed_directory(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    with pytest.raises(PriorUpdateError, match="signed prior/update"):
        _verify(
            scene,
            current,
            ClaimedPriorEvidence(
                old.observation_record,
                scene.wheels,
                old.prepared_record,
                old.registry_envelope,
                old.lock_envelope,
                old.native_envelope,
            ),
        )


def test_candidate_cannot_overlap_previous_staging(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    journal = json.loads(scene.journal.read_bytes())
    journal["stage_relative_path"] = "old-stage"
    scene.journal.write_bytes(_canonical(journal))
    with pytest.raises(PriorUpdateError):
        _verify(scene, current, old)


def test_candidate_may_not_share_prior_wheelhouse(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    journal = json.loads(scene.journal.read_bytes())
    journal["wheelhouse_relative_path"] = "old-wheels"
    scene.journal.write_bytes(_canonical(journal))
    with pytest.raises(PriorUpdateError, match="directories overlap"):
        _verify(scene, current, old)


def test_none_or_boolean_revision_refused(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    for revision in (None, True, 0):
        with pytest.raises(PriorUpdateError, match="revision"):
            _verify(scene, current, old, expected_revision=revision)


def test_invalid_trust_type_and_naive_clock_refused(tmp_path: Path) -> None:
    scene, current, old = _two_sides(tmp_path)
    with pytest.raises(PriorUpdateError, match="keyring"):
        _verify(scene, current, old, trust=object())  # type: ignore[arg-type]
    with pytest.raises(PriorUpdateError, match="aware"):
        _verify(scene, current, old, now=scene.inputs()["now"].replace(tzinfo=None))
