"""Slice 88: protected postdelete inspection and one-shot certificate.

Exercise real Slice 78-87 SQLite, witness, capsule and dispatch contracts.
Synthetic callbacks are NOT OS-service security or durability acceptance.
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

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_plan_capsule_clearance_preflight import (
    IndependentlyHeldCapsule,
    ProtectedCapsuleClearancePreflightLedger,
)
from paper_data_suite.evergreen_plan_capsule_delete_dispatch import (
    CapsuleDeleteDispatchError,
    IndependentCapsuleDeleteReadback,
    ProtectedCapsuleDeleteDispatcher,
)
from paper_data_suite.evergreen_plan_capsule_postdelete_reconciliation import (
    CapsulePostdeleteReconciliationError,
    IndependentDeleteTerminationEvidence,
    ProtectedCapsulePostdeleteReconciler,
    _claim_hash,
)
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    ProtectedCapsulePredeleteUncertaintyLedger,
)
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationEvidence,
    ProtectedPlanFinalizationFence,
)
from paper_data_suite.evergreen_plan_finalization_preflight import (
    PlanFinalizationPreflight,
)
from paper_data_suite.evergreen_plan_local_convergence import (
    IndependentNoInflightEvidence,
    ProtectedLocalConvergenceCoordinator,
)
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    IndependentLocalDeploymentInspection,
    ProtectedLocalReceiptDeploymentPlanner,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    IndependentLocalReceiptReadback,
    ProtectedLocalPrewriteUncertaintyLedger,
)
from paper_data_suite.evergreen_plan_local_receipt_dispatch import (
    ProtectedLocalReceiptDispatcher,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedPlanReceiptWriter,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    ProtectedPlanPublicationPreclaimLedger,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)

INSTALL = "a" * 32
PRIOR = "b" * 32
NEXT = "c" * 32
ACTOR = "protected-service"
NOW = datetime(2026, 10, 26, 23, tzinfo=UTC)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate(tx: str, stage: str, wheels: str) -> ObservedJournalPipCandidate:
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
def scene(tmp_path: Path) -> dict[str, Any]:
    old = make_untrusted_active_receipt(
        candidate(PRIOR, "prior/one", "prior/wheels"),
        prepared_record=b"old-p",
        registry_envelope=b"old-r",
        lock_envelope=b"old-l",
        native_envelope=b"old-n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    new = make_untrusted_active_receipt(
        candidate(NEXT, "candidate/two", "candidate/wheels"),
        prepared_record=b"new-p",
        registry_envelope=b"new-r",
        lock_envelope=b"new-l",
        native_envelope=b"new-n",
        generation=2,
        recorded_at=NOW,
        previous=ExternallyPinnedReceiptHead(1, sha(old)),
    )
    request = WitnessCommitRequest(INSTALL, "independent_witness", 1, old, new)
    raw = serialize_witness_commit_request(request)
    preflight = PlanFinalizationPreflight(
        INSTALL,
        NEXT,
        sha(raw),
        sha(new),
        2,
        2,
        "5" * 64,
        "6" * 64,
        sha(b"must-remain"),
        "8" * 64,
        "9" * 64,
    )
    evidence = IndependentFinalizationEvidence(
        preflight.installation_id,
        preflight.transaction_id,
        preflight.request_sha256,
        preflight.successor_sha256,
        preflight.generation,
        preflight.witness_revision,
        preflight.proposal_sha256,
        preflight.selection_sha256,
        preflight.recovery_capsule_sha256,
        preflight.journal_sha256,
        preflight.service_envelope_sha256,
        "d" * 64,
        True,
        True,
        True,
    )
    protected = tmp_path / "service"
    protected.mkdir()
    path = protected / "protected.sqlite3"
    db = sqlite3.connect(path, isolation_level=None)
    operations: list[str] = []

    def authorize(install: str, operation: str, context: object) -> bool:
        operations.append(operation)
        return install == INSTALL and context == ACTOR

    def reader(
        req: WitnessCommitRequest, context: object
    ) -> IndependentFinalizationEvidence:
        assert req == request and context == ACTOR
        operations.append("independent_evidence")
        return evidence

    fence = ProtectedPlanFinalizationFence(db, authorize=authorize)
    reservation = fence.reserve(
        raw, preflight, service_context=ACTOR, independently_read_evidence=reader
    )
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    preclaim = preclaims.preclaim_once(
        raw, reservation, service_context=ACTOR, independently_read_evidence=reader
    )
    writer = ProtectedPlanReceiptWriter(preclaims)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    witness_db = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        witness_db,
        witness_id="independent_witness",
        authorize=lambda install, operation, context: (
            install == INSTALL and context == ACTOR
        ),
        sign=key.sign,
    )
    store.commit_receipt(INSTALL, old, context=ACTOR)
    store.commit_receipt(INSTALL, new, context=ACTOR)
    witness_reads: list[str] = []

    def witness(challenge: bytes) -> bytes:
        witness_reads.append("signed_witness")
        return store.answer_challenge(challenge, context=ACTOR, now=NOW)

    local = tmp_path / "teacher-local"
    local.mkdir()
    (local / "pending-slot-recovery.json").write_bytes(b"must-remain")
    (local / "student-work.txt").write_bytes(b"untouched")
    return dict(
        old=old,
        new=new,
        raw=raw,
        reservation=reservation,
        preclaim=preclaim,
        db=db,
        db_path=path,
        fence=fence,
        preclaims=preclaims,
        writer=writer,
        public=public,
        reader=reader,
        authorize=authorize,
        witness=witness,
        witness_reads=witness_reads,
        operations=operations,
        local=local,
    )


TARGET = sha(b"independently configured local active receipt path")


@pytest.fixture
def ready(scene: dict[str, Any]) -> dict[str, Any]:
    record = scene["writer"].record_once(
        scene["raw"],
        scene["reservation"],
        scene["preclaim"],
        service_context=ACTOR,
        independently_read_evidence=scene["reader"],
        witness_transport=scene["witness"],
        pinned_public_key=scene["public"],
        now=NOW,
    )
    scene["record"] = record
    scene["planner"] = ProtectedLocalReceiptDeploymentPlanner(scene["writer"])
    active = scene["local"] / "active-receipt.json"
    active.write_bytes(scene["old"])
    scene["active"] = active
    physical_calls: list[str] = []

    def inspect(
        request: WitnessCommitRequest, context: object
    ) -> IndependentLocalDeploymentInspection:
        assert context == ACTOR
        physical_calls.append("read-protected-local-state")
        capsule = (scene["local"] / "pending-slot-recovery.json").read_bytes()
        local = active.read_bytes()
        return IndependentLocalDeploymentInspection(
            request.installation_id,
            scene["reservation"].transaction_id,
            scene["reservation"].request_sha256,
            request.successor_sha256,
            request.predecessor_sha256,
            sha(local),
            TARGET,
            scene["reservation"].proposal_sha256,
            scene["reservation"].selection_sha256,
            scene["reservation"].recovery_capsule_sha256,
            scene["reservation"].journal_sha256,
            sha(local + capsule),
            True,
            True,
            True,
            True,
        )

    scene["physical_reader"] = inspect
    scene["physical_calls"] = physical_calls
    return scene


def prepare(ready: dict[str, Any], **changes: Any) -> Any:
    inputs: dict[str, Any] = {
        "request_bytes": ready["raw"],
        "reservation": ready["reservation"],
        "preclaim": ready["preclaim"],
        "record": ready["record"],
        "service_context": ACTOR,
        "independently_read_evidence": ready["reader"],
        "independently_read_local": ready["physical_reader"],
        "pinned_target_identity_sha256": TARGET,
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["planner"].prepare_once(**(inputs | changes))


@pytest.fixture
def prepared(ready: dict[str, Any]) -> dict[str, Any]:
    ready["intent"] = prepare(ready)
    ready["ledger"] = ProtectedLocalPrewriteUncertaintyLedger(ready["planner"])
    seen: list[str] = []

    def read_local(
        request: WitnessCommitRequest, context: object
    ) -> IndependentLocalReceiptReadback:
        assert context == ACTOR
        seen.append("protected-readback")
        active = ready["active"]
        return IndependentLocalReceiptReadback(
            request.installation_id,
            ready["reservation"].transaction_id,
            ready["reservation"].request_sha256,
            TARGET,
            active.read_bytes() if active.exists() else None,
            ready["reservation"].proposal_sha256,
            ready["reservation"].selection_sha256,
            ready["reservation"].recovery_capsule_sha256,
            ready["reservation"].journal_sha256,
            True,
            active.is_file(),
            (ready["local"] / "pending-slot-recovery.json").is_file(),
            True,
            True,
        )

    ready["read_local"] = read_local
    ready["read_calls"] = seen
    return ready


def arm(prepared: dict[str, Any], **changes: Any) -> Any:
    inputs = {
        "request_bytes": prepared["raw"],
        "reservation": prepared["reservation"],
        "preclaim": prepared["preclaim"],
        "record": prepared["record"],
        "intent": prepared["intent"],
        "service_context": ACTOR,
        "independently_read_evidence": prepared["reader"],
        "independently_read_local": prepared["physical_reader"],
        "witness_transport": prepared["witness"],
        "pinned_public_key": prepared["public"],
        "now": NOW,
    }
    return prepared["ledger"].arm_once(**(inputs | changes))


def classify(prepared: dict[str, Any], **changes: Any) -> Any:
    inputs = {
        "request_bytes": prepared["raw"],
        "reservation": prepared["reservation"],
        "preclaim": prepared["preclaim"],
        "record": prepared["record"],
        "intent": prepared["intent"],
        "service_context": ACTOR,
        "independently_read_evidence": prepared["reader"],
        "independently_read_local_receipt": prepared["read_local"],
        "witness_transport": prepared["witness"],
        "pinned_public_key": prepared["public"],
        "now": NOW,
    }
    return prepared["ledger"].inspect_after_uncertainty(**(inputs | changes))


@pytest.fixture
def armed(prepared: dict[str, Any]) -> dict[str, Any]:
    prepared["marker"] = arm(prepared)
    prepared["dispatcher"] = ProtectedLocalReceiptDispatcher(prepared["ledger"])
    writes: list[str] = []

    def protected_write(
        req: WitnessCommitRequest, target: str, context: object
    ) -> None:
        assert context == ACTOR and target == TARGET
        assert req.successor_receipt_bytes == prepared["new"]
        assert prepared["active"].read_bytes() == prepared["old"]
        assert (
            prepared["dispatcher"].observe(INSTALL, service_context=ACTOR) is not None
        )
        writes.append("one-protected-file-operation")
        prepared["active"].write_bytes(req.successor_receipt_bytes)

    prepared["write"] = protected_write
    prepared["writes"] = writes
    return prepared


def dispatch(armed: dict[str, Any], **changes: Any) -> Any:
    kwargs: dict[str, Any] = {
        "request_bytes": armed["raw"],
        "reservation": armed["reservation"],
        "preclaim": armed["preclaim"],
        "record": armed["record"],
        "intent": armed["intent"],
        "marker": armed["marker"],
        "service_context": ACTOR,
        "independently_read_evidence": armed["reader"],
        "independently_read_local_receipt": armed["read_local"],
        "witness_transport": armed["witness"],
        "pinned_public_key": armed["public"],
        "now": NOW,
        "service_owned_write": armed["write"],
    }
    return armed["dispatcher"].dispatch_once(**(kwargs | changes))


@pytest.fixture
def completed(armed: dict[str, Any]) -> dict[str, Any]:
    dispatch(armed)
    armed["claim"] = armed["dispatcher"].observe(INSTALL, service_context=ACTOR)
    armed["convergence"] = ProtectedLocalConvergenceCoordinator(armed["dispatcher"])
    calls: list[str] = []

    def quiet(req: WitnessCommitRequest, ctx: object) -> IndependentNoInflightEvidence:
        assert req.installation_id == INSTALL and ctx == ACTOR
        calls.append("independent-no-inflight")
        from paper_data_suite.evergreen_plan_local_convergence import _claim_hash

        return IndependentNoInflightEvidence(
            INSTALL,
            NEXT,
            _claim_hash(armed["claim"]),
            TARGET,
            "f" * 64,
            "e" * 64,
            True,
            True,
            True,
            True,
            True,
        )

    armed["quiet"] = quiet
    armed["quiet_calls"] = calls
    return armed


def reconcile(ready: dict[str, Any], *, certify: bool = False, **updates: Any) -> Any:
    args: dict[str, Any] = {
        "request_bytes": ready["raw"],
        "reservation": ready["reservation"],
        "preclaim": ready["preclaim"],
        "record": ready["record"],
        "intent": ready["intent"],
        "marker": ready["marker"],
        "claim": ready["claim"],
        "service_context": ACTOR,
        "independently_read_evidence": ready["reader"],
        "independently_read_local_receipt": ready["read_local"],
        "independently_confirm_quiescence": ready["quiet"],
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    method = (
        ready["convergence"].certify_once if certify else ready["convergence"].inspect
    )
    return method(**(args | updates))


CAPSULE_ID = sha(b"independently pinned recovery capsule file identity")


@pytest.fixture
def converged(completed: dict[str, Any]) -> dict[str, Any]:
    completed["certified"] = reconcile(completed, certify=True)
    completed["clearance"] = ProtectedCapsuleClearancePreflightLedger(
        completed["convergence"]
    )
    reads: list[str] = []

    def capsule(req: WitnessCommitRequest, ctx: object) -> IndependentlyHeldCapsule:
        assert req.installation_id == INSTALL and ctx == ACTOR
        reads.append("independent capsule physical read")
        return IndependentlyHeldCapsule(
            INSTALL,
            NEXT,
            CAPSULE_ID,
            (completed["local"] / "pending-slot-recovery.json").read_bytes(),
            True,
            True,
            True,
            True,
        )

    completed["capsule_reader"] = capsule
    completed["capsule_reads"] = reads
    return completed


def prepare_clearance(ready: dict[str, Any], **changes: Any) -> Any:
    kwargs: dict[str, Any] = {
        "request_bytes": ready["raw"],
        "reservation": ready["reservation"],
        "preclaim": ready["preclaim"],
        "record": ready["record"],
        "intent": ready["intent"],
        "marker": ready["marker"],
        "claim": ready["claim"],
        "convergence": ready["certified"],
        "service_context": ACTOR,
        "independently_read_evidence": ready["reader"],
        "independently_read_local_receipt": ready["read_local"],
        "independently_confirm_quiescence": ready["quiet"],
        "independently_read_capsule": ready["capsule_reader"],
        "pinned_capsule_identity_sha256": CAPSULE_ID,
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["clearance"].prepare_once(**(kwargs | changes))


@pytest.fixture
def clearance_ready(converged: dict[str, Any]) -> dict[str, Any]:
    converged["preflight"] = prepare_clearance(converged)
    converged["predelete"] = ProtectedCapsulePredeleteUncertaintyLedger(
        converged["clearance"]
    )
    return converged


def arm_predelete(ready: dict[str, Any], **changes: Any) -> Any:
    args: dict[str, Any] = {
        "request_bytes": ready["raw"],
        "reservation": ready["reservation"],
        "preclaim": ready["preclaim"],
        "record": ready["record"],
        "intent": ready["intent"],
        "marker": ready["marker"],
        "claim": ready["claim"],
        "convergence": ready["certified"],
        "clearance_preflight": ready["preflight"],
        "service_context": ACTOR,
        "independently_read_evidence": ready["reader"],
        "independently_read_local_receipt": ready["read_local"],
        "independently_confirm_quiescence": ready["quiet"],
        "independently_read_capsule": ready["capsule_reader"],
        "pinned_capsule_identity_sha256": CAPSULE_ID,
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["predelete"].arm_once(**(args | changes))


@pytest.fixture
def delete_ready(clearance_ready: dict[str, Any]) -> dict[str, Any]:
    ready = clearance_ready
    ready["delete_marker"] = arm_predelete(ready)
    ready["deleter"] = ProtectedCapsuleDeleteDispatcher(ready["predelete"])
    ready["delete_calls"] = []
    ready["post_calls"] = []

    def delete(req: WitnessCommitRequest, identity: str, context: object) -> None:
        assert req.installation_id == INSTALL and context == ACTOR
        assert identity == CAPSULE_ID
        assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is not None
        assert ready["active"].read_bytes() == ready["new"]
        ready["delete_calls"].append("one-service-deletion")
        (ready["local"] / "pending-slot-recovery.json").unlink()

    def post(
        req: WitnessCommitRequest, context: object
    ) -> IndependentCapsuleDeleteReadback:
        assert req.installation_id == INSTALL and context == ACTOR
        ready["post_calls"].append("independent-postdelete")
        capsule = ready["local"] / "pending-slot-recovery.json"
        return IndependentCapsuleDeleteReadback(
            INSTALL,
            NEXT,
            CAPSULE_ID,
            TARGET,
            ready["active"].read_bytes() if ready["active"].exists() else None,
            capsule.read_bytes() if capsule.exists() else None,
            ready["reservation"].proposal_sha256,
            ready["reservation"].selection_sha256,
            ready["reservation"].journal_sha256,
            True,
            True,
            not capsule.exists(),
            True,
            True,
            True,
            True,
            True,
        )

    ready["delete"] = delete
    ready["post"] = post
    return ready


def run_delete(ready: dict[str, Any], **changes: Any) -> Any:
    args: dict[str, Any] = {
        "request_bytes": ready["raw"],
        "reservation": ready["reservation"],
        "preclaim": ready["preclaim"],
        "record": ready["record"],
        "intent": ready["intent"],
        "marker": ready["marker"],
        "claim": ready["claim"],
        "convergence": ready["certified"],
        "clearance_preflight": ready["preflight"],
        "predelete_marker": ready["delete_marker"],
        "service_context": ACTOR,
        "independently_read_evidence": ready["reader"],
        "independently_read_local_receipt": ready["read_local"],
        "independently_confirm_quiescence": ready["quiet"],
        "independently_read_capsule": ready["capsule_reader"],
        "independently_read_postdelete": ready["post"],
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
        "service_owned_delete": ready["delete"],
    }
    return ready["deleter"].dispatch_once(**(args | changes))


def postdelete_context(ready: dict[str, Any]) -> dict[str, Any]:
    ready["delete_claim"] = ready["deleter"].observe(INSTALL, service_context=ACTOR)
    ready["postdelete_api"] = ProtectedCapsulePostdeleteReconciler(ready["deleter"])
    ready["termination_calls"] = []

    def termination(
        req: WitnessCommitRequest, context: object
    ) -> IndependentDeleteTerminationEvidence:
        assert req.installation_id == INSTALL and context == ACTOR
        ready["termination_calls"].append("independent-delete-termination")
        return IndependentDeleteTerminationEvidence(
            INSTALL,
            NEXT,
            _claim_hash(ready["delete_claim"]),
            CAPSULE_ID,
            "d" * 64,
            "e" * 64,
            True,
            True,
            True,
            True,
            True,
        )

    ready["termination_reader"] = termination
    return ready


@pytest.fixture
def postdelete_ready(delete_ready: dict[str, Any]) -> dict[str, Any]:
    run_delete(delete_ready)
    return postdelete_context(delete_ready)


def verify_postdelete(
    ready: dict[str, Any], *, certify: bool = False, **updates: Any
) -> Any:
    kwargs: dict[str, Any] = {
        "request_bytes": ready["raw"],
        "reservation": ready["reservation"],
        "preclaim": ready["preclaim"],
        "record": ready["record"],
        "intent": ready["intent"],
        "marker": ready["marker"],
        "claim": ready["claim"],
        "convergence": ready["certified"],
        "clearance_preflight": ready["preflight"],
        "predelete_marker": ready["delete_marker"],
        "delete_claim": ready["delete_claim"],
        "service_context": ACTOR,
        "independently_read_postdelete": ready["post"],
        "independently_confirm_delete_termination": ready["termination_reader"],
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    api = ready["postdelete_api"]
    return (api.certify_once if certify else api.inspect)(**(kwargs | updates))


def test_read_only_absence_no_launch_and_no_certificate(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    before = ready["local"] / "student-work.txt"
    previous = before.read_bytes()
    result = verify_postdelete(ready)
    assert result.status == "CAPSULE_ABSENT_PENDING_PROTECTED_CERTIFICATION"
    assert result.authority.startswith("NO_REDELETE")
    assert result.observed_capsule_sha256 is None
    assert ready["postdelete_api"].observe(INSTALL, service_context=ACTOR) is None
    assert ready["termination_calls"] == ["independent-delete-termination"] * 2
    assert before.read_bytes() == previous
    assert len(ready["delete_calls"]) == 1


def test_certify_once_binds_claim_and_independent_termination(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    record = verify_postdelete(ready, certify=True)
    assert record.status == "CAPSULE_POSTDELETE_RECONCILED_NO_LAUNCH_AUTHORITY"
    assert record.authority.startswith("NO_REDELETE")
    assert record.delete_claim_sha256 == _claim_hash(ready["delete_claim"])
    assert record.successor_sha256 == sha(ready["new"])
    assert len(record.writer_termination_evidence_sha256) == 64
    assert record == ready["postdelete_api"].observe(INSTALL, service_context=ACTOR)
    assert ready["active"].read_bytes() == ready["new"]
    assert len(ready["delete_calls"]) == 1
    assert not any(
        hasattr(ready["postdelete_api"], name)
        for name in (
            "delete",
            "retry",
            "redispatch",
            "launch",
            "activate",
            "switch",
            "rollback",
        )
    )


def test_replay_refused_before_further_service_reads(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    first = verify_postdelete(ready, certify=True)
    before = len(ready["termination_calls"])
    with pytest.raises(CapsulePostdeleteReconciliationError, match="already certified"):
        verify_postdelete(ready, certify=True)
    assert len(ready["termination_calls"]) == before
    assert first == ready["postdelete_api"].observe(INSTALL, service_context=ACTOR)


@pytest.mark.parametrize(
    "state,status",
    (
        ("original", "CAPSULE_PRESENT_NO_DELETE_RETRY_AUTHORITY"),
        ("unexpected", "CAPSULE_UNKNOWN_QUARANTINE_REQUIRED"),
    ),
)
def test_remaining_or_unknown_capsule_never_certified(
    postdelete_ready: dict[str, Any],
    state: str,
    status: str,
) -> None:
    ready = postdelete_ready
    path = ready["local"] / "pending-slot-recovery.json"
    payload = b"must-remain" if state == "original" else b"changed-capsule"
    path.write_bytes(payload)
    result = verify_postdelete(ready)
    assert result.status == status
    assert result.observed_capsule_sha256 == sha(payload)
    with pytest.raises(CapsulePostdeleteReconciliationError, match="absence"):
        verify_postdelete(ready, certify=True)
    assert ready["postdelete_api"].observe(INSTALL, service_context=ACTOR) is None
    assert len(ready["delete_calls"]) == 1


@pytest.mark.parametrize(
    "field",
    (
        "all_prior_delete_operations_terminated",
        "exclusive_directory_fence_held",
        "no_unaccounted_deleter_or_writer_in_flight",
        "directory_durability_independently_verified",
        "active_successor_physically_reaudited",
    ),
)
def test_failed_termination_fence_refused(
    postdelete_ready: dict[str, Any],
    field: str,
) -> None:
    original = postdelete_ready["termination_reader"]

    def untrusted(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(CapsulePostdeleteReconciliationError, match="in flight"):
        verify_postdelete(
            postdelete_ready, independently_confirm_delete_termination=untrusted
        )
    with pytest.raises(CapsulePostdeleteReconciliationError, match="in flight"):
        verify_postdelete(
            postdelete_ready,
            certify=True,
            independently_confirm_delete_termination=untrusted,
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("delete_claim_sha256", "f" * 64),
        ("capsule_identity_sha256", "f" * 64),
        ("deletion_fence_sha256", "broken"),
        ("deletion_termination_sha256", "broken"),
        ("installation_id", "b" * 32),
        ("transaction_id", "b" * 32),
    ),
)
def test_forged_termination_evidence_refused(
    postdelete_ready: dict[str, Any],
    field: str,
    value: str,
) -> None:
    original = postdelete_ready["termination_reader"]

    def forged(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: value})

    with pytest.raises(CapsulePostdeleteReconciliationError, match="in flight"):
        verify_postdelete(
            postdelete_ready, independently_confirm_delete_termination=forged
        )


@pytest.mark.parametrize(
    "field",
    (
        "parent_directory_protected",
        "active_receipt_protected_regular_file",
        "exclusive_service_fences_held",
        "all_delete_operations_terminated",
        "no_unaccounted_capsule_writer_in_flight",
        "directory_durability_independently_checked",
        "candidate_physical_bytes_reaudited",
    ),
)
def test_unsafe_postdelete_reader_refused(
    postdelete_ready: dict[str, Any],
    field: str,
) -> None:
    original = postdelete_ready["post"]

    def forged(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(CapsulePostdeleteReconciliationError, match="fence"):
        verify_postdelete(postdelete_ready, independently_read_postdelete=forged)


@pytest.mark.parametrize(
    "field,value",
    (
        ("active_receipt_bytes", b"predecessor"),
        ("target_identity_sha256", "f" * 64),
        ("capsule_identity_sha256", "f" * 64),
        ("selection_sha256", "f" * 64),
        ("capsule_absence_independently_confirmed", False),
    ),
)
def test_wrong_postdelete_target_or_receipt_refused(
    postdelete_ready: dict[str, Any],
    field: str,
    value: object,
) -> None:
    original = postdelete_ready["post"]

    def forged(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: value})

    with pytest.raises(CapsulePostdeleteReconciliationError, match="changed active"):
        verify_postdelete(postdelete_ready, independently_read_postdelete=forged)


def test_drift_between_independent_samples_refuses_certificate(
    postdelete_ready: dict[str, Any],
) -> None:
    original = postdelete_ready["post"]
    count = 0

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal count
        count += 1
        if count == 2:
            path = postdelete_ready["local"] / "pending-slot-recovery.json"
            path.write_bytes(b"untrusted")
        return original(req, ctx)

    with pytest.raises(CapsulePostdeleteReconciliationError, match="drifted"):
        verify_postdelete(
            postdelete_ready, certify=True, independently_read_postdelete=drift
        )
    assert (
        postdelete_ready["postdelete_api"].observe(INSTALL, service_context=ACTOR)
        is None
    )


def test_witness_key_refused(postdelete_ready: dict[str, Any]) -> None:
    other_key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(CapsulePostdeleteReconciliationError, match="signed"):
        verify_postdelete(postdelete_ready, pinned_public_key=other_key)


def test_missing_durable_delete_claim_refused(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    ready["db"].execute("DELETE FROM plan_capsule_delete_dispatch_v1")
    with pytest.raises(CapsulePostdeleteReconciliationError, match="chain changed"):
        verify_postdelete(ready, certify=True)


@pytest.mark.parametrize(
    "field",
    (
        "predelete_marker_sha256",
        "capsule_identity_sha256",
        "successor_sha256",
        "status",
        "authority",
    ),
)
def test_forged_dispatch_claim_refused(
    postdelete_ready: dict[str, Any],
    field: str,
) -> None:
    claim = replace(postdelete_ready["delete_claim"], **{field: "f" * 64})
    with pytest.raises(CapsulePostdeleteReconciliationError, match="noncanonical"):
        verify_postdelete(postdelete_ready, delete_claim=claim)


@pytest.mark.parametrize("context", (None, "teacher", "other-service", True))
def test_unauthorized_actor_refused(
    postdelete_ready: dict[str, Any],
    context: object,
) -> None:
    with pytest.raises(CapsulePostdeleteReconciliationError, match="authorization"):
        verify_postdelete(postdelete_ready, service_context=context)


def test_sqlite_transaction_open_refused(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    ready["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(CapsulePostdeleteReconciliationError, match="runtime"):
            verify_postdelete(ready, certify=True)
    finally:
        ready["db"].execute("ROLLBACK")


def test_reopened_database_preserves_certificate(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    certificate = verify_postdelete(ready, certify=True)
    ready["db"].close()
    db = sqlite3.connect(ready["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=ready["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    uncertainty = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatcher = ProtectedLocalReceiptDispatcher(uncertainty)
    convergence = ProtectedLocalConvergenceCoordinator(dispatcher)
    preflight = ProtectedCapsuleClearancePreflightLedger(convergence)
    predelete = ProtectedCapsulePredeleteUncertaintyLedger(preflight)
    deleter = ProtectedCapsuleDeleteDispatcher(predelete)
    reopened = ProtectedCapsulePostdeleteReconciler(deleter)
    assert reopened.observe(INSTALL, service_context=ACTOR) == certificate
    db.close()


def test_corrupt_stored_certificate_refused(
    postdelete_ready: dict[str, Any],
) -> None:
    ready = postdelete_ready
    verify_postdelete(ready, certify=True)
    with pytest.raises(sqlite3.IntegrityError):
        ready["db"].execute(
            "UPDATE plan_capsule_postdelete_reconciliation_v1 SET status='READY' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    ready["db"].execute(
        "UPDATE plan_capsule_postdelete_reconciliation_v1 "
        "SET absence_evidence_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(CapsulePostdeleteReconciliationError, match="corrupt"):
        ready["postdelete_api"].observe(INSTALL, service_context=ACTOR)


def test_lost_delete_ack_reconciles_without_redispatch(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    original = ready["delete"]

    def lost(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        original(req, target, ctx)
        raise OSError("lost delete acknowledgment")

    with pytest.raises(CapsuleDeleteDispatchError, match="outcome uncertain"):
        run_delete(ready, service_owned_delete=lost)
    postdelete_context(ready)
    certificate = verify_postdelete(ready, certify=True)
    assert certificate.status == "CAPSULE_POSTDELETE_RECONCILED_NO_LAUNCH_AUTHORITY"
    assert ready["delete_calls"] == ["one-service-deletion"]


def test_noop_delete_is_diagnostic_not_retryable(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready

    def no_op(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        ready["delete_calls"].append("no-op")

    with pytest.raises(CapsuleDeleteDispatchError, match="not verified"):
        run_delete(ready, service_owned_delete=no_op)
    postdelete_context(ready)
    inspected = verify_postdelete(ready)
    assert inspected.status == "CAPSULE_PRESENT_NO_DELETE_RETRY_AUTHORITY"
    with pytest.raises(CapsulePostdeleteReconciliationError, match="absence"):
        verify_postdelete(ready, certify=True)
    assert ready["delete_calls"] == ["no-op"]
