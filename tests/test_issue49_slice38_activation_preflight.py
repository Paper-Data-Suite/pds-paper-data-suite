"""Slice 38: signed predecessor versus proposed staged update, never activation."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from paper_data_suite.evergreen_activation_preflight import (
    ActivationPreflightError,
    inspect_witness_bound_update_preflight,
)
from paper_data_suite.evergreen_activation_slots import (
    UntrustedSlotSelection,
    _selection_bytes,
)
from paper_data_suite.evergreen_active_receipts import make_untrusted_active_receipt
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
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


def _candidate(
    transaction: str, stage: str, wheels: str
) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        transaction,
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
def scenario(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "software"
    classroom = tmp_path / "classroom"
    root.mkdir()
    classroom.mkdir()
    (root / "transactions").mkdir()
    for path in ("prior/one", "prior/wheels", "candidate/two", "candidate/wheels"):
        (root / path).mkdir(parents=True)
    old = _candidate(OLD, "prior/one", "prior/wheels")
    fresh = _candidate(NEW, "candidate/two", "candidate/wheels")
    old_inputs = ProposedCandidateEvidence(b"p", b"r", b"l", b"n")
    new_inputs = ProposedCandidateEvidence(b"P", b"R", b"L", b"N")
    receipt = make_untrusted_active_receipt(
        old,
        prepared_record=old_inputs.prepared_record,
        registry_envelope=old_inputs.registry_envelope,
        lock_envelope=old_inputs.lock_envelope,
        native_envelope=old_inputs.native_envelope,
        generation=1,
        recorded_at=NOW - timedelta(minutes=1),
        previous=None,
    )
    old_selected = UntrustedSlotSelection(
        OLD,
        old.stage_relative_path,
        hashlib.sha256(old_inputs.prepared_record).hexdigest(),
        hashlib.sha256(old_inputs.native_envelope).hexdigest(),
        1,
    )
    (root / "candidate-selection.json").write_bytes(_selection_bytes(old_selected))
    previous_observation = b"independently recheck this old native/pip stage"
    journal = UntrustedUpdateJournal(
        NEW,
        1,
        UpdatePhase.CANDIDATE_VERIFIED,
        NOW - timedelta(seconds=30),
        fresh.stage_relative_path,
        fresh.wheelhouse_relative_path,
        hashlib.sha256(new_inputs.prepared_record).hexdigest(),
        hashlib.sha256(new_inputs.registry_envelope).hexdigest(),
        hashlib.sha256(new_inputs.lock_envelope).hexdigest(),
        hashlib.sha256(new_inputs.native_envelope).hexdigest(),
        hashlib.sha256(previous_observation).hexdigest(),
    )
    (root / "transactions" / f"{NEW}.json").write_bytes(_serialize(journal))
    conn = sqlite3.connect(":memory:", isolation_level=None)
    private = Ed25519PrivateKey.generate()
    store = MonotonicCheckpointStore(
        conn,
        witness_id=WITNESS,
        authorize=lambda installation, operation, context: (
            installation == INSTALL and context == "service"
        ),
        sign=private.sign,
    )
    store.commit_receipt(INSTALL, receipt, context="service")

    def transport(challenge: bytes) -> bytes:
        return store.answer_challenge(challenge, context="service", now=NOW)

    return {
        "software_root": root,
        "classroom_workspace": classroom,
        "transaction_id": NEW,
        "candidate": fresh,
        "candidate_inputs": new_inputs,
        "previous_observation_record": previous_observation,
        "previous_receipt_bytes": receipt,
        "witness_transport": transport,
        "installation_id": INSTALL,
        "pinned_public_key": private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ),
        "expected_witness_id": WITNESS,
        "now": NOW,
    }


def test_valid_read_only_preflight_has_no_launch_authority(
    scenario: dict[str, Any],
) -> None:
    root = scenario["software_root"]
    before = {
        file.relative_to(root): file.read_bytes()
        for file in root.rglob("*")
        if file.is_file()
    }
    result = inspect_witness_bound_update_preflight(**scenario)
    after = {
        file.relative_to(root): file.read_bytes()
        for file in root.rglob("*")
        if file.is_file()
    }
    assert before == after
    assert result.status == "PRECHECK_ONLY_NOT_AUTHORIZED"
    assert result.previous_generation == 1
    assert result.proposed_generation == 2
    assert result.witness_revision == 1
    assert result.transaction_id == NEW
    assert result.prior_stage == "prior/one"
    assert result.candidate_stage == "candidate/two"
    assert not hasattr(result, "can_launch")
    assert not hasattr(result, "activate")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate", None),
        ("candidate_inputs", None),
        ("previous_receipt_bytes", b""),
        ("previous_observation_record", b""),
        ("previous_observation_record", b"x" * 16385),
        ("now", datetime(2026, 10, 20, 18)),
        ("installation_id", "wrong"),
        ("expected_witness_id", "wrong_witness"),
        ("pinned_public_key", b"0" * 32),
        ("minimum_witness_revision", 2),
    ],
)
def test_input_identity_fail_closed(
    scenario: dict[str, Any], field: str, value: Any
) -> None:
    args = {**scenario, field: value}
    with pytest.raises(ActivationPreflightError):
        inspect_witness_bound_update_preflight(**args)


def test_wrong_candidate_transaction_refused(scenario: dict[str, Any]) -> None:
    args = dict(scenario)
    args["candidate"] = replace(args["candidate"], transaction_id="d" * 32)
    with pytest.raises(ActivationPreflightError, match="candidate"):
        inspect_witness_bound_update_preflight(**args)


def test_tampered_candidate_evidence_refused(scenario: dict[str, Any]) -> None:
    args = dict(scenario)
    args["candidate_inputs"] = replace(
        args["candidate_inputs"], prepared_record=b"changed"
    )
    with pytest.raises(ActivationPreflightError, match="candidate"):
        inspect_witness_bound_update_preflight(**args)


def test_locally_edited_prior_receipt_refused(scenario: dict[str, Any]) -> None:
    args = dict(scenario)
    args["previous_receipt_bytes"] = args["previous_receipt_bytes"].replace(
        b'"generation":1', b'"generation":2'
    )
    with pytest.raises(ActivationPreflightError):
        inspect_witness_bound_update_preflight(**args)


def test_wrong_local_old_slot_refused(scenario: dict[str, Any]) -> None:
    root = scenario["software_root"]
    (root / "candidate-selection.json").write_bytes(
        _selection_bytes(
            UntrustedSlotSelection(OLD, "candidate/two", "0" * 64, "0" * 64, 1)
        )
    )
    with pytest.raises(ActivationPreflightError, match="prior"):
        inspect_witness_bound_update_preflight(**scenario)


def test_pending_recovery_blocks_preflight(scenario: dict[str, Any]) -> None:
    (scenario["software_root"] / "pending-slot-recovery.json").write_bytes(b"x")
    with pytest.raises(ActivationPreflightError, match="rejected"):
        inspect_witness_bound_update_preflight(**scenario)


def test_missing_journal_refused(scenario: dict[str, Any]) -> None:
    (scenario["software_root"] / "transactions" / f"{NEW}.json").unlink()
    with pytest.raises(ActivationPreflightError, match="missing"):
        inspect_witness_bound_update_preflight(**scenario)


@pytest.mark.parametrize("phase", [UpdatePhase.ACTIVATION_INTENT, UpdatePhase.ABORTED])
def test_armed_or_aborted_journal_refused(
    scenario: dict[str, Any], phase: UpdatePhase
) -> None:
    root = scenario["software_root"]
    path = root / "transactions" / f"{NEW}.json"
    from paper_data_suite.evergreen_update_journal import _parse

    path.write_bytes(_serialize(replace(_parse(path.read_bytes()), phase=phase)))
    with pytest.raises(ActivationPreflightError, match="armed"):
        inspect_witness_bound_update_preflight(**scenario)


def test_previous_observation_hash_required(scenario: dict[str, Any]) -> None:
    args = dict(scenario)
    args["previous_observation_record"] = b"not matching locally journaled digest"
    with pytest.raises(ActivationPreflightError, match="candidate"):
        inspect_witness_bound_update_preflight(**args)


def test_same_candidate_and_prior_stage_refused(scenario: dict[str, Any]) -> None:
    root = scenario["software_root"]
    path = root / "transactions" / f"{NEW}.json"
    from paper_data_suite.evergreen_update_journal import _parse

    record = _parse(path.read_bytes())
    record = replace(record, stage_relative_path="prior/one")
    path.write_bytes(_serialize(record))
    args = dict(scenario)
    args["candidate"] = replace(args["candidate"], stage_relative_path="prior/one")
    with pytest.raises(ActivationPreflightError, match="overlap"):
        inspect_witness_bound_update_preflight(**args)


def test_unsafe_missing_staged_directory_refused(scenario: dict[str, Any]) -> None:
    (scenario["software_root"] / "candidate" / "two").rmdir()
    with pytest.raises(ActivationPreflightError, match="rejected"):
        inspect_witness_bound_update_preflight(**scenario)


def test_no_network_if_local_selection_wrong(scenario: dict[str, Any]) -> None:
    args = dict(scenario)
    args["witness_transport"] = lambda _: (_ for _ in ()).throw(
        AssertionError("network must not run")
    )
    args["candidate"] = replace(args["candidate"], transaction_id="d" * 32)
    with pytest.raises(ActivationPreflightError, match="candidate"):
        inspect_witness_bound_update_preflight(**args)


def test_no_changes_to_workspace(scenario: dict[str, Any]) -> None:
    workspace = scenario["classroom_workspace"]
    (workspace / "keep.txt").write_text("original student work")
    inspect_witness_bound_update_preflight(**scenario)
    assert (workspace / "keep.txt").read_text() == "original student work"


def test_detect_selection_drift_during_remote_query(scenario: dict[str, Any]) -> None:
    original_transport = scenario["witness_transport"]
    root = scenario["software_root"]

    def drifter(challenge: bytes) -> bytes:
        response = original_transport(challenge)
        (root / "candidate-selection.json").write_bytes(
            _selection_bytes(
                UntrustedSlotSelection(OLD, "prior/one", "0" * 64, "0" * 64, 1)
            )
        )
        return response

    args = dict(scenario)
    args["witness_transport"] = drifter
    with pytest.raises(ActivationPreflightError, match="changed"):
        inspect_witness_bound_update_preflight(**args)


def test_no_execution_or_import_of_provider_during_preflight(
    scenario: dict[str, Any],
) -> None:
    with patch("subprocess.run", side_effect=AssertionError("cannot execute")):
        inspect_witness_bound_update_preflight(**scenario)


def test_nonsigned_witness_response_refused(scenario: dict[str, Any]) -> None:
    args = dict(scenario)
    args["witness_transport"] = lambda _: b"{}"
    with pytest.raises(ActivationPreflightError, match="rejected"):
        inspect_witness_bound_update_preflight(**args)
