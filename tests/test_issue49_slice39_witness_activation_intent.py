"""Slice 39: a signed witness gates ONLY recoverable journal intent."""

from __future__ import annotations

import hashlib
import os
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
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdatePhase,
    _parse,
    _serialize,
)
from paper_data_suite.evergreen_witness_activation_intent import (
    WitnessActivationIntentError,
    arm_witness_bound_activation_intent,
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
        1,
        UpdatePhase.CANDIDATE_VERIFIED,
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

    import paper_data_suite.evergreen_witness_activation_intent as module

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
        "expected_revision": 1,
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


def _change_journal(ready: dict[str, Any], **kwargs: Any) -> None:
    path = ready["root"] / "transactions" / f"{NEW}.json"
    path.write_bytes(_serialize(replace(_journal(ready), **kwargs)))


def test_arms_only_journal_and_rechecks_both_installations(
    ready: dict[str, Any],
) -> None:
    root, kwargs = ready["root"], ready["args"]
    (ready["workspace"] / "student.txt").write_text("keep")
    old_pointer = (root / "candidate-selection.json").read_bytes()
    before_files = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    result = arm_witness_bound_activation_intent(**kwargs)
    assert result.status == "ACTIVATION_INTENT_ONLY_RECOVERY_REQUIRED"
    assert result.previous_generation == 1 and result.proposed_generation == 2
    assert result.journal_revision == 2 and result.witness_revision == 1
    assert result.previous_receipt_sha256 == _sha(kwargs["previous_receipt_bytes"])
    assert _journal(ready).phase is UpdatePhase.ACTIVATION_INTENT
    assert _journal(ready).revision == 2
    assert (root / "candidate-selection.json").read_bytes() == old_pointer
    assert not (root / "pending-slot-recovery.json").exists()
    assert ready["counts"] == {"old": 2, "new": 2, "prior": 2, "native": 2}
    after_files = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert {
        name for name in after_files if before_files[name] != after_files[name]
    } == {Path("transactions") / f"{NEW}.json"}
    assert (ready["workspace"] / "student.txt").read_text() == "keep"
    assert not hasattr(result, "launch") and not hasattr(result, "activate")


def test_replay_cannot_arm_again(ready: dict[str, Any]) -> None:
    arm_witness_bound_activation_intent(**ready["args"])
    with pytest.raises(WitnessActivationIntentError, match="journal"):
        arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).revision == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_revision", 2),
        ("expected_revision", True),
        ("candidate", None),
        ("prior", None),
        ("trust", None),
        ("previous_receipt_bytes", b""),
        ("pinned_public_key", b"x"),
        ("now", datetime(2026, 10, 20)),
        ("now", NOW.replace(microsecond=1)),
        ("candidate_module_envelopes", {}),
        ("prior_module_envelopes", {}),
    ],
)
def test_bad_inputs_prevent_arm(ready: dict[str, Any], field: str, value: Any) -> None:
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(**{**ready["args"], field: value})
    assert _journal(ready).phase is UpdatePhase.CANDIDATE_VERIFIED


def test_wrong_signed_witness_head_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(
            **{**ready["args"], "pinned_public_key": b"0" * 32}
        )
    assert _journal(ready).revision == 1


def test_witness_revision_rollback_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(
            **{**ready["args"], "minimum_witness_revision": 2}
        )
    assert _journal(ready).revision == 1


def test_cannot_arm_when_pending_recovery(ready: dict[str, Any]) -> None:
    (ready["root"] / "pending-slot-recovery.json").write_bytes(b"unreconciled")
    with pytest.raises(WitnessActivationIntentError, match="recovery"):
        arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).revision == 1


def test_already_held_selection_lock_refused(ready: dict[str, Any]) -> None:
    lock = ready["root"] / "candidate-selection.lock"
    lock.write_bytes(b"")
    with pytest.raises(WitnessActivationIntentError, match="locked"):
        arm_witness_bound_activation_intent(**ready["args"])
    assert lock.exists() and _journal(ready).revision == 1


def test_already_held_journal_lock_refused(ready: dict[str, Any]) -> None:
    lock = ready["root"] / "transactions" / f"{NEW}.lock"
    lock.write_bytes(b"")
    with pytest.raises(WitnessActivationIntentError, match="locked"):
        arm_witness_bound_activation_intent(**ready["args"])
    assert lock.exists() and not (ready["root"] / "candidate-selection.lock").exists()


def test_mutated_prior_receipt_refused(ready: dict[str, Any]) -> None:
    changed = ready["args"]["previous_receipt_bytes"].replace(
        b"prior/one", b"prior/two"
    )
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(
            **{**ready["args"], "previous_receipt_bytes": changed}
        )
    assert _journal(ready).revision == 1


def test_changed_candidate_input_refused(ready: dict[str, Any]) -> None:
    corrupt = replace(ready["args"]["candidate"], lock_envelope=b"different")
    with pytest.raises(WitnessActivationIntentError, match="candidate"):
        arm_witness_bound_activation_intent(**{**ready["args"], "candidate": corrupt})
    assert ready["counts"]["new"] == 0


def test_forged_prior_observation_refused(ready: dict[str, Any]) -> None:
    corrupt = replace(ready["args"]["prior"], observation_record=b"new observation")
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(**{**ready["args"], "prior": corrupt})
    assert _journal(ready).revision == 1


