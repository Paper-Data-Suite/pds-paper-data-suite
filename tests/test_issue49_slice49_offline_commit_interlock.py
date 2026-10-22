"""Slice 49: no offline pointer rollback across possible external witness CAS."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice40_witness_slot_transition as witness_fixtures
from test_issue49_slice40_witness_slot_transition import (
    _recover as witness_recover,
)
from test_issue49_slice40_witness_slot_transition import (
    _select as witness_select,
)

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    PendingSlotRecovery,
    UntrustedSlotSelection,
    _parse_recovery,
    _recovery_bytes,
    _selection_bytes,
    restore_previous_selection,
)
from paper_data_suite.evergreen_offline_commit_interlock import (
    OfflineCommitInterlockError,
    refuse_if_local_successor_proposal_exists,
)
from paper_data_suite.evergreen_witness_slot_transition import (
    WitnessSlotTransitionError,
)

# Expose a shared pytest fixture without shadowing an imported name.
witness_ready = witness_fixtures.ready

TX = "c" * 32
OLD = "b" * 32


def proposal(root: Path) -> Path:
    return root / "transactions" / f"{TX}.successor-proposal.json"


def test_pure_interlock_rejects_any_present_proposal(tmp_path: Path) -> None:
    (tmp_path / "transactions").mkdir()
    refuse_if_local_successor_proposal_exists(tmp_path, TX)
    path = proposal(tmp_path)
    path.write_bytes(b"not canonical evidence")
    with pytest.raises(OfflineCommitInterlockError, match="protected"):
        refuse_if_local_successor_proposal_exists(tmp_path, TX)
    assert path.read_bytes() == b"not canonical evidence"
    path.unlink()
    path.mkdir()
    with pytest.raises(OfflineCommitInterlockError, match="protected"):
        refuse_if_local_successor_proposal_exists(tmp_path, TX)


@pytest.mark.parametrize("invalid", ["../../bad", "A" * 32, "x" * 32, "", None])
def test_invalid_transaction_identity_refused(tmp_path: Path, invalid: Any) -> None:
    with pytest.raises(OfflineCommitInterlockError, match="identity"):
        refuse_if_local_successor_proposal_exists(tmp_path, invalid)


def test_interlock_never_follows_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "transactions"
    directory.mkdir()
    target = tmp_path / "external"
    target.write_bytes(b"must-not-read")
    try:
        proposal(tmp_path).symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(OfflineCommitInterlockError, match="protected"):
        refuse_if_local_successor_proposal_exists(tmp_path, TX)
    assert target.read_bytes() == b"must-not-read"


def legacy_scene(tmp_path: Path) -> tuple[Path, Path, bytes, bytes]:
    root, classroom = tmp_path / "software", tmp_path / "classroom"
    root.mkdir()
    classroom.mkdir()
    (root / "transactions").mkdir()
    old = _selection_bytes(
        UntrustedSlotSelection(OLD, "old-stage", "a" * 64, "b" * 64, 1)
    )
    newer = _selection_bytes(
        UntrustedSlotSelection(TX, "new-stage", "c" * 64, "d" * 64, 2)
    )
    (root / "candidate-selection.json").write_bytes(newer)
    (root / "pending-slot-recovery.json").write_bytes(
        _recovery_bytes(
            PendingSlotRecovery(
                TX,
                old,
                hashlib.sha256(newer).hexdigest(),
                hashlib.sha256(old).hexdigest(),
            )
        )
    )
    return root, classroom, old, newer


def test_legacy_restore_refuses_pending_proposal_without_mutation(
    tmp_path: Path,
) -> None:
    root, classroom, _old, selected = legacy_scene(tmp_path)
    marker = root / "pending-slot-recovery.json"
    prior_marker = marker.read_bytes()
    proposal(root).write_bytes(b"broken record still fences")
    with pytest.raises(ActivationSlotError, match="offline restore blocked"):
        restore_previous_selection(
            root, classroom_workspace=classroom, transaction_id=TX
        )
    assert (root / "candidate-selection.json").read_bytes() == selected
    assert marker.read_bytes() == prior_marker
    assert proposal(root).exists()
    assert not (root / "candidate-selection.lock").exists()


def test_legacy_restore_without_proposal_remains_inert(tmp_path: Path) -> None:
    root, classroom, prior, _ = legacy_scene(tmp_path)
    result = restore_previous_selection(
        root, classroom_workspace=classroom, transaction_id=TX
    )
    assert result is not None and result.transaction_id == OLD
    assert (root / "candidate-selection.json").read_bytes() == prior
    assert not (root / "pending-slot-recovery.json").exists()


def test_witness_offline_restore_refuses_possible_cas_without_mutation(
    witness_ready: dict[str, Any],
) -> None:
    witness_select(witness_ready)
    root: Path = witness_ready["root"]
    pointer = root / "candidate-selection.json"
    capsule = root / "pending-slot-recovery.json"
    journal = root / "transactions" / f"{TX}.json"
    before = (pointer.read_bytes(), capsule.read_bytes(), journal.read_bytes())
    proposal(root).write_bytes(b"malformed proposal")
    with pytest.raises(WitnessSlotTransitionError, match="offline restore blocked"):
        witness_recover(witness_ready)
    assert before == (pointer.read_bytes(), capsule.read_bytes(), journal.read_bytes())
    assert not (root / "candidate-selection.lock").exists()
    assert not (root / "transactions" / f"{TX}.lock").exists()


def test_witness_crash_after_pointer_restore_still_keeps_capsule(
    witness_ready: dict[str, Any],
) -> None:
    witness_select(witness_ready)
    root: Path = witness_ready["root"]
    pointer = root / "candidate-selection.json"
    capsule = root / "pending-slot-recovery.json"
    saved = capsule.read_bytes()
    prior = _parse_recovery(saved).previous_bytes
    assert prior is not None
    # Simulate interruption after writing the old pointer but before cleanup.
    pointer.write_bytes(prior)
    proposal(root).write_bytes(b"pending-witness-request")
    with pytest.raises(WitnessSlotTransitionError, match="offline restore blocked"):
        witness_recover(witness_ready)
    assert pointer.read_bytes() == prior
    assert capsule.read_bytes() == saved
    assert proposal(root).is_file()


def test_guard_does_not_touch_teacher_workspace_or_network(
    witness_ready: dict[str, Any],
) -> None:
    witness_select(witness_ready)
    root: Path = witness_ready["root"]
    workspace: Path = witness_ready["workspace"]
    student = workspace / "student-original.txt"
    student.write_text("retained")
    proposal(root).write_bytes(b"possible CAS")
    with (
        patch("socket.create_connection", side_effect=AssertionError("network")),
        patch("subprocess.run", side_effect=AssertionError("execution")),
    ):
        with pytest.raises(WitnessSlotTransitionError):
            witness_recover(witness_ready)
    assert student.read_text() == "retained"
    assert proposal(root).read_bytes() == b"possible CAS"


def test_proposal_absence_is_not_remote_cas_proof(tmp_path: Path) -> None:
    root, _, _, _ = legacy_scene(tmp_path)
    assert refuse_if_local_successor_proposal_exists(root, TX) is None
    # This fact alone is not authority to launch, witness-commit or rollback.
