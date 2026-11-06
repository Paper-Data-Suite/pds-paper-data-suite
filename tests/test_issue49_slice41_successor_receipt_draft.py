"""Slice 41: read-only successor draft and strict witness CAS preconditions."""

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
    UntrustedSlotSelection,
    _selection_bytes,
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
from paper_data_suite.evergreen_successor_receipt_draft import (
    SuccessorReceiptDraftError,
    draft_witness_bound_successor_receipt,
)
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdatePhase,
    _parse,
    _serialize,
)
from paper_data_suite.evergreen_witness_slot_transition import (
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
    import paper_data_suite.evergreen_successor_receipt_draft as draft_module

    monkeypatch.setattr(draft_module, "verify_previous_slot_record", fake_prior)
    monkeypatch.setattr(draft_module, "audit_publisher_bound_pip_candidate", fake_pip)
    monkeypatch.setattr(
        draft_module, "verify_signed_staged_native_evidence", fake_native
    )
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


def _selected(ready: dict[str, Any]) -> Any:
    return select_witness_bound_candidate_slot(**ready["args"])


def _draft(ready: dict[str, Any]) -> Any:
    args = dict(ready["args"])
    args.pop("expected_revision")
    return draft_witness_bound_successor_receipt(**args, expected_revision=2)


def _journal(ready: dict[str, Any]) -> UntrustedUpdateJournal:
    root = ready["root"]
    return _parse((root / "transactions" / f"{NEW}.json").read_bytes())


def test_successor_draft_exact_chain_does_not_write_or_commit(
    ready: dict[str, Any],
) -> None:
    root = ready["root"]
    _selected(ready)
    (ready["workspace"] / "student.txt").write_text("original")
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    result = _draft(ready)
    after = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert result.status == "DRAFT_ONLY_CHECKPOINT_NOT_COMMITTED_RECOVERY_STILL_PENDING"
    assert before == after
    assert result.previous_generation == 1 and result.proposed_generation == 2
    assert result.expected_witness_revision == 1
    assert result.proposed_receipt_sha256 == _sha(result.receipt_bytes)
    from paper_data_suite.evergreen_active_receipts import (
        parse_untrusted_active_receipt,
    )

    successor = parse_untrusted_active_receipt(result.receipt_bytes)
    assert successor.generation == 2
    assert successor.transaction_id == NEW
    assert successor.previous_receipt_sha256 == result.previous_receipt_sha256
    assert successor.stage_relative_path == "candidate/two"
    assert successor.native_payload_sha256 == "6" * 64
    assert successor.pip_inventory_sha256 == "4" * 64
    assert result.previous_receipt_sha256 == _sha(
        ready["args"]["previous_receipt_bytes"]
    )
    assert (root / "pending-slot-recovery.json").exists()
    assert _journal(ready).phase is UpdatePhase.ACTIVATION_INTENT
    assert _journal(ready).revision == 2
    assert (ready["workspace"] / "student.txt").read_text() == "original"
    assert ready["counts"] == {"old": 4, "new": 4, "prior": 4, "native": 4}
    assert not hasattr(result, "commit") and not hasattr(result, "launch")


def test_draft_still_requires_explicit_offline_recovery(
    ready: dict[str, Any],
) -> None:
    _selected(ready)
    draft = _draft(ready)
    assert draft.proposed_generation == 2
    with patch(
        "paper_data_suite.evergreen_witness_slot_transition.query_checkpoint_witness",
        side_effect=AssertionError("offline recovery contacted witness"),
    ):
        result = reconcile_witness_bound_selection_offline(
            ready["root"],
            classroom_workspace=ready["workspace"],
            transaction_id=NEW,
            now=NOW,
        )
    assert result.journal_revision == 3
    assert _journal(ready).phase is UpdatePhase.RECOVERY_REQUIRED
    with pytest.raises(SuccessorReceiptDraftError):
        _draft(ready)


def test_no_proposal_without_selection(ready: dict[str, Any]) -> None:
    with pytest.raises(SuccessorReceiptDraftError, match="pending recovery"):
        _draft(ready)
    assert ready["counts"] == {"old": 0, "new": 0, "prior": 0, "native": 0}


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_revision", True),
        ("expected_revision", 1),
        ("candidate", None),
        ("prior", None),
        ("trust", None),
        ("candidate_module_envelopes", {}),
        ("prior_module_envelopes", {}),
        ("previous_receipt_bytes", b""),
        ("pinned_public_key", b"x"),
        ("now", datetime(2026, 10, 20)),
        ("now", NOW.replace(microsecond=1)),
    ],
)
def test_bad_parameters_refused_without_mutation(
    ready: dict[str, Any], field: str, value: Any
) -> None:
    _selected(ready)
    args = {**ready["args"], field: value}
    path = ready["root"] / "candidate-selection.json"
    before = path.read_bytes()
    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(**args)
    assert path.read_bytes() == before
    assert _journal(ready).revision == 2


def test_stale_or_bad_witness_signature_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    args = {**ready["args"], "pinned_public_key": b"0" * 32}
    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(**args)
    assert _journal(ready).revision == 2


def test_witness_revision_rollback_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    args = {**ready["args"], "minimum_witness_revision": 2}
    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(**args)


