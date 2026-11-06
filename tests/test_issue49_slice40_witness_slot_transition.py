"""Slice 40: inert reversible selection, offline recovery, and crash boundaries."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    UntrustedSlotSelection,
    _selection_bytes,
    read_candidate_selection,
    read_pending_slot_recovery,
)
from paper_data_suite.evergreen_active_receipts import make_untrusted_active_receipt
from paper_data_suite.evergreen_catalog_verification import (
    TrustedKeyring,
    TrustedPublicKey,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_native_evidence import NativeEvidenceError
from paper_data_suite.evergreen_previous_install import (
    PreviousInstallationError,
    PreviousSlotObservation,
    VerifiedPreviousSlotBytes,
)
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    ProposedCandidateEvidence,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    PublisherPipPreflightError,
)
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdatePhase,
    _parse,
    _serialize,
)
from paper_data_suite.evergreen_witness_slot_transition import (
    WitnessSlotTransitionError,
    reconcile_witness_bound_selection_offline,
    select_witness_bound_candidate_slot,
)

NOW = datetime(2026, 10, 20, 18, tzinfo=UTC)
INSTALL = "a" * 32
OLD = "b" * 32
NEW = "c" * 32
WITNESS = "independent_witness"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        wheels,
        "3" * 64,
        "4" * 64,
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root, classroom = tmp_path / "software", tmp_path / "classroom"
    root.mkdir()
    classroom.mkdir()
    (root / "transactions").mkdir()
    for entry in ("prior/one", "prior/wheels", "candidate/two", "candidate/wheels"):
        (root / entry).mkdir(parents=True)
    (root / "prior/one/bytes.bin").write_bytes(b"old bytes")
    (root / "candidate/two/bytes.bin").write_bytes(b"new bytes")
    before_inputs = ProposedCandidateEvidence(b"p", b"r", b"l", b"n")
    after_inputs = ProposedCandidateEvidence(b"P", b"R", b"L", b"N")
    original = _candidate(OLD, "prior/one", "prior/wheels")
    receipt = make_untrusted_active_receipt(
        original,
        prepared_record=before_inputs.prepared_record,
        registry_envelope=before_inputs.registry_envelope,
        lock_envelope=before_inputs.lock_envelope,
        native_envelope=before_inputs.native_envelope,
        generation=1,
        recorded_at=NOW - timedelta(minutes=1),
        previous=None,
    )
    selected = UntrustedSlotSelection(OLD, "prior/one", _sha(b"p"), _sha(b"n"), 1)
    (root / "candidate-selection.json").write_bytes(_selection_bytes(selected))
    old_observation = b"prior byte observation for this test double"
    new_journal = UntrustedUpdateJournal(
        NEW,
        2,
        UpdatePhase.ACTIVATION_INTENT,
        NOW - timedelta(seconds=30),
        "candidate/two",
        "candidate/wheels",
        _sha(b"P"),
        _sha(b"R"),
        _sha(b"L"),
        _sha(b"N"),
        _sha(old_observation),
    )
    (root / "transactions" / f"{NEW}.json").write_bytes(_serialize(new_journal))
    previous = PreviousSlotObservation(
        OLD,
        "prior/one",
        "prior/wheels",
        1,
        _sha(b"p"),
        _sha(b"r"),
        _sha(b"l"),
        _sha(b"n"),
        "3" * 64,
        1,
    )
    counts: dict[str, int] = {"old": 0, "new": 0, "prior": 0, "native": 0}

    def fake_prior(
        record: bytes, software_root: Path, **kwargs: Any
    ) -> VerifiedPreviousSlotBytes:
        counts["prior"] += 1
        if (software_root / "prior/one/bytes.bin").read_bytes() != b"old bytes":
            raise PreviousInstallationError("changed predecessor software")
        assert kwargs["wheelhouse"] == root / "prior/wheels"
        return VerifiedPreviousSlotBytes(previous, _sha(record))

    def fake_pip(stage: Path, wheels: Path, **kwargs: Any) -> SimpleNamespace:
        is_old = stage == root / "prior/one"
        label = "old" if is_old else "new"
        counts[label] += 1
        expected = b"old bytes" if is_old else b"new bytes"
        if (stage / "bytes.bin").read_bytes() != expected:
            raise PublisherPipPreflightError("changed installed pip bytes")
        return SimpleNamespace(
            transaction_id=OLD if is_old else NEW,
            stage_root=stage,
            wheelhouse=wheels,
            pip_inventory_sha256="4" * 64,
            publisher_digests=(("quillan", "5" * 64),),
            root_console_targets=(("quillan", "quillan", "quillan.cli:main"),),
            external_distributions=("pds-core",),
        )

    def fake_native(stage: Path, wheels: Path, **kwargs: Any) -> SimpleNamespace:
        counts["native"] += 1
        if (stage / "bytes.bin").read_bytes() != b"new bytes":
            raise NativeEvidenceError("changed native bytes")
        return SimpleNamespace(
            transaction_id=NEW, stage_root=stage, payload_sha256="6" * 64
        )

    import paper_data_suite.evergreen_witness_slot_transition as module

    monkeypatch.setattr(module, "verify_previous_slot_record", fake_prior)
    monkeypatch.setattr(module, "audit_publisher_bound_pip_candidate", fake_pip)
    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", fake_native)
    private = Ed25519PrivateKey.generate()
    connection = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        connection,
        witness_id=WITNESS,
        authorize=lambda install, operation, context: (
            install == INSTALL and context == "service"
        ),
        sign=private.sign,
    )
    store.commit_receipt(INSTALL, receipt, context="service")

    def transport(challenge: bytes) -> bytes:
        return store.answer_challenge(challenge, context="service", now=NOW)

    key = Ed25519PrivateKey.generate()
    trust = TrustedKeyring(
        (
            TrustedPublicKey(
                "root_key",
                key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
            ),
        ),
        ("root_key",),
    )
    kwargs: dict[str, Any] = {
        "software_root": root,
        "classroom_workspace": classroom,
        "transaction_id": NEW,
        "expected_revision": 2,
        "candidate": after_inputs,
        "candidate_module_envelopes": {"quillan": b"new"},
        "prior": ClaimedPriorEvidence(
            old_observation, root / "prior/wheels", b"p", b"r", b"l", b"n"
        ),
        "prior_module_envelopes": {"quillan": b"old"},
        "previous_receipt_bytes": receipt,
        "witness_transport": transport,
        "installation_id": INSTALL,
        "pinned_public_key": private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ),
        "expected_witness_id": WITNESS,
        "trust": trust,
        "now": NOW,
    }
    return {"args": kwargs, "counts": counts, "root": root, "workspace": classroom}


def _journal(ready: dict[str, Any]) -> UntrustedUpdateJournal:
    root = ready["root"]
    return _parse((root / "transactions" / f"{NEW}.json").read_bytes())


def _write_journal(ready: dict[str, Any], **change: Any) -> None:
    file = ready["root"] / "transactions" / f"{NEW}.json"
    file.write_bytes(_serialize(replace(_journal(ready), **change)))


def _select(ready: dict[str, Any]) -> Any:
    return select_witness_bound_candidate_slot(**ready["args"])


def _recover(ready: dict[str, Any]) -> Any:
    return reconcile_witness_bound_selection_offline(
        ready["root"],
        classroom_workspace=ready["workspace"],
        transaction_id=NEW,
        now=NOW,
    )


def test_selection_writes_recovery_first_and_only_two_inert_files(
    ready: dict[str, Any],
) -> None:
    root, workspace = ready["root"], ready["workspace"]
    (workspace / "original.txt").write_text("student work unchanged")
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    result = _select(ready)
    assert result.status == "INERT_SELECTION_PENDING_EXPLICIT_RECOVERY"
    assert result.previous_generation == 1 and result.selected_generation == 2
    assert result.witness_revision == 1
    assert result.previous_receipt_sha256 == _sha(
        ready["args"]["previous_receipt_bytes"]
    )
    assert result.selected_stage == "candidate/two"
    assert _journal(ready).phase is UpdatePhase.ACTIVATION_INTENT
    assert _journal(ready).revision == 2
    pending = read_pending_slot_recovery(root, classroom_workspace=workspace)
    assert pending is not None and pending.transaction_id == NEW
    assert pending.previous_bytes == before[Path("candidate-selection.json")]
    with pytest.raises(ActivationSlotError, match="pending"):
        read_candidate_selection(root, classroom_workspace=workspace)
    current = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert set(current) - set(before) == {Path("pending-slot-recovery.json")}
    assert {p for p in before if before[p] != current[p]} == {
        Path("candidate-selection.json")
    }
    assert (workspace / "original.txt").read_text() == "student work unchanged"
    assert ready["counts"] == {"old": 2, "new": 2, "prior": 2, "native": 2}
    assert not hasattr(result, "launch") and not hasattr(result, "commit")


def test_offline_recovery_restores_exact_pointer_and_preserves_unresolved_journal(
    ready: dict[str, Any],
) -> None:
    root = ready["root"]
    old_bytes = (root / "candidate-selection.json").read_bytes()
    _select(ready)
    with patch(
        "paper_data_suite.evergreen_witness_slot_transition.query_checkpoint_witness",
        side_effect=AssertionError("offline rollback MUST NOT query witness"),
    ):
        result = _recover(ready)
    assert result.status == "OLD_INERT_POINTER_RESTORED_FULL_RECOVERY_REQUIRED"
    assert result.restored_generation == 1 and result.journal_revision == 3
    assert (root / "candidate-selection.json").read_bytes() == old_bytes
    assert not (root / "pending-slot-recovery.json").exists()
    assert _journal(ready).phase is UpdatePhase.RECOVERY_REQUIRED
    assert read_candidate_selection(root, classroom_workspace=ready["workspace"]) == (
        UntrustedSlotSelection(OLD, "prior/one", _sha(b"p"), _sha(b"n"), 1)
    )
    assert (root / "prior/one/bytes.bin").read_bytes() == b"old bytes"
    assert (root / "candidate/two/bytes.bin").read_bytes() == b"new bytes"
    with pytest.raises(WitnessSlotTransitionError):
        _select(ready)


def test_replay_selection_while_pending_is_refused(ready: dict[str, Any]) -> None:
    _select(ready)
    with pytest.raises(WitnessSlotTransitionError, match="recovery capsule"):
        _select(ready)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_revision", 1),
        ("expected_revision", True),
        ("candidate", None),
        ("prior", None),
        ("trust", None),
        ("previous_receipt_bytes", b""),
        ("pinned_public_key", b"a"),
        ("now", datetime(2026, 10, 20)),
        ("now", NOW.replace(microsecond=1)),
        ("candidate_module_envelopes", {}),
        ("prior_module_envelopes", {}),
    ],
)
def test_invalid_inputs_refuse_before_mutation(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(**{**ready["args"], field: value})
    assert _journal(ready).revision == 2
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


@pytest.mark.parametrize(
    "revision,phase",
    [
        (1, UpdatePhase.CANDIDATE_VERIFIED),
        (3, UpdatePhase.RECOVERY_REQUIRED),
        (2, UpdatePhase.ABORTED),
    ],
)
def test_requires_exact_armed_revision(
    ready: dict[str, Any], revision: int, phase: UpdatePhase
) -> None:
    _write_journal(ready, revision=revision, phase=phase)
    with pytest.raises(WitnessSlotTransitionError, match="armed"):
        _select(ready)


def test_witness_wrong_signer_fails_closed(ready: dict[str, Any]) -> None:
    args = {**ready["args"], "pinned_public_key": b"0" * 32}
    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(**args)
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_replayed_witness_revision_fails_closed(ready: dict[str, Any]) -> None:
    args = {**ready["args"], "minimum_witness_revision": 2}
    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(**args)


def test_witness_outage_keeps_original_pointer(ready: dict[str, Any]) -> None:
    old = (ready["root"] / "candidate-selection.json").read_bytes()
    args = {
        **ready["args"],
        "witness_transport": lambda _: (_ for _ in ()).throw(
            ConnectionError("offline")
        ),
    }
    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(**args)
    assert (ready["root"] / "candidate-selection.json").read_bytes() == old
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_candidate_byte_change_during_witness_is_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        answer = original(request)
        (ready["root"] / "candidate/two/bytes.bin").write_bytes(b"changed")
        return answer

    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(
            **{**ready["args"], "witness_transport": tamper}
        )
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_prior_byte_change_during_witness_is_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        answer = original(request)
        (ready["root"] / "prior/one/bytes.bin").write_bytes(b"changed")
        return answer

    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(
            **{**ready["args"], "witness_transport": tamper}
        )
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_pointer_change_during_witness_is_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        answer = original(request)
        (ready["root"] / "candidate-selection.json").write_bytes(
            _selection_bytes(
                UntrustedSlotSelection(OLD, "prior/one", "0" * 64, "0" * 64, 1)
            )
        )
        return answer

    with pytest.raises(WitnessSlotTransitionError, match="coordinated state"):
        select_witness_bound_candidate_slot(
            **{**ready["args"], "witness_transport": tamper}
        )


def test_journal_change_during_witness_is_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        answer = original(request)
        _write_journal(ready, recorded_at=NOW - timedelta(seconds=10))
        return answer

    with pytest.raises(WitnessSlotTransitionError, match="coordinated state"):
        select_witness_bound_candidate_slot(
            **{**ready["args"], "witness_transport": tamper}
        )


def test_expired_witness_during_second_audit_refused(ready: dict[str, Any]) -> None:
    import paper_data_suite.evergreen_witness_slot_transition as module

    with patch.object(module.time, "monotonic", side_effect=[0.0, 301.0]):
        with pytest.raises(WitnessSlotTransitionError, match="expired"):
            _select(ready)
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_corrupt_receipt_rejected(ready: dict[str, Any]) -> None:
    args = {**ready["args"]}
    args["previous_receipt_bytes"] = args["previous_receipt_bytes"].replace(
        b'"generation":1', b'"generation":2'
    )
    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(**args)


def test_missing_prior_directory_rejected(ready: dict[str, Any]) -> None:
    (ready["root"] / "prior/one/bytes.bin").unlink()
    (ready["root"] / "prior/one").rmdir()
    with pytest.raises(WitnessSlotTransitionError):
        _select(ready)


def test_recovery_marker_write_failure_leaves_old_pointer(
    ready: dict[str, Any],
) -> None:
    import paper_data_suite.evergreen_witness_slot_transition as module

    old = (ready["root"] / "candidate-selection.json").read_bytes()
    with patch.object(module, "_atomic", side_effect=ActivationSlotError("disk full")):
        with pytest.raises(WitnessSlotTransitionError):
            _select(ready)
    assert (ready["root"] / "candidate-selection.json").read_bytes() == old
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_interruption_after_recovery_capsule_is_offline_recoverable(
    ready: dict[str, Any],
) -> None:
    import paper_data_suite.evergreen_witness_slot_transition as module

    original_atomic = module._atomic
    attempts = 0
    old = (ready["root"] / "candidate-selection.json").read_bytes()

    def interrupted(path: Path, raw: bytes) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise ActivationSlotError("selection interrupted")
        original_atomic(path, raw)

    with patch.object(module, "_atomic", side_effect=interrupted):
        with pytest.raises(WitnessSlotTransitionError):
            _select(ready)
    assert (ready["root"] / "candidate-selection.json").read_bytes() == old
    assert (
        read_pending_slot_recovery(
            ready["root"], classroom_workspace=ready["workspace"]
        )
        is not None
    )
    assert _recover(ready).restored_generation == 1
    assert _journal(ready).phase is UpdatePhase.RECOVERY_REQUIRED


def test_interruption_after_pointer_restore_is_retryable(
    ready: dict[str, Any],
) -> None:
    import paper_data_suite.evergreen_witness_slot_transition as module

    old = (ready["root"] / "candidate-selection.json").read_bytes()
    _select(ready)
    with patch.object(module, "_atomic_save", side_effect=OSError("power loss")):
        with pytest.raises(OSError, match="power loss"):
            _recover(ready)
    assert (ready["root"] / "candidate-selection.json").read_bytes() == old
    assert (ready["root"] / "pending-slot-recovery.json").exists()
    assert _journal(ready).phase is UpdatePhase.ACTIVATION_INTENT
    assert _recover(ready).journal_revision == 3


def test_interruption_after_journal_recovery_write_is_retryable(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ready["root"]
    marker = root / "pending-slot-recovery.json"
    _select(ready)
    original_unlink = Path.unlink

    def interrupt_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == marker:
            raise OSError("power loss")
        original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", interrupt_unlink)
        with pytest.raises(WitnessSlotTransitionError, match="cleanup"):
            _recover(ready)
    assert _journal(ready).revision == 3
    assert _journal(ready).phase is UpdatePhase.RECOVERY_REQUIRED
    assert marker.exists()
    assert _recover(ready).journal_revision == 3
    assert not marker.exists()


def test_recovery_refuses_unknown_selection_without_clobbering(
    ready: dict[str, Any],
) -> None:
    root = ready["root"]
    _select(ready)
    alien = _selection_bytes(
        UntrustedSlotSelection("d" * 32, "prior/one", "0" * 64, "0" * 64, 7)
    )
    (root / "candidate-selection.json").write_bytes(alien)
    with pytest.raises(WitnessSlotTransitionError, match="ambiguous"):
        _recover(ready)
    assert (root / "candidate-selection.json").read_bytes() == alien
    assert (root / "pending-slot-recovery.json").exists()
    assert _journal(ready).revision == 2


def test_recovery_rejects_unrelated_transaction(ready: dict[str, Any]) -> None:
    _select(ready)
    with pytest.raises(WitnessSlotTransitionError, match="ambiguous"):
        reconcile_witness_bound_selection_offline(
            ready["root"],
            classroom_workspace=ready["workspace"],
            transaction_id="d" * 32,
            now=NOW,
        )
    assert _journal(ready).revision == 2


def test_missing_capsule_requires_manual_reconciliation(
    ready: dict[str, Any],
) -> None:
    _select(ready)
    (ready["root"] / "pending-slot-recovery.json").unlink()
    with pytest.raises(WitnessSlotTransitionError, match="no pending"):
        _recover(ready)
    assert _journal(ready).revision == 2


def test_recovery_cannot_reconcile_journal_drift(ready: dict[str, Any]) -> None:
    _select(ready)
    _write_journal(ready, revision=4)
    with pytest.raises(WitnessSlotTransitionError, match="ambiguous"):
        _recover(ready)
    assert (ready["root"] / "pending-slot-recovery.json").exists()


def test_locks_are_released_on_refusal(ready: dict[str, Any]) -> None:
    args = {**ready["args"], "minimum_witness_revision": 5}
    with pytest.raises(WitnessSlotTransitionError):
        select_witness_bound_candidate_slot(**args)
    assert not (ready["root"] / "candidate-selection.lock").exists()
    assert not (ready["root"] / "transactions" / f"{NEW}.lock").exists()


def test_selection_lock_prevents_concurrent_transition(ready: dict[str, Any]) -> None:
    lock = ready["root"] / "candidate-selection.lock"
    lock.write_bytes(b"")
    with pytest.raises(WitnessSlotTransitionError, match="locked"):
        _select(ready)
    assert lock.exists()


def test_no_subprocess_or_teacher_launch(ready: dict[str, Any]) -> None:
    with patch("subprocess.run", side_effect=AssertionError("no execution")):
        _select(ready)
        _recover(ready)
    assert (ready["root"] / "candidate/two/bytes.bin").read_bytes() == b"new bytes"
