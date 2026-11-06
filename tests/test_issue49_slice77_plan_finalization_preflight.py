"""Slice 77: selected successor finalization preflight stays inert and fenced.

The remote/physical Slice-76 inspection is stubbed ONLY in these tests;
previous tests verify the actual TLS, signatures and publisher/native auditors.
The pending proposal, selection, capsule, journal, and signed witness fixture
use their actual repository implementations and real Ed25519 signatures.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_local_receipt_recovery import (
    persist_untrusted_successor_proposal,
)
from paper_data_suite.evergreen_plan_finalization_preflight import (
    PlanFinalizationPreflightError,
    inspect_plan_finalization_preflight,
)
from paper_data_suite.evergreen_plan_forward_recovery import PlanForwardRecoveryReview
from paper_data_suite.evergreen_plan_inert_selection import PlanPendingInertSelection
from paper_data_suite.evergreen_plan_service_admission import (
    PlanSuccessorServiceAdmission,
)
from paper_data_suite.evergreen_plan_service_dispatch import (
    PlanSuccessorServiceSignedRecovery,
)
from paper_data_suite.evergreen_plan_successor_draft import PlanSuccessorDraftReview
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_recovery_observation_https import (
    ProvisionedRecoveryObservationHttpsClient,
)
from paper_data_suite.evergreen_successor_receipt_draft import (
    WitnessBoundSuccessorDraft,
)
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdatePhase,
    _serialize,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)

NOW = datetime(2026, 10, 26, 22, 0, tzinfo=UTC)
INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
WITNESS = "independent_witness"
ACTOR = "independent-service-actor"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        wheels,
        "3" * 64,  # native payload
        "4" * 64,  # pip inventory
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "software"
    classroom = tmp_path / "classroom"
    root.mkdir()
    classroom.mkdir()
    (root / "transactions").mkdir()
    for path in ("prior/one", "prior/wheels", "candidate/two", "candidate/wheels"):
        (root / path).mkdir(parents=True)
    prior = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"prior-prepared",
        registry_envelope=b"prior-registry",
        lock_envelope=b"prior-lock",
        native_envelope=b"prior-native",
        generation=1,
        recorded_at=NOW - timedelta(minutes=3),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"new-prepared",
        registry_envelope=b"new-registry",
        lock_envelope=b"new-lock",
        native_envelope=b"new-native",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, sha(prior)),
    )
    old_selection = _selection_bytes(
        UntrustedSlotSelection(
            PRIOR, "prior/one", sha(b"prior-prepared"), sha(b"prior-native"), 1
        )
    )
    new_selection = _selection_bytes(
        UntrustedSlotSelection(
            NEXT, "candidate/two", sha(b"new-prepared"), sha(b"new-native"), 2
        )
    )
    pointer = root / "candidate-selection.json"
    capsule = root / "pending-slot-recovery.json"
    pointer.write_bytes(new_selection)
    capsule.write_bytes(
        _recovery_bytes(
            PendingSlotRecovery(
                NEXT, old_selection, sha(new_selection), sha(old_selection)
            )
        )
    )
    journal_file = root / "transactions" / f"{NEXT}.json"
    journal_file.write_bytes(
        _serialize(
            UntrustedUpdateJournal(
                NEXT,
                2,
                UpdatePhase.ACTIVATION_INTENT,
                NOW - timedelta(seconds=30),
                "candidate/two",
                "candidate/wheels",
                sha(b"new-prepared"),
                sha(b"new-registry"),
                sha(b"new-lock"),
                sha(b"new-native"),
                sha(b"previous observation"),
            )
        )
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    connection = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        connection,
        witness_id=WITNESS,
        authorize=lambda identity, operation, context: (
            identity == INSTALL and context == ACTOR
        ),
        sign=private.sign,
    )
    store.commit_receipt(INSTALL, prior, context=ACTOR)
    observations: list[bytes] = []

    def witness(challenge: bytes) -> bytes:
        observations.append(challenge)
        return store.answer_challenge(challenge, context=ACTOR, now=NOW)

    persist_untrusted_successor_proposal(
        root,
        classroom_workspace=classroom,
        transaction_id=NEXT,
        draft=WitnessBoundSuccessorDraft(
            NEXT, 1, 2, sha(prior), 1, sha(successor), successor
        ),
        previous_receipt_bytes=prior,
        installation_id=INSTALL,
        witness_id=WITNESS,
        witness_transport=witness,
        pinned_public_key=public,
        now=NOW,
    )
    store.commit_receipt(INSTALL, successor, context=ACTOR)
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, prior, successor)
    raw = serialize_witness_commit_request(request)
    review = PlanSuccessorDraftReview(
        NEXT, INSTALL, 2, 1, 2, 1, sha(prior), sha(successor), sha(raw), raw
    )
    admitted = PlanSuccessorServiceAdmission(
        INSTALL, NEXT, sha(raw), sha(prior), sha(successor), 1, 2, 1
    )
    stopped = PlanSuccessorServiceSignedRecovery(
        INSTALL,
        NEXT,
        sha(raw),
        2,
        sha(successor),
        "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED",
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY",
    )
    selected = PlanPendingInertSelection(NEXT, 2, 1, 2, 1, sha(prior), "candidate/two")
    fresh = PlanForwardRecoveryReview(
        INSTALL,
        NEXT,
        sha(raw),
        sha(successor),
        2,
        2,
        "candidate/two",
        "candidate/wheels",
        "4" * 64,  # pip digest
        "3" * 64,  # native digest
        "9" * 64,
    )
    calls: list[str] = []
    import paper_data_suite.evergreen_plan_finalization_preflight as module

    def independent(*args: Any, **kwargs: Any) -> PlanForwardRecoveryReview:
        calls.append("remote_and_physical_audits")
        return fresh

    monkeypatch.setattr(module, "inspect_plan_bound_forward_recovery", independent)
    args = dict(
        review=review,
        admission=admitted,
        signed_recovery=stopped,
        selected=selected,
        software_root=root,
        classroom_workspace=classroom,
        service_client=object.__new__(ProvisionedRecoveryObservationHttpsClient),
        witness_transport=witness,
        pinned_witness_public_key=public,
        candidate=ProposedCandidateEvidence(
            b"new-prepared", b"new-registry", b"new-lock", b"new-native"
        ),
        candidate_module_envelopes={"quillan": b"synthetic"},
        trust=object.__new__(TrustedKeyring),
        now=NOW,
    )
    return dict(
        args=args,
        fresh=fresh,
        calls=calls,
        observations=observations,
        module=module,
        root=root,
        classroom=classroom,
        pointer=pointer,
        capsule=capsule,
        journal=journal_file,
        store=store,
        proposal=root / "transactions" / f"{NEXT}.successor-proposal.json",
    )


def inspect(scenario: dict[str, Any], **changes: Any) -> Any:
    return inspect_plan_finalization_preflight(**(scenario["args"] | changes))


def baseline_files(scenario: dict[str, Any]) -> dict[str, bytes]:
    return {
        path.relative_to(scenario["root"]).as_posix(): path.read_bytes()
        for path in scenario["root"].rglob("*")
        if path.is_file()
    }


def test_successful_preflight_is_read_only_and_not_a_capability(
    scenario: dict[str, Any],
) -> None:
    (scenario["classroom"] / "student.txt").write_text("untouched")
    before = baseline_files(scenario)
    output = inspect(scenario)
    assert output.installation_id == INSTALL
    assert output.transaction_id == NEXT
    assert output.generation == 2
    assert output.witness_revision == 2
    assert output.successor_sha256 == scenario["args"]["review"].proposed_receipt_sha256
    assert output.proposal_sha256 == sha(scenario["proposal"].read_bytes())
    assert output.selection_sha256 == sha(scenario["pointer"].read_bytes())
    assert output.recovery_capsule_sha256 == sha(scenario["capsule"].read_bytes())
    assert output.journal_sha256 == sha(scenario["journal"].read_bytes())
    assert (
        output.status
        == "LOCAL_FINALIZATION_PREFLIGHT_REVIEW_ONLY_RECOVERY_CAPSULE_REQUIRED"
    )
    assert "NO_RECEIPT_WRITE" in output.authority
    assert not hasattr(output, "commit") and not hasattr(output, "activate")
    assert baseline_files(scenario) == before
    assert (scenario["classroom"] / "student.txt").read_text() == "untouched"
    assert scenario["calls"] == ["remote_and_physical_audits"]
    assert len(scenario["observations"]) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_sha256", "f" * 64),
        ("serialized_request", b"bad"),
        ("transaction_id", "d" * 32),
        ("journal_revision", True),
        ("status", "READY_TO_COMMIT"),
        ("authority", "MAY_LAUNCH"),
    ],
)
def test_untrusted_plan_fails_before_remote(
    scenario: dict[str, Any], field: str, value: Any
) -> None:
    changed = replace(scenario["args"]["review"], **{field: value})
    with pytest.raises(PlanFinalizationPreflightError):
        inspect(scenario, review=changed)
    assert scenario["calls"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("installation_id", "d" * 32),
        ("transaction_id", "d" * 32),
        ("request_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("successor_generation", 3),
        ("witness_revision", 7),
        ("stage_relative_path", "wrong/stage"),
        ("wheelhouse_relative_path", "wrong/wheels"),
        ("pip_inventory_sha256", "f" * 64),
        ("native_payload_sha256", "f" * 64),
        ("signed_service_envelope_sha256", "not-a-digest"),
        ("status", "READY_TO_COMMIT"),
        ("authority", "MAY_LAUNCH"),
    ],
)
def test_forged_fresh_review_does_not_reach_locked_reads(
    scenario: dict[str, Any], field: str, value: Any
) -> None:
    wrong = replace(scenario["fresh"], **{field: value})
    scenario["module"].inspect_plan_bound_forward_recovery = lambda *a, **k: wrong
    before = baseline_files(scenario)
    with pytest.raises(PlanFinalizationPreflightError, match="conflicts"):
        inspect(scenario)
    assert baseline_files(scenario) == before
    assert len(scenario["observations"]) == 1  # only proposal persistence


@pytest.mark.parametrize("file_key", ["proposal", "pointer", "capsule", "journal"])
def test_missing_pending_file_prevents_finalization(
    scenario: dict[str, Any], file_key: str
) -> None:
    scenario[file_key].unlink()
    with pytest.raises(PlanFinalizationPreflightError):
        inspect(scenario)
    assert len(scenario["observations"]) == 1
    assert scenario["calls"] == ["remote_and_physical_audits"]


@pytest.mark.parametrize("file_key", ["proposal", "pointer", "capsule", "journal"])
def test_altered_pending_file_prevents_finalization(
    scenario: dict[str, Any], file_key: str
) -> None:
    scenario[file_key].write_bytes(b"altered local metadata")
    with pytest.raises(PlanFinalizationPreflightError):
        inspect(scenario)
    assert len(scenario["observations"]) == 1


def test_predecessor_only_signed_witness_refuses_forward_preflight(
    scenario: dict[str, Any],
) -> None:
    prior = scenario["args"]["review"].serialized_request
    assert prior
    # The service has a successor, but supplying the wrong installation pin is
    # a safe way to prove no success without authentic signed successor readback.
    with pytest.raises(PlanFinalizationPreflightError):
        inspect(scenario, pinned_witness_public_key=b"x" * 32)
    assert scenario["capsule"].exists()


def test_lock_contention_refuses_without_changing_local_state(
    scenario: dict[str, Any],
) -> None:
    marker = scenario["root"] / "candidate-selection.lock"
    marker.write_bytes(b"existing independent lock")
    before = baseline_files(scenario)
    with pytest.raises(PlanFinalizationPreflightError):
        inspect(scenario)
    assert baseline_files(scenario) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pinned_witness_public_key", b"short"),
        ("witness_transport", None),
        ("now", datetime(2026, 10, 26)),
        ("software_root", "unsafe"),
    ],
)
def test_bad_independent_inputs_refused_before_remote(
    scenario: dict[str, Any], field: str, value: Any
) -> None:
    with pytest.raises(PlanFinalizationPreflightError):
        inspect(scenario, **{field: value})
    assert scenario["calls"] == []


def test_independent_inspector_fails_closed(scenario: dict[str, Any]) -> None:
    from paper_data_suite.evergreen_plan_forward_recovery import (
        PlanForwardRecoveryError,
    )

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PlanForwardRecoveryError("service down")

    scenario["module"].inspect_plan_bound_forward_recovery = fail
    with pytest.raises(PlanFinalizationPreflightError, match="independent service"):
        inspect(scenario)
    assert scenario["capsule"].exists()


def test_full_inspection_expiry_fails_before_local_lock(
    scenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import paper_data_suite.evergreen_plan_finalization_preflight as module

    clock = iter([0.0, 31.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    with pytest.raises(PlanFinalizationPreflightError, match="conflicts"):
        inspect(scenario)
    assert len(scenario["observations"]) == 1
