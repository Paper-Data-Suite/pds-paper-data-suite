"""Slice 92: one-shot process-dispatch claim against real Slices 78-91.

The fake launcher is test-only, not a qualified Windows service.
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
    IndependentCapsuleDeleteReadback,
    ProtectedCapsuleDeleteDispatcher,
)
from paper_data_suite.evergreen_plan_capsule_postdelete_reconciliation import (
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
from paper_data_suite.evergreen_plan_launch_dispatch import (
    IndependentProcessStartReadback,
    LaunchDispatchError,
    ProtectedLaunchDispatcher,
    _prelaunch_hash,
)
from paper_data_suite.evergreen_plan_launch_intent import (
    ProtectedLaunchIntentLedger,
)
from paper_data_suite.evergreen_plan_launcher_readiness_preflight import (
    IndependentLauncherReadinessInspection,
    ProtectedLauncherReadinessPreflightLedger,
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
from paper_data_suite.evergreen_plan_prelaunch_uncertainty import (
    ProtectedPrelaunchUncertaintyLedger,
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


@pytest.fixture
def launch_ready(postdelete_ready: dict[str, Any]) -> dict[str, Any]:
    ready = postdelete_ready
    ready["postdelete_certificate"] = verify_postdelete(ready, certify=True)
    ready["launcher_preflight"] = ProtectedLauncherReadinessPreflightLedger(
        ready["postdelete_api"]
    )
    ready["launch_reads"] = []

    def inspection(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentLauncherReadinessInspection:
        assert req.installation_id == INSTALL and ctx == ACTOR
        ready["launch_reads"].append("independent-runtime-audit")
        return IndependentLauncherReadinessInspection(
            INSTALL,
            NEXT,
            ready["reservation"].request_sha256,
            TARGET,
            CAPSULE_ID,
            ready["reservation"].selection_sha256,
            ready["reservation"].journal_sha256,
            sha(b"service-pinned-executable"),
            sha(b"independently audited installed runtime"),
            sha(b"separately provisioned OS service boundary"),
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        )

    ready["launch_reader"] = inspection
    return ready


def check_launch(ready: dict[str, Any], **changes: Any) -> Any:
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
        "postdelete_certificate": ready["postdelete_certificate"],
        "service_context": ACTOR,
        "independently_read_postdelete": ready["post"],
        "independently_confirm_delete_termination": ready["termination_reader"],
        "independently_read_launcher": ready["launch_reader"],
        "witness_transport": ready["witness"],
        "pinned_public_key": ready["public"],
        "now": NOW,
    }
    return ready["launcher_preflight"].prepare_once(**(kwargs | changes))


@pytest.fixture
def intent_ready(launch_ready: dict[str, Any]) -> dict[str, Any]:
    launch_ready["readiness_record"] = check_launch(launch_ready)
    launch_ready["intent_api"] = ProtectedLaunchIntentLedger(
        launch_ready["launcher_preflight"]
    )
    return launch_ready


def reserve_intent(ready: dict[str, Any], **changes: Any) -> Any:
    inputs = dict(
        request_bytes=ready["raw"],
        reservation=ready["reservation"],
        preclaim=ready["preclaim"],
        record=ready["record"],
        intent=ready["intent"],
        marker=ready["marker"],
        claim=ready["claim"],
        convergence=ready["certified"],
        clearance_preflight=ready["preflight"],
        predelete_marker=ready["delete_marker"],
        delete_claim=ready["delete_claim"],
        postdelete_certificate=ready["postdelete_certificate"],
        launcher_preflight=ready["readiness_record"],
        service_context=ACTOR,
        independently_read_postdelete=ready["post"],
        independently_confirm_delete_termination=ready["termination_reader"],
        independently_read_launcher=ready["launch_reader"],
        witness_transport=ready["witness"],
        pinned_public_key=ready["public"],
        now=NOW,
    )
    return ready["intent_api"].reserve_once(**(inputs | changes))


@pytest.fixture
def prelaunch_ready(intent_ready: dict[str, Any]) -> dict[str, Any]:
    ready = intent_ready
    ready["launch_reservation"] = reserve_intent(ready)
    ready["prelaunch_api"] = ProtectedPrelaunchUncertaintyLedger(ready["intent_api"])
    return ready


def arm_prelaunch(ready: dict[str, Any], **changes: Any) -> Any:
    inputs: dict[str, Any] = dict(
        request_bytes=ready["raw"],
        reservation=ready["reservation"],
        preclaim=ready["preclaim"],
        record=ready["record"],
        intent=ready["intent"],
        marker=ready["marker"],
        claim=ready["claim"],
        convergence=ready["certified"],
        clearance_preflight=ready["preflight"],
        predelete_marker=ready["delete_marker"],
        delete_claim=ready["delete_claim"],
        postdelete_certificate=ready["postdelete_certificate"],
        launcher_preflight=ready["readiness_record"],
        launch_intent=ready["launch_reservation"],
        service_context=ACTOR,
        independently_read_postdelete=ready["post"],
        independently_confirm_delete_termination=ready["termination_reader"],
        independently_read_launcher=ready["launch_reader"],
        witness_transport=ready["witness"],
        pinned_public_key=ready["public"],
        now=NOW,
    )
    return ready["prelaunch_api"].arm_once(**(inputs | changes))


@pytest.fixture
def dispatch_ready(prelaunch_ready: dict[str, Any]) -> dict[str, Any]:
    r = prelaunch_ready
    r["prelaunch_marker"] = arm_prelaunch(r)
    r["launch_dispatch"] = ProtectedLaunchDispatcher(r["prelaunch_api"])
    r["start_calls"] = []
    r["process_reads"] = []
    r["observed_start"] = True

    def service_start(req: WitnessCommitRequest, executable: str, ctx: object) -> None:
        assert req.installation_id == INSTALL and ctx == ACTOR
        assert executable == r["launch_reservation"].executable_identity_sha256
        # The claim MUST be durable before an external launch can be called.
        assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
        assert not (r["local"] / "pending-slot-recovery.json").exists()
        assert r["active"].read_bytes() == r["new"]
        r["start_calls"].append("one-independent-service-launch")

    def read_process(req: WitnessCommitRequest, ctx: object) -> Any:
        assert req.installation_id == INSTALL and ctx == ACTOR
        r["process_reads"].append("independent-process-inspection")
        return IndependentProcessStartReadback(
            INSTALL,
            NEXT,
            r["launch_reservation"].executable_identity_sha256,
            r["launch_reservation"].service_boundary_sha256,
            TARGET,
            r["observed_start"],
            True,
            True,
            True,
            True,
            True,
        )

    r["service_start"] = service_start
    r["read_process"] = read_process
    return r


def run_launch(r: dict[str, Any], **changes: Any) -> Any:
    args: dict[str, Any] = dict(
        request_bytes=r["raw"],
        reservation=r["reservation"],
        preclaim=r["preclaim"],
        record=r["record"],
        intent=r["intent"],
        marker=r["marker"],
        claim=r["claim"],
        convergence=r["certified"],
        clearance_preflight=r["preflight"],
        predelete_marker=r["delete_marker"],
        delete_claim=r["delete_claim"],
        postdelete_certificate=r["postdelete_certificate"],
        launcher_preflight=r["readiness_record"],
        launch_intent=r["launch_reservation"],
        prelaunch_marker=r["prelaunch_marker"],
        service_context=ACTOR,
        independently_read_postdelete=r["post"],
        independently_confirm_delete_termination=r["termination_reader"],
        independently_read_launcher=r["launch_reader"],
        independently_inspect_process=r["read_process"],
        witness_transport=r["witness"],
        pinned_public_key=r["public"],
        now=NOW,
        service_owned_launch=r["service_start"],
    )
    return r["launch_dispatch"].dispatch_once(**(args | changes))


def test_launch_claim_precedes_one_service_call(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    untouched = (r["local"] / "student-work.txt").read_bytes()
    response = run_launch(r)
    assert response.status == "PROCESS_START_OBSERVED_ACTIVATION_NOT_AUTHORIZED"
    assert response.authority.startswith("NO_RELAUNCH_ACTIVATE")
    claim = r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    assert claim is not None
    assert claim.status == "LAUNCH_DISPATCH_CLAIMED_PROCESS_OUTCOME_UNCERTAIN"
    assert claim.prelaunch_marker_sha256 == _prelaunch_hash(r["prelaunch_marker"])
    assert claim.executable_identity_sha256 == (
        r["launch_reservation"].executable_identity_sha256
    )
    assert r["start_calls"] == ["one-independent-service-launch"]
    assert r["process_reads"] == ["independent-process-inspection"]
    assert r["active"].read_bytes() == r["new"]
    assert not (r["local"] / "pending-slot-recovery.json").exists()
    assert (r["local"] / "student-work.txt").read_bytes() == untouched
    assert r["db"].in_transaction is False
    assert not hasattr(r["launch_dispatch"], "activate")
    assert not hasattr(r["launch_dispatch"], "retry")
    assert not hasattr(r["launch_dispatch"], "rollback")


def test_relaunch_refused_before_external_readback(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    run_launch(r)
    start_count = len(r["start_calls"])
    reads = len(r["launch_reads"])
    witness_reads = len(r["witness_reads"])
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)
    assert len(r["start_calls"]) == start_count == 1
    assert len(r["launch_reads"]) == reads
    assert len(r["witness_reads"]) == witness_reads


@pytest.mark.parametrize(
    "seen,status",
    [
        (False, "PROCESS_NOT_OBSERVED_NO_RETRY_AUTHORITY"),
        (None, "PROCESS_OUTCOME_UNKNOWN_QUARANTINE_REQUIRED"),
    ],
)
def test_missing_or_uncertain_process_never_allows_retry(
    dispatch_ready: dict[str, Any],
    seen: bool | None,
    status: str,
) -> None:
    r = dispatch_ready
    r["observed_start"] = seen
    observed = run_launch(r)
    assert observed.status == status
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)
    assert len(r["start_calls"]) == 1


def test_launcher_lost_ack_retains_durable_claim(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    prior = r["service_start"]

    def lost_ack(req: WitnessCommitRequest, exe: str, ctx: object) -> None:
        prior(req, exe, ctx)
        raise OSError("process may have started; lost acknowledgment")

    with pytest.raises(LaunchDispatchError, match="outcome uncertain"):
        run_launch(r, service_owned_launch=lost_ack)
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    assert len(r["start_calls"]) == 1
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)
    assert len(r["start_calls"]) == 1


def test_callback_no_op_does_not_create_retry_authority(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    r["observed_start"] = False
    answer = run_launch(r, service_owned_launch=lambda req, exe, ctx: None)
    assert answer.status == "PROCESS_NOT_OBSERVED_NO_RETRY_AUTHORITY"
    assert not r["start_calls"]
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)


def test_post_start_reader_failure_keeps_one_shot_claim(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready

    def failed(req: WitnessCommitRequest, context: object) -> Any:
        raise OSError("post-start service observation offline")

    with pytest.raises(LaunchDispatchError, match="observation unavailable"):
        run_launch(r, independently_inspect_process=failed)
    assert len(r["start_calls"]) == 1
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    with pytest.raises(LaunchDispatchError, match="already claimed"):
        run_launch(r)


@pytest.mark.parametrize(
    "field",
    [
        "exclusive_launcher_service_fence_held",
        "no_second_dispatch_observed",
        "successor_receipt_independently_confirmed",
        "capsule_still_absent_independently_confirmed",
        "protected_software_and_classroom_files_unchanged",
    ],
)
def test_post_start_unverified_fence_fails_closed(
    dispatch_ready: dict[str, Any],
    field: str,
) -> None:
    r = dispatch_ready
    original = r["read_process"]

    def invalid(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(LaunchDispatchError, match="state unverified"):
        run_launch(r, independently_inspect_process=invalid)
    assert len(r["start_calls"]) == 1
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)


@pytest.mark.parametrize(
    "field",
    [
        "installation_id",
        "transaction_id",
        "executable_identity_sha256",
        "service_boundary_sha256",
        "target_identity_sha256",
    ],
)
def test_forged_post_start_identity_fails_closed(
    dispatch_ready: dict[str, Any],
    field: str,
) -> None:
    r = dispatch_ready
    original = r["read_process"]

    def invalid(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: "0" * 64})

    with pytest.raises(LaunchDispatchError, match="state unverified"):
        run_launch(r, independently_inspect_process=invalid)
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)


@pytest.mark.parametrize(
    "field",
    [
        "protected_launch_intent_sha256",
        "launcher_readiness_preflight_sha256",
        "postdelete_certificate_sha256",
        "target_identity_sha256",
        "renewed_runtime_evidence_sha256",
        "status",
        "authority",
    ],
)
def test_forged_prelaunch_marker_refused_before_launch(
    dispatch_ready: dict[str, Any],
    field: str,
) -> None:
    r = dispatch_ready
    forged = replace(r["prelaunch_marker"], **{field: "f" * 64})
    with pytest.raises(LaunchDispatchError):
        run_launch(r, prelaunch_marker=forged)
    assert not r["start_calls"]
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_persisted_prelaunch_marker_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    r["db"].execute("DELETE FROM plan_prelaunch_uncertainty_v1")
    with pytest.raises(LaunchDispatchError, match="durable protected"):
        run_launch(r)
    assert not r["start_calls"]


def test_mutated_persisted_prelaunch_marker_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    r["db"].execute(
        "UPDATE plan_prelaunch_uncertainty_v1 "
        "SET renewed_runtime_evidence_sha256=? WHERE installation_id=?",
        ("0" * 64, INSTALL),
    )
    with pytest.raises(LaunchDispatchError, match="durable protected"):
        run_launch(r)
    assert not r["start_calls"]


def test_missing_persisted_launch_intent_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    r["db"].execute("DELETE FROM plan_launch_intent_v1")
    with pytest.raises(LaunchDispatchError, match="durable protected"):
        run_launch(r)
    assert not r["start_calls"]


@pytest.mark.parametrize("context", [None, "teacher", "student", True])
def test_unauthorized_actor_refused(
    dispatch_ready: dict[str, Any],
    context: object,
) -> None:
    with pytest.raises(LaunchDispatchError, match="authorization"):
        run_launch(dispatch_ready, service_context=context)
    assert not dispatch_ready["start_calls"]


def test_reappeared_capsule_refused_before_dispatch(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    (r["local"] / "pending-slot-recovery.json").write_bytes(b"unexpected")
    with pytest.raises(LaunchDispatchError):
        run_launch(r)
    assert not r["start_calls"]


def test_changed_successor_receipt_refused_before_dispatch(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    r["active"].write_bytes(r["old"])
    with pytest.raises(LaunchDispatchError):
        run_launch(r)
    assert not r["start_calls"]


def test_expired_launcher_service_fence_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    prior = r["launch_reader"]

    def altered(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(prior(req, ctx), no_launcher_execution_attempted=False)

    with pytest.raises(LaunchDispatchError, match="service fence"):
        run_launch(r, independently_read_launcher=altered)
    assert not r["start_calls"]


def test_wrong_signed_witness_key_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(LaunchDispatchError, match="signed successor"):
        run_launch(r, pinned_public_key=key)
    assert not r["start_calls"]


def test_drift_across_prelaunch_samples_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    prior = r["launch_reader"]
    count = 0

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal count
        count += 1
        if count == 2:
            return replace(prior(req, ctx), service_boundary_sha256="0" * 64)
        return prior(req, ctx)

    with pytest.raises(LaunchDispatchError):
        run_launch(r, independently_read_launcher=drift)
    assert not r["start_calls"]
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR) is None


def test_reject_inside_active_protected_transaction(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    r["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LaunchDispatchError, match="inputs missing"):
            run_launch(r)
    finally:
        r["db"].execute("ROLLBACK")
    assert not r["start_calls"]


def test_reopen_persisted_launch_claim(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    run_launch(r)
    original = r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
    r["db"].close()
    db = sqlite3.connect(r["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=r["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    prewrite = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatcher = ProtectedLocalReceiptDispatcher(prewrite)
    convergence = ProtectedLocalConvergenceCoordinator(dispatcher)
    clearance = ProtectedCapsuleClearancePreflightLedger(convergence)
    predelete = ProtectedCapsulePredeleteUncertaintyLedger(clearance)
    deleter = ProtectedCapsuleDeleteDispatcher(predelete)
    reconciler = ProtectedCapsulePostdeleteReconciler(deleter)
    readiness = ProtectedLauncherReadinessPreflightLedger(reconciler)
    intents = ProtectedLaunchIntentLedger(readiness)
    uncertainty = ProtectedPrelaunchUncertaintyLedger(intents)
    launch_dispatcher = ProtectedLaunchDispatcher(uncertainty)
    assert launch_dispatcher.observe(INSTALL, service_context=ACTOR) == original
    db.close()


def test_corrupt_stored_launch_claim_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    run_launch(r)
    with pytest.raises(sqlite3.IntegrityError):
        r["db"].execute(
            "UPDATE plan_launch_dispatch_v1 SET status='SUCCESS' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    r["db"].execute(
        "UPDATE plan_launch_dispatch_v1 "
        "SET prelaunch_marker_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(LaunchDispatchError, match="corrupt"):
        r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)


def test_missing_independent_launch_adapter_refused(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    with pytest.raises(LaunchDispatchError, match="inputs missing"):
        run_launch(r, service_owned_launch=None)
    assert not r["start_calls"]


def test_unknown_post_start_type_fails_closed(
    dispatch_ready: dict[str, Any],
) -> None:
    r = dispatch_ready
    with pytest.raises(LaunchDispatchError, match="state unverified"):
        run_launch(r, independently_inspect_process=lambda req, ctx: "yes")
    assert r["launch_dispatch"].observe(INSTALL, service_context=ACTOR)