def test_candidate_byte_change_before_witness_refused(ready: dict[str, Any]) -> None:
    (ready["root"] / "candidate/two/bytes.bin").write_bytes(b"tampered")
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).phase is UpdatePhase.CANDIDATE_VERIFIED


def test_prior_byte_change_before_witness_refused(ready: dict[str, Any]) -> None:
    (ready["root"] / "prior/one/bytes.bin").write_bytes(b"tampered")
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).phase is UpdatePhase.CANDIDATE_VERIFIED


def test_candidate_byte_change_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        response = original(request)
        (ready["root"] / "candidate/two/bytes.bin").write_bytes(b"tampered")
        return response

    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(
            **{**ready["args"], "witness_transport": tamper}
        )
    assert ready["counts"]["new"] >= 2
    assert _journal(ready).revision == 1


def test_selection_drift_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        response = original(request)
        (ready["root"] / "candidate-selection.json").write_bytes(
            _selection_bytes(
                UntrustedSlotSelection(OLD, "prior/one", "0" * 64, "0" * 64, 1)
            )
        )
        return response

    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(
            **{**ready["args"], "witness_transport": tamper}
        )
    assert _journal(ready).revision == 1


def test_journal_drift_during_witness_refused(ready: dict[str, Any]) -> None:
    original = ready["args"]["witness_transport"]

    def tamper(request: bytes) -> bytes:
        response = original(request)
        _change_journal(ready, recorded_at=NOW - timedelta(seconds=10))
        return response

    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(
            **{**ready["args"], "witness_transport": tamper}
        )
    assert _journal(ready).revision == 1


def test_journal_aborted_refused_without_network(ready: dict[str, Any]) -> None:
    _change_journal(ready, phase=UpdatePhase.ABORTED)
    args = dict(ready["args"])
    args["witness_transport"] = lambda _: (_ for _ in ()).throw(
        AssertionError("network")
    )
    with pytest.raises(WitnessActivationIntentError, match="journal"):
        arm_witness_bound_activation_intent(**args)


def test_remote_failure_refused_without_mutation(ready: dict[str, Any]) -> None:
    args = dict(ready["args"])
    args["witness_transport"] = lambda _: (_ for _ in ()).throw(
        ConnectionError("offline")
    )
    with pytest.raises(WitnessActivationIntentError, match="rejected"):
        arm_witness_bound_activation_intent(**args)
    assert _journal(ready).phase is UpdatePhase.CANDIDATE_VERIFIED


def test_second_native_audit_is_mandatory(
    ready: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_witness_activation_intent as module

    original = module.verify_signed_staged_native_evidence

    def fail_second(*args: Any, **kwargs: Any) -> Any:
        if ready["counts"]["native"] >= 1:
            raise NativeEvidenceError("second audit failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "verify_signed_staged_native_evidence", fail_second)
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).revision == 1


def test_interrupted_atomic_save_does_not_claim_activation(
    ready: dict[str, Any],
) -> None:
    import paper_data_suite.evergreen_witness_activation_intent as module

    with patch.object(module, "_atomic_save", side_effect=OSError("interrupted")):
        with pytest.raises(OSError, match="interrupted"):
            arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).phase is UpdatePhase.CANDIDATE_VERIFIED
    assert not (ready["root"] / "candidate-selection.lock").exists()
    assert not (ready["root"] / "transactions" / f"{NEW}.lock").exists()


def test_atomic_replace_failure_fails_closed(ready: dict[str, Any]) -> None:
    import paper_data_suite.evergreen_update_journal as journal_module

    # The implementation's _atomic_save is the same imported function object.
    with patch.object(journal_module.os, "replace", side_effect=OSError("disk full")):
        with pytest.raises(WitnessActivationIntentError):
            arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).revision == 1
    assert not list((ready["root"] / "transactions").glob(".pds-intent-*.tmp"))


def test_no_subprocess_provider_import_or_promotion(ready: dict[str, Any]) -> None:
    with patch("subprocess.run", side_effect=AssertionError("execution forbidden")):
        arm_witness_bound_activation_intent(**ready["args"])
    assert (ready["root"] / "candidate-selection.json").exists()
    assert not (ready["root"] / "pending-slot-recovery.json").exists()


def test_witness_expiry_during_second_audit_refused(ready: dict[str, Any]) -> None:
    import paper_data_suite.evergreen_witness_activation_intent as module

    with patch.object(module.time, "monotonic", side_effect=[0.0, 301.0]):
        with pytest.raises(WitnessActivationIntentError, match="expired"):
            arm_witness_bound_activation_intent(**ready["args"])
    assert _journal(ready).revision == 1


def test_locks_released_on_rejection(ready: dict[str, Any]) -> None:
    args = dict(ready["args"])
    args["minimum_witness_revision"] = 5
    with pytest.raises(WitnessActivationIntentError):
        arm_witness_bound_activation_intent(**args)
    assert not (ready["root"] / "candidate-selection.lock").exists()
    assert not (ready["root"] / "transactions" / f"{NEW}.lock").exists()
    assert os.path.isdir(ready["root"] / "prior/one")
