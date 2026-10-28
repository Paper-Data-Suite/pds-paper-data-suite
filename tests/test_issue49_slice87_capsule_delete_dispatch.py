"""Slice 87: one-shot protected capsule deletion dispatch.

Exercises real Slice 78-86 SQLite and Ed25519 witness paths. Test callbacks
are simulated only: they do not constitute an OS-protected service.
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


def test_one_shot_claim_precedes_deletion_and_only_diagnostic(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is None
    other_before = (ready["local"] / "student-work.txt").read_bytes()
    result = run_delete(ready)
    assert result.status == "CAPSULE_ABSENT_POSTDELETE_RECONCILIATION_REQUIRED"
    assert result.authority.startswith("NO_REDELETE")
    assert ready["delete_calls"] == ["one-service-deletion"]
    assert ready["post_calls"] == ["independent-postdelete"]
    assert not (ready["local"] / "pending-slot-recovery.json").exists()
    assert ready["active"].read_bytes() == ready["new"]
    assert (ready["local"] / "student-work.txt").read_bytes() == other_before
    durable = ready["deleter"].observe(INSTALL, service_context=ACTOR)
    assert durable is not None
    assert durable.status == "CAPSULE_DELETE_DISPATCH_CLAIMED_OUTCOME_UNCERTAIN"
    assert durable.predelete_marker_sha256 != durable.clearance_preflight_sha256
    assert (
        ready["predelete"].observe(INSTALL, service_context=ACTOR)
        == ready["delete_marker"]
    )
    assert not any(
        hasattr(ready["deleter"], k)
        for k in (
            "launch",
            "rollback",
            "retry",
            "clear",
            "activate",
            "switch",
        )
    )


def test_replay_never_dispatches_again(delete_ready: dict[str, Any]) -> None:
    ready = delete_ready
    run_delete(ready)
    with pytest.raises(CapsuleDeleteDispatchError, match="already claimed"):
        run_delete(ready)
    assert len(ready["delete_calls"]) == 1


def test_lost_delete_ack_keeps_claim_and_no_retry(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    base = ready["delete"]

    def lost(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        base(req, target, ctx)
        raise OSError("lost ACK after deletion")

    with pytest.raises(CapsuleDeleteDispatchError, match="outcome uncertain"):
        run_delete(ready, service_owned_delete=lost)
    assert len(ready["delete_calls"]) == 1
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is not None
    with pytest.raises(CapsuleDeleteDispatchError, match="already claimed"):
        run_delete(ready)


def test_callback_returns_without_deletion_is_uncertain(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready

    def noop(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        ready["delete_calls"].append("noop")

    with pytest.raises(CapsuleDeleteDispatchError, match="not verified"):
        run_delete(ready, service_owned_delete=noop)
    assert (ready["local"] / "pending-slot-recovery.json").is_file()
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is not None
    with pytest.raises(CapsuleDeleteDispatchError, match="already claimed"):
        run_delete(ready)


def test_postdelete_reader_outage_no_second_dispatch(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready

    def outage(req: WitnessCommitRequest, ctx: object) -> Any:
        raise OSError("postdelete reader unavailable")

    with pytest.raises(CapsuleDeleteDispatchError, match="verification unavailable"):
        run_delete(ready, independently_read_postdelete=outage)
    assert ready["delete_calls"] == ["one-service-deletion"]
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is not None


@pytest.mark.parametrize(
    "field",
    [
        "capsule_absence_independently_confirmed",
        "exclusive_service_fences_held",
        "all_delete_operations_terminated",
        "no_unaccounted_capsule_writer_in_flight",
        "directory_durability_independently_checked",
        "candidate_physical_bytes_reaudited",
        "parent_directory_protected",
        "active_receipt_protected_regular_file",
    ],
)
def test_unproven_postdelete_fence_refused(
    delete_ready: dict[str, Any],
    field: str,
) -> None:
    ready = delete_ready
    post = ready["post"]

    def forged(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(post(req, ctx), **{field: False})

    with pytest.raises(CapsuleDeleteDispatchError, match="not verified"):
        run_delete(ready, independently_read_postdelete=forged)
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("capsule_identity_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("selection_sha256", "f" * 64),
        ("active_receipt_bytes", b"incorrect"),
        ("capsule_bytes", b"unexpected"),
    ],
)
def test_wrong_postdelete_identity_or_bytes_refused(
    delete_ready: dict[str, Any],
    field: str,
    value: object,
) -> None:
    ready = delete_ready
    post = ready["post"]

    def forged(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(post(req, ctx), **{field: value})

    with pytest.raises(CapsuleDeleteDispatchError, match="not verified"):
        run_delete(ready, independently_read_postdelete=forged)


@pytest.mark.parametrize(
    "field",
    [
        "clearance_preflight_sha256",
        "capsule_identity_sha256",
        "recovery_capsule_sha256",
        "target_identity_sha256",
        "independent_fence_sha256",
        "successor_sha256",
        "status",
        "authority",
    ],
)
def test_forged_predelete_refused_before_dispatch(
    delete_ready: dict[str, Any],
    field: str,
) -> None:
    ready = delete_ready
    forged = replace(ready["delete_marker"], **{field: "f" * 64})
    with pytest.raises(CapsuleDeleteDispatchError, match="noncanonical"):
        run_delete(ready, predelete_marker=forged)
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is None
    assert ready["delete_calls"] == []


@pytest.mark.parametrize("actor", (None, "teacher", "other-service", True))
def test_unprivileged_service_context_refused(
    delete_ready: dict[str, Any],
    actor: object,
) -> None:
    with pytest.raises(CapsuleDeleteDispatchError, match="inputs refused"):
        run_delete(delete_ready, service_context=actor)
    assert delete_ready["delete_calls"] == []


def test_missing_durable_predelete_marker_blocks_call(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    ready["db"].execute("DELETE FROM plan_capsule_predelete_uncertainty_v1")
    with pytest.raises(CapsuleDeleteDispatchError, match="records drifted"):
        run_delete(ready)
    assert ready["delete_calls"] == []


def test_changed_capsule_before_claim_blocks_deletion(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    (ready["local"] / "pending-slot-recovery.json").write_bytes(b"changed")
    with pytest.raises(CapsuleDeleteDispatchError, match="capsule"):
        run_delete(ready)
    assert ready["delete_calls"] == []
    assert ready["deleter"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_capsule_before_claim_blocks_deletion(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    (ready["local"] / "pending-slot-recovery.json").unlink()
    with pytest.raises(CapsuleDeleteDispatchError, match="inspection unavailable"):
        run_delete(ready)
    assert ready["delete_calls"] == []


def test_revoked_predelete_writer_fence_blocks_deletion(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    original = ready["quiet"]

    def revoked(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), exclusive_os_fence_held=False)

    with pytest.raises(CapsuleDeleteDispatchError, match="inspection unavailable"):
        run_delete(ready, independently_confirm_quiescence=revoked)
    assert ready["delete_calls"] == []


def test_wrong_witness_key_blocks_deletion(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(Exception):
        run_delete(ready, pinned_public_key=key)
    assert ready["delete_calls"] == []


def test_active_transaction_refuses_before_claim(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    ready["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(CapsuleDeleteDispatchError, match="inputs refused"):
            run_delete(ready)
    finally:
        ready["db"].execute("ROLLBACK")


def test_reopen_durable_claim_remains_one_shot(
    delete_ready: dict[str, Any],
) -> None:
    ready = delete_ready
    run_delete(ready)
    claim = ready["deleter"].observe(INSTALL, service_context=ACTOR)
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
    reopened = ProtectedCapsuleDeleteDispatcher(predelete)
    assert reopened.observe(INSTALL, service_context=ACTOR) == claim
    ready["deleter"] = reopened
    with pytest.raises(CapsuleDeleteDispatchError, match="already claimed"):
        run_delete(ready)
    db.close()


def test_corrupt_durable_claim_refused(delete_ready: dict[str, Any]) -> None:
    ready = delete_ready
    run_delete(ready)
    with pytest.raises(sqlite3.IntegrityError):
        ready["db"].execute(
            "UPDATE plan_capsule_delete_dispatch_v1 SET status='RETRY' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    ready["db"].execute(
        "UPDATE plan_capsule_delete_dispatch_v1 SET target_identity_sha256='bad' "
        "WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(CapsuleDeleteDispatchError, match="corrupt"):
        ready["deleter"].observe(INSTALL, service_context=ACTOR)
