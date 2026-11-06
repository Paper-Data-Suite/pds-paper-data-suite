"""Slice 43: an inert durable proposal and signed-but-unresolved head readback."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_activation_slots import (
    PendingSlotRecovery,
    UntrustedSlotSelection,
    _recovery_bytes,
    _selection_bytes,
)
from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_local_receipt_recovery import (
    LocalReceiptRecoveryError,
    inspect_pending_forward_recovery,
    persist_untrusted_successor_proposal,
)
from paper_data_suite.evergreen_successor_receipt_draft import (
    WitnessBoundSuccessorDraft,
)
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdatePhase,
    _serialize,
)

NOW = datetime(2026, 10, 20, 18, tzinfo=UTC)
INSTALL = "a" * 32
OLD = "b" * 32
NEW = "c" * 32
WITNESS = "independent_witness"
CONTEXT = "service-operator"


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
def prepared(tmp_path: Path) -> dict[str, Any]:
    root, classroom = tmp_path / "software", tmp_path / "classroom"
    root.mkdir()
    classroom.mkdir()
    (root / "transactions").mkdir()
    for entry in ("prior/one", "prior/wheels", "candidate/two", "candidate/wheels"):
        (root / entry).mkdir(parents=True)
    old_prepared, old_registry, old_lock, old_native = b"p", b"r", b"l", b"n"
    new_prepared, new_registry, new_lock, new_native = b"P", b"R", b"L", b"N"
    prior = make_untrusted_active_receipt(
        _candidate(OLD, "prior/one", "prior/wheels"),
        prepared_record=old_prepared,
        registry_envelope=old_registry,
        lock_envelope=old_lock,
        native_envelope=old_native,
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        _candidate(NEW, "candidate/two", "candidate/wheels"),
        prepared_record=new_prepared,
        registry_envelope=new_registry,
        lock_envelope=new_lock,
        native_envelope=new_native,
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, _sha(prior)),
    )
    old_selection = _selection_bytes(
        UntrustedSlotSelection(
            OLD, "prior/one", _sha(old_prepared), _sha(old_native), 1
        )
    )
    selected = _selection_bytes(
        UntrustedSlotSelection(
            NEW, "candidate/two", _sha(new_prepared), _sha(new_native), 2
        )
    )
    (root / "candidate-selection.json").write_bytes(selected)
    (root / "pending-slot-recovery.json").write_bytes(
        _recovery_bytes(
            PendingSlotRecovery(NEW, old_selection, _sha(selected), _sha(old_selection))
        )
    )
    journal = UntrustedUpdateJournal(
        NEW,
        2,
        UpdatePhase.ACTIVATION_INTENT,
        NOW - timedelta(seconds=30),
        "candidate/two",
        "candidate/wheels",
        _sha(new_prepared),
        _sha(new_registry),
        _sha(new_lock),
        _sha(new_native),
        _sha(b"previous observation"),
    )
    journal_file = root / "transactions" / f"{NEW}.json"
    journal_file.write_bytes(_serialize(journal))
    draft = WitnessBoundSuccessorDraft(
        NEW, 1, 2, _sha(prior), 1, _sha(successor), successor
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        conn,
        witness_id=WITNESS,
        authorize=lambda identity, operation, context: (
            identity == INSTALL and context == CONTEXT
        ),
        sign=private.sign,
    )
    store.commit_receipt(INSTALL, prior, context=CONTEXT)
    counts = {"reads": 0}

    def transport(challenge: bytes) -> bytes:
        counts["reads"] += 1
        return store.answer_challenge(challenge, context=CONTEXT, now=NOW)

    prepare_args = {
        "software_root": root,
        "classroom_workspace": classroom,
        "transaction_id": NEW,
        "draft": draft,
        "previous_receipt_bytes": prior,
        "installation_id": INSTALL,
        "witness_id": WITNESS,
        "witness_transport": transport,
        "pinned_public_key": public,
        "now": NOW,
    }
    observe_args = {
        "software_root": root,
        "classroom_workspace": classroom,
        "transaction_id": NEW,
        "witness_transport": transport,
        "pinned_public_key": public,
        "now": NOW,
    }
    return {
        "root": root,
        "classroom": classroom,
        "journal_file": journal_file,
        "prior": prior,
        "successor": successor,
        "prepare": prepare_args,
        "observe": observe_args,
        "store": store,
        "counts": counts,
    }


def _proposal_path(scenario: dict[str, Any]) -> Path:
    return scenario["root"] / "transactions" / f"{NEW}.successor-proposal.json"


def _persist(scenario: dict[str, Any]) -> Any:
    return persist_untrusted_successor_proposal(**scenario["prepare"])


def _observe(scenario: dict[str, Any]) -> Any:
    return inspect_pending_forward_recovery(**scenario["observe"])


def test_durable_proposal_preserves_both_pending_files(
    prepared: dict[str, Any],
) -> None:
    root = prepared["root"]
    (prepared["classroom"] / "student.txt").write_text("preserved")
    old_state = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    result = _persist(prepared)
    assert result.status == "UNTRUSTED_PROPOSAL_STORED_RECOVERY_REMAINS_PENDING"
    assert result.successor_sha256 == _sha(prepared["successor"])
    assert result.predecessor_sha256 == _sha(prepared["prior"])
    path = _proposal_path(prepared)
    assert _sha(path.read_bytes()) == result.record_sha256
    changed = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert set(changed) - set(old_state) == {path.relative_to(root)}
    assert all(changed[key] == value for key, value in old_state.items())
    assert (prepared["classroom"] / "student.txt").read_text() == "preserved"
    assert prepared["counts"]["reads"] == 1
    assert not hasattr(result, "activate") and not hasattr(result, "commit")


def test_old_signed_head_remains_unresolved(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    result = _observe(prepared)
    assert result.status == "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"
    assert result.generation == 1 and result.witness_revision == 1
    assert result.authority == "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
    assert prepared["counts"]["reads"] == 2
    assert (prepared["root"] / "pending-slot-recovery.json").exists()


def test_advanced_signed_head_still_requires_forward_recovery(
    prepared: dict[str, Any],
) -> None:
    _persist(prepared)
    prepared["store"].commit_receipt(INSTALL, prepared["successor"], context=CONTEXT)
    result = _observe(prepared)
    assert result.status == "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
    assert result.generation == 2 and result.witness_revision == 2
    assert result.observed_receipt_sha256 == _sha(prepared["successor"])
    assert result.authority == "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
    assert (prepared["root"] / "pending-slot-recovery.json").exists()
    assert not hasattr(result, "rollback")


def test_cannot_persist_after_witness_has_advanced(prepared: dict[str, Any]) -> None:
    prepared["store"].commit_receipt(INSTALL, prepared["successor"], context=CONTEXT)
    with pytest.raises(LocalReceiptRecoveryError, match="already witnessed"):
        _persist(prepared)
    assert not _proposal_path(prepared).exists()


def test_no_duplicate_proposal_overwrite(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    original = _proposal_path(prepared).read_bytes()
    with pytest.raises(LocalReceiptRecoveryError, match="already"):
        _persist(prepared)
    assert _proposal_path(prepared).read_bytes() == original


def test_cannot_inspect_without_durable_proposal(prepared: dict[str, Any]) -> None:
    with pytest.raises(LocalReceiptRecoveryError, match="no durable proposal"):
        _observe(prepared)
    assert prepared["counts"]["reads"] == 0


def test_corrupted_durable_record_refused_before_read(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    _proposal_path(prepared).write_bytes(b"not json")
    previous = prepared["counts"]["reads"]
    with pytest.raises(LocalReceiptRecoveryError):
        _observe(prepared)
    assert prepared["counts"]["reads"] == previous


def test_noncanonical_record_refused(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    path = _proposal_path(prepared)
    data = json.loads(path.read_bytes())
    path.write_bytes(json.dumps(data, indent=2).encode("ascii"))
    with pytest.raises(LocalReceiptRecoveryError, match="noncanonical"):
        _observe(prepared)


def test_durable_request_tamper_refused(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    path = _proposal_path(prepared)
    path.write_bytes(
        path.read_bytes().replace(
            b"proposal_only_not_active", b"active_install_is_valid"
        )
    )
    with pytest.raises(LocalReceiptRecoveryError):
        _observe(prepared)


def test_missing_recovery_capsule_blocks_both_steps(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    (prepared["root"] / "pending-slot-recovery.json").unlink()
    with pytest.raises(LocalReceiptRecoveryError):
        _observe(prepared)
    assert _proposal_path(prepared).exists()


def test_changed_selection_after_persist_refused(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    (prepared["root"] / "candidate-selection.json").write_bytes(
        _selection_bytes(
            UntrustedSlotSelection(OLD, "prior/one", "0" * 64, "0" * 64, 1)
        )
    )
    with pytest.raises(LocalReceiptRecoveryError):
        _observe(prepared)


def test_changed_journal_after_persist_refused(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    from paper_data_suite.evergreen_update_journal import _parse

    journal_file = prepared["journal_file"]
    journal = _parse(journal_file.read_bytes())
    journal_file.write_bytes(_serialize(replace(journal, recorded_at=NOW)))
    with pytest.raises(LocalReceiptRecoveryError, match="drift"):
        _observe(prepared)


def test_journal_already_recovered_not_an_activation(prepared: dict[str, Any]) -> None:
    _persist(prepared)
    from paper_data_suite.evergreen_update_journal import _parse

    journal_file = prepared["journal_file"]
    journal = _parse(journal_file.read_bytes())
    journal_file.write_bytes(
        _serialize(replace(journal, revision=3, phase=UpdatePhase.RECOVERY_REQUIRED))
    )
    with pytest.raises(LocalReceiptRecoveryError):
        _observe(prepared)


def test_wrong_signed_key_fails_without_write(prepared: dict[str, Any]) -> None:
    kwargs = {**prepared["prepare"], "pinned_public_key": b"0" * 32}
    with pytest.raises(LocalReceiptRecoveryError):
        persist_untrusted_successor_proposal(**kwargs)
    assert not _proposal_path(prepared).exists()


def test_network_outage_keeps_pending_proposal(prepared: dict[str, Any]) -> None:
    _persist(prepared)

    def unavailable(_request: bytes) -> bytes:
        raise ConnectionError("offline")

    with pytest.raises(LocalReceiptRecoveryError):
        inspect_pending_forward_recovery(
            **{**prepared["observe"], "witness_transport": unavailable}
        )
    assert _proposal_path(prepared).exists()


def test_draft_changed_receipt_refused(prepared: dict[str, Any]) -> None:
    invalid = replace(prepared["prepare"]["draft"], proposed_receipt_sha256="0" * 64)
    with pytest.raises(LocalReceiptRecoveryError):
        persist_untrusted_successor_proposal(
            **{**prepared["prepare"], "draft": invalid}
        )
    assert not _proposal_path(prepared).exists()


def test_predecessor_drift_refused(prepared: dict[str, Any]) -> None:
    kwargs = {**prepared["prepare"], "previous_receipt_bytes": b"other"}
    with pytest.raises(LocalReceiptRecoveryError):
        persist_untrusted_successor_proposal(**kwargs)
    assert not _proposal_path(prepared).exists()


def test_unexpected_pending_selection_blocks_persist(prepared: dict[str, Any]) -> None:
    selected = prepared["root"] / "candidate-selection.json"
    selected.write_bytes(
        _selection_bytes(
            UntrustedSlotSelection(NEW, "prior/one", "0" * 64, "0" * 64, 2)
        )
    )
    with pytest.raises(LocalReceiptRecoveryError):
        _persist(prepared)
    assert not _proposal_path(prepared).exists()


def test_locked_selection_prevents_mutation(prepared: dict[str, Any]) -> None:
    lock = prepared["root"] / "candidate-selection.lock"
    lock.write_bytes(b"")
    with pytest.raises(LocalReceiptRecoveryError, match="locked"):
        _persist(prepared)
    assert lock.exists()
    assert not _proposal_path(prepared).exists()


def test_locked_journal_prevents_mutation(prepared: dict[str, Any]) -> None:
    lock = prepared["root"] / "transactions" / f"{NEW}.lock"
    lock.write_bytes(b"")
    with pytest.raises(LocalReceiptRecoveryError, match="locked"):
        _persist(prepared)
    assert lock.exists()
    assert not _proposal_path(prepared).exists()


def test_selected_state_drift_during_witness_blocks_write(
    prepared: dict[str, Any],
) -> None:
    normal = prepared["prepare"]["witness_transport"]

    def alter(challenge: bytes) -> bytes:
        result = normal(challenge)
        (prepared["root"] / "candidate-selection.json").write_bytes(
            _selection_bytes(
                UntrustedSlotSelection(OLD, "prior/one", "0" * 64, "0" * 64, 1)
            )
        )
        return result

    with pytest.raises(LocalReceiptRecoveryError):
        persist_untrusted_successor_proposal(
            **{**prepared["prepare"], "witness_transport": alter}
        )
    assert not _proposal_path(prepared).exists()


def test_record_atomic_write_failure_preserves_pending(
    prepared: dict[str, Any],
) -> None:
    import paper_data_suite.evergreen_local_receipt_recovery as module

    with patch.object(module.os, "replace", side_effect=OSError("disk full")):
        with pytest.raises(LocalReceiptRecoveryError, match="atomic"):
            _persist(prepared)
    assert not _proposal_path(prepared).exists()
    assert (prepared["root"] / "pending-slot-recovery.json").exists()
    assert not list((prepared["root"] / "transactions").glob(".pds-proposal-*.tmp"))


def test_foreign_unsafe_proposal_symlink_refused(
    prepared: dict[str, Any], tmp_path: Path
) -> None:
    path = _proposal_path(prepared)
    other = tmp_path / "external"
    other.write_bytes(b"alien")
    try:
        path.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with pytest.raises(LocalReceiptRecoveryError):
        _persist(prepared)
    assert other.read_bytes() == b"alien"


def test_no_execution_or_service_cas(prepared: dict[str, Any]) -> None:
    with (
        patch("subprocess.run", side_effect=AssertionError("must not execute")),
        patch.object(
            prepared["store"],
            "commit_receipt",
            side_effect=AssertionError("service CAS must not run"),
        ),
    ):
        _persist(prepared)
        _observe(prepared)
    assert (prepared["root"] / "pending-slot-recovery.json").exists()