def test_witness_outage_fails_closed(ready: dict[str, Any]) -> None:
    _selected(ready)
    args = {
        **ready["args"],
        "witness_transport": lambda _: (_ for _ in ()).throw(
            ConnectionError("offline")
        ),
    }
    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(**args)
    assert (ready["root"] / "pending-slot-recovery.json").exists()


def test_tampered_recovery_capsule_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    target = ready["root"] / "pending-slot-recovery.json"
    target.write_bytes(
        target.read_bytes().replace(b"candidate_sha256", b"candidate_sha257")
    )
    with pytest.raises(SuccessorReceiptDraftError):
        _draft(ready)


def test_missing_capsule_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    (ready["root"] / "pending-slot-recovery.json").unlink()
    with pytest.raises(SuccessorReceiptDraftError, match="pending recovery"):
        _draft(ready)


def test_wrong_selected_pointer_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    (ready["root"] / "candidate-selection.json").write_bytes(
        _selection_bytes(
            UntrustedSlotSelection("d" * 32, "candidate/two", "0" * 64, "0" * 64, 2)
        )
    )
    with pytest.raises(SuccessorReceiptDraftError):
        _draft(ready)


def test_stale_journal_rejected(ready: dict[str, Any]) -> None:
    _selected(ready)
    path = ready["root"] / "transactions" / f"{NEW}.json"
    path.write_bytes(_serialize(replace(_journal(ready), revision=3)))
    with pytest.raises(SuccessorReceiptDraftError, match="exact pending"):
        _draft(ready)


def test_changed_candidate_digest_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    args = dict(ready["args"])
    args["candidate"] = replace(args["candidate"], native_envelope=b"changed")
    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(**args)


def test_replaced_previous_receipt_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    args = dict(ready["args"])
    args["previous_receipt_bytes"] = args["previous_receipt_bytes"].replace(
        b'"generation":1', b'"generation":2'
    )
    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(**args)


def test_candidate_modified_during_witness_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        signed = original(challenge)
        (ready["root"] / "candidate/two/bytes.bin").write_bytes(b"tampered")
        return signed

    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(
            **{**ready["args"], "witness_transport": tamper}
        )
    assert _journal(ready).revision == 2


def test_old_software_modified_during_witness_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        signed = original(challenge)
        (ready["root"] / "prior/one/bytes.bin").write_bytes(b"tampered")
        return signed

    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(
            **{**ready["args"], "witness_transport": tamper}
        )


def test_selection_drift_during_remote_query_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        signed = original(challenge)
        (ready["root"] / "candidate-selection.json").write_bytes(b"random")
        return signed

    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(
            **{**ready["args"], "witness_transport": tamper}
        )


def test_recovery_capsule_drift_during_remote_query_refused(
    ready: dict[str, Any],
) -> None:
    _selected(ready)
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        signed = original(challenge)
        (ready["root"] / "pending-slot-recovery.json").write_bytes(b"random")
        return signed

    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(
            **{**ready["args"], "witness_transport": tamper}
        )


def test_replayed_journal_during_remote_query_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    original = ready["args"]["witness_transport"]

    def tamper(challenge: bytes) -> bytes:
        signed = original(challenge)
        path = ready["root"] / "transactions" / f"{NEW}.json"
        path.write_bytes(_serialize(replace(_journal(ready), recorded_at=NOW)))
        return signed

    with pytest.raises(SuccessorReceiptDraftError):
        draft_witness_bound_successor_receipt(
            **{**ready["args"], "witness_transport": tamper}
        )


def test_witness_expired_mid_audit_refused(ready: dict[str, Any]) -> None:
    _selected(ready)
    import paper_data_suite.evergreen_successor_receipt_draft as module

    with patch.object(module.time, "monotonic", side_effect=[0.0, 301.0]):
        with pytest.raises(SuccessorReceiptDraftError, match="expired"):
            _draft(ready)


def test_draft_never_executes_candidate(ready: dict[str, Any]) -> None:
    _selected(ready)
    with patch("subprocess.run", side_effect=AssertionError("execution")):
        result = _draft(ready)
    assert result.proposed_generation == 2


def test_selection_lock_refuses_concurrent_draft(ready: dict[str, Any]) -> None:
    _selected(ready)
    lock = ready["root"] / "candidate-selection.lock"
    lock.write_bytes(b"")
    with pytest.raises(SuccessorReceiptDraftError, match="locked"):
        _draft(ready)
    assert lock.exists()


def test_journal_lock_refuses_concurrent_draft(ready: dict[str, Any]) -> None:
    _selected(ready)
    lock = ready["root"] / "transactions" / f"{NEW}.lock"
    lock.write_bytes(b"")
    with pytest.raises(SuccessorReceiptDraftError, match="locked"):
        _draft(ready)
    assert lock.exists()


def test_draft_is_repeatable_without_local_receipt_write(ready: dict[str, Any]) -> None:
    _selected(ready)
    first = _draft(ready)
    second = _draft(ready)
    assert first == second
    assert not (ready["root"] / "active-receipt.json").exists()
    assert (ready["root"] / "pending-slot-recovery.json").exists()
