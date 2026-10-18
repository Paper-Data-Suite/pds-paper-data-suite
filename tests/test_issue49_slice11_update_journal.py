"""Issue #49 Slice 11: verified transaction intents and crash-recovery signals."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_issue49_slice3_signature_verification import NOW, _ring
from test_issue49_slice9_virtualenv_runtime import _scene
from test_issue49_slice10_signed_native_evidence import _evidence

from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    begin_verified_update_intent,
    classify_recovery,
    load_update_intent,
    record_safe_disposition,
    request_activation_intent,
)


class Scene:
    def __init__(self, tmp_path: Path, layout: str = "windows") -> None:
        self.manager = tmp_path / "software"
        self.manager.mkdir()
        self.workspace = tmp_path / "classroom"
        self.workspace.mkdir()
        (self.manager / "transactions").mkdir()
        (
            self.stage,
            self.wheels,
            self.registry,
            self.lock,
            self.prepared,
            self.layout,
        ) = _scene(self.manager, layout=layout)
        scene = (
            self.stage,
            self.wheels,
            self.registry,
            self.lock,
            self.prepared,
            self.layout,
        )
        self.evidence = _evidence(scene)
        self.tx = "f" * 32
        self.journal = self.manager / "transactions" / f"{self.tx}.json"

    def inputs(self) -> dict[str, Any]:
        return dict(
            classroom_workspace=self.workspace,
            prepared_record=self.prepared,
            registry_envelope=self.registry,
            lock_envelope=self.lock,
            evidence_envelope=self.evidence,
            trust=_ring(),
            now=NOW,
            layout=self.layout,
        )

    def begin(self):
        return begin_verified_update_intent(
            self.manager,
            stage_root=self.stage,
            wheelhouse=self.wheels,
            **self.inputs(),
        )

    def arm(self, *, expected_revision: int = 1):
        return request_activation_intent(
            self.manager,
            transaction_id=self.tx,
            expected_revision=expected_revision,
            **self.inputs(),
        )

    def load(self):
        return load_update_intent(
            self.manager,
            classroom_workspace=self.workspace,
            transaction_id=self.tx,
        )


def test_verified_candidate_creates_only_journal_not_install(tmp_path: Path) -> None:
    sample = Scene(tmp_path)
    before = {
        p.relative_to(sample.stage): p.read_bytes()
        for p in sample.stage.rglob("*")
        if p.is_file()
    }
    saved = sample.begin()
    assert sample.load() == saved
    assert saved.phase is UpdatePhase.CANDIDATE_VERIFIED
    assert saved.revision == 1
    assert not saved.recovery_required
    assert saved.expected_previous_receipt_sha256 is None
    assert classify_recovery(saved) == "candidate_only_no_activation_attempted"
    assert not hasattr(saved, "can_launch")
    assert not hasattr(saved, "activated")
    assert not (sample.journal.parent / f"{sample.tx}.lock").exists()
    assert {
        p.relative_to(sample.stage): p.read_bytes()
        for p in sample.stage.rglob("*")
        if p.is_file()
    } == before


def test_activation_intent_remains_nonactivating_and_requires_recovery(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    armed = scene.arm()
    assert armed.revision == 2
    assert armed.phase is UpdatePhase.ACTIVATION_INTENT
    assert armed.recovery_required
    assert classify_recovery(scene.load()) == (
        "manual_active_install_reconciliation_required"
    )
    assert not (scene.manager / "active.json").exists()
    assert not (scene.manager / "activated").exists()
    with pytest.raises(UpdateJournalError, match="once"):
        scene.arm(expected_revision=2)


def test_interrupted_activation_can_be_marked_recovery_required(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    scene.arm()
    record = record_safe_disposition(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=scene.tx,
        expected_revision=2,
        phase=UpdatePhase.RECOVERY_REQUIRED,
        now=NOW,
    )
    assert record.revision == 3
    assert record.recovery_required
    assert scene.load() == record
    with pytest.raises(UpdateJournalError, match="transition"):
        record_safe_disposition(
            scene.manager,
            classroom_workspace=scene.workspace,
            transaction_id=scene.tx,
            expected_revision=3,
            phase=UpdatePhase.ABORTED,
            now=NOW,
        )


def test_before_activation_candidate_may_be_aborted_without_deletion(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    stopped = record_safe_disposition(
        scene.manager,
        classroom_workspace=scene.workspace,
        transaction_id=scene.tx,
        expected_revision=1,
        phase=UpdatePhase.ABORTED,
        now=NOW,
    )
    assert scene.journal.exists()
    assert classify_recovery(stopped) == "candidate_aborted_no_activation_attempted"
    with pytest.raises(UpdateJournalError, match="once"):
        scene.arm(expected_revision=2)


def test_same_transaction_id_cannot_reset_recorded_intent(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    original = scene.journal.read_bytes()
    with pytest.raises(UpdateJournalError, match="already exists"):
        scene.begin()
    assert scene.journal.read_bytes() == original


def test_stale_revision_is_rejected_without_overwrite(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    before = scene.journal.read_bytes()
    with pytest.raises(UpdateJournalError, match="stale"):
        scene.arm(expected_revision=8)
    assert scene.journal.read_bytes() == before


def test_candidate_tampered_after_verification_refuses_intent(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    python = scene.stage / "Scripts/python.exe"
    python.write_bytes(b"wrong bytes")
    with pytest.raises(UpdateJournalError, match="signed stage verification"):
        scene.arm()
    assert scene.load().phase is UpdatePhase.CANDIDATE_VERIFIED


def test_changed_evidence_bytes_refuse_intent(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    arguments = scene.inputs()
    arguments["registry_envelope"] = scene.registry + b" "
    with pytest.raises(UpdateJournalError, match="evidence bytes have changed"):
        request_activation_intent(
            scene.manager,
            transaction_id=scene.tx,
            expected_revision=1,
            **arguments,
        )
    assert scene.load().revision == 1


def test_same_size_replaced_native_binary_refused(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    original = scene.stage / "Scripts/python.exe"
    original.write_bytes(b"X" * original.stat().st_size)
    with pytest.raises(UpdateJournalError, match="signed stage verification"):
        scene.arm()


def test_untrusted_signer_cannot_create_candidate_journal(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    arguments = scene.inputs()
    arguments["evidence_envelope"] = b"{}"
    with pytest.raises(UpdateJournalError, match="signed stage verification"):
        begin_verified_update_intent(
            scene.manager,
            stage_root=scene.stage,
            wheelhouse=scene.wheels,
            **arguments,
        )
    assert not scene.journal.exists()


def test_classroom_root_must_not_overlap_software_root(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    with pytest.raises(UpdateJournalError, match="outside classroom workspace"):
        begin_verified_update_intent(
            scene.manager,
            classroom_workspace=scene.manager / "transactions",
            stage_root=scene.stage,
            wheelhouse=scene.wheels,
            prepared_record=scene.prepared,
            registry_envelope=scene.registry,
            lock_envelope=scene.lock,
            evidence_envelope=scene.evidence,
            trust=_ring(),
            now=NOW,
            layout=scene.layout,
        )
    assert not scene.journal.exists()


def test_staged_directory_outside_managed_software_refused(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    with pytest.raises(UpdateJournalError, match="escapes software root"):
        begin_verified_update_intent(
            scene.manager,
            stage_root=scene.workspace,
            wheelhouse=scene.wheels,
            **scene.inputs(),
        )


def test_symlinked_stage_parent_refused_without_touching_target(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    link = scene.manager / "linked-stage"
    try:
        link.symlink_to(scene.stage, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(UpdateJournalError, match="reparse"):
        begin_verified_update_intent(
            scene.manager,
            stage_root=link,
            wheelhouse=scene.wheels,
            **scene.inputs(),
        )
    assert not scene.journal.exists()


def test_locked_transaction_refuses_mutation(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    lock = scene.journal.with_suffix(".lock")
    lock.write_text("occupied")
    before = scene.journal.read_bytes()
    with pytest.raises(UpdateJournalError, match="locked"):
        scene.arm()
    assert scene.journal.read_bytes() == before
    assert lock.exists()


def test_atomic_replace_failure_preserves_old_checkpoint(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    before = scene.journal.read_bytes()
    with patch(
        "paper_data_suite.evergreen_update_journal.os.replace",
        side_effect=OSError("injected"),
    ):
        with pytest.raises(UpdateJournalError, match="atomically persist"):
            scene.arm()
    assert scene.journal.read_bytes() == before
    assert sorted(path.name for path in scene.journal.parent.iterdir()) == [
        f"{scene.tx}.json"
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update({"phase": "committed"}),
        lambda d: d.update({"is_active": True}),
        lambda d: d.update({"revision": True}),
        lambda d: d.update({"prepared_sha256": "a" * 63}),
        lambda d: d.update({"stage_relative_path": "../bad"}),
    ],
)
def test_local_journal_cannot_claim_active_installation(
    tmp_path: Path,
    mutation: Any,
) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    data = json.loads(scene.journal.read_bytes())
    mutation(data)
    scene.journal.write_bytes(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(UpdateJournalError):
        scene.load()


def test_duplicate_json_fields_refused(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    raw = scene.journal.read_bytes()
    modified = raw.replace(b'"revision":1', b'"revision":1,"revision":1')
    scene.journal.write_bytes(modified)
    with pytest.raises(UpdateJournalError, match="duplicate"):
        scene.load()


def test_historical_time_regression_refused(tmp_path: Path) -> None:
    scene = Scene(tmp_path)
    scene.begin()
    inputs = scene.inputs()
    inputs["now"] = NOW - timedelta(days=1)
    with pytest.raises(UpdateJournalError, match="clock predates"):
        request_activation_intent(
            scene.manager,
            transaction_id=scene.tx,
            expected_revision=1,
            **inputs,
        )


def test_untrusted_local_file_never_grants_launch_even_if_self_consistent(
    tmp_path: Path,
) -> None:
    scene = Scene(tmp_path)
    initial = scene.begin()
    assert initial.expected_previous_receipt_sha256 is None
    assert scene.load().phase is UpdatePhase.CANDIDATE_VERIFIED
    assert not hasattr(scene.load(), "release_trust")
    assert not hasattr(scene.load(), "can_launch")
