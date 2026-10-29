"""Slice 91: one-shot prelaunch uncertainty without process execution.

Exercise actual protected Slices 78-88 chain, witness and read-only probes.
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
    PrelaunchUncertaintyError,
    ProtectedPrelaunchUncertaintyLedger,
    _intent_hash,
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


def test_barrier_is_durable_nonexecuting_and_capsule_absent(
    prelaunch_ready: dict[str, Any],
) -> None:
    r = prelaunch_ready
    before = (r["local"] / "student-work.txt").read_bytes()
    writes = list(r["delete_calls"])
    marker = arm_prelaunch(r)
    assert marker.status == "PRELAUNCH_UNCERTAINTY_ARMED_NO_PROCESS_DISPATCH"
    assert marker.authority.startswith("NO_REARM_LAUNCH_RETRY")
    assert marker.protected_launch_intent_sha256 == _intent_hash(
        r["launch_reservation"]
    )
    assert marker.renewed_runtime_evidence_sha256 == (
        r["launch_reservation"].renewed_runtime_evidence_sha256
    )
    assert r["prelaunch_api"].observe(INSTALL, service_context=ACTOR) == marker
    assert r["active"].read_bytes() == r["new"]
    assert not (r["local"] / "pending-slot-recovery.json").exists()
    assert (r["local"] / "student-work.txt").read_bytes() == before
    assert r["delete_calls"] == writes
    for verb in (
        "execute",
        "launch",
        "dispatch",
        "start",
        "switch",
        "clear",
        "delete",
        "rollback",
        "activate",
        "retry",
    ):
        assert not hasattr(r["prelaunch_api"], verb)


def test_rearm_refused_before_independent_read(
    prelaunch_ready: dict[str, Any],
) -> None:
    first = arm_prelaunch(prelaunch_ready)
    observations = len(prelaunch_ready["launch_reads"])
    witnesses = len(prelaunch_ready["witness_reads"])
    with pytest.raises(PrelaunchUncertaintyError, match="already armed"):
        arm_prelaunch(prelaunch_ready)
    assert len(prelaunch_ready["launch_reads"]) == observations
    assert len(prelaunch_ready["witness_reads"]) == witnesses
    assert (
        prelaunch_ready["prelaunch_api"].observe(INSTALL, service_context=ACTOR)
        == first
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("launcher_readiness_preflight_sha256", "f" * 64),
        ("postdelete_certificate_sha256", "f" * 64),
        ("executable_identity_sha256", "f" * 64),
        ("service_boundary_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("renewed_runtime_evidence_sha256", "f" * 64),
        ("status", "READY_TO_EXECUTE"),
        ("authority", "PROCESS_EXECUTION_ALLOWED"),
    ],
)
def test_forged_launch_intent_refused_before_arm(
    prelaunch_ready: dict[str, Any],
    field: str,
    value: str,
) -> None:
    forged = replace(prelaunch_ready["launch_reservation"], **{field: value})
    expected_error = (
        "durable protected chain changed"
        if field in ("executable_identity_sha256", "service_boundary_sha256")
        else "invalid protected"
    )
    with pytest.raises(PrelaunchUncertaintyError, match=expected_error):
        arm_prelaunch(prelaunch_ready, launch_intent=forged)
    assert (
        prelaunch_ready["prelaunch_api"].observe(INSTALL, service_context=ACTOR) is None
    )


def test_missing_durable_launch_intent_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    prelaunch_ready["db"].execute("DELETE FROM plan_launch_intent_v1")
    with pytest.raises(PrelaunchUncertaintyError, match="durable protected"):
        arm_prelaunch(prelaunch_ready)


def test_mutated_durable_launch_intent_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    prelaunch_ready["db"].execute(
        "UPDATE plan_launch_intent_v1 "
        "SET renewed_runtime_evidence_sha256=? WHERE installation_id=?",
        ("0" * 64, INSTALL),
    )
    with pytest.raises(PrelaunchUncertaintyError, match="durable protected"):
        arm_prelaunch(prelaunch_ready)


def test_missing_durable_readiness_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    prelaunch_ready["db"].execute("DELETE FROM plan_launcher_readiness_preflight_v1")
    with pytest.raises(PrelaunchUncertaintyError, match="durable protected"):
        arm_prelaunch(prelaunch_ready)


@pytest.mark.parametrize("context", [None, "student", "teacher", True])
def test_unauthorized_context_refused(
    prelaunch_ready: dict[str, Any],
    context: object,
) -> None:
    with pytest.raises(PrelaunchUncertaintyError, match="authorization"):
        arm_prelaunch(prelaunch_ready, service_context=context)


@pytest.mark.parametrize(
    "field",
    [
        "no_inflight_deleter_writer_or_launcher",
        "read_only_runtime_audit_completed",
        "installed_candidate_identity_matches_signed_successor",
        "active_receipt_and_capsule_directories_os_fenced",
        "no_launcher_execution_attempted",
        "candidate_dependencies_independently_verified",
        "classroom_and_user_data_untouched",
    ],
)
def test_revoked_runtime_or_execution_fence_refused(
    prelaunch_ready: dict[str, Any],
    field: str,
) -> None:
    original = prelaunch_ready["launch_reader"]

    def unsafe(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(PrelaunchUncertaintyError, match="execution fence"):
        arm_prelaunch(prelaunch_ready, independently_read_launcher=unsafe)


def test_launcher_executable_changed_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    original = prelaunch_ready["launch_reader"]

    def changed(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), executable_identity_sha256="0" * 64)

    with pytest.raises(PrelaunchUncertaintyError, match="runtime evidence"):
        arm_prelaunch(prelaunch_ready, independently_read_launcher=changed)


@pytest.mark.parametrize("raw", [b"must-remain", b"unexpected-capsule"])
def test_reappearing_capsule_refused(
    prelaunch_ready: dict[str, Any],
    raw: bytes,
) -> None:
    (prelaunch_ready["local"] / "pending-slot-recovery.json").write_bytes(raw)
    with pytest.raises(PrelaunchUncertaintyError):
        arm_prelaunch(prelaunch_ready)


def test_successor_receipt_changed_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    prelaunch_ready["active"].write_bytes(prelaunch_ready["old"])
    with pytest.raises(PrelaunchUncertaintyError):
        arm_prelaunch(prelaunch_ready)


def test_unterminated_deletion_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    original = prelaunch_ready["termination_reader"]

    def uncertain(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), all_prior_delete_operations_terminated=False)

    with pytest.raises(PrelaunchUncertaintyError, match="deletion still"):
        arm_prelaunch(
            prelaunch_ready, independently_confirm_delete_termination=uncertain
        )


def test_wrong_signed_witness_key_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    other = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(PrelaunchUncertaintyError, match="signed successor"):
        arm_prelaunch(prelaunch_ready, pinned_public_key=other)


def test_drift_between_two_samples_refused(
    prelaunch_ready: dict[str, Any],
) -> None:
    original = prelaunch_ready["launch_reader"]
    count = 0

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal count
        count += 1
        observed = original(req, ctx)
        if count == 2:
            return replace(observed, service_boundary_sha256="0" * 64)
        return observed

    with pytest.raises(PrelaunchUncertaintyError):
        arm_prelaunch(prelaunch_ready, independently_read_launcher=drift)
    assert (
        prelaunch_ready["prelaunch_api"].observe(INSTALL, service_context=ACTOR) is None
    )


def test_independent_probe_exception_fails_closed(
    prelaunch_ready: dict[str, Any],
) -> None:
    def outage(req: WitnessCommitRequest, ctx: object) -> Any:
        raise OSError("independent service unavailable")

    with pytest.raises(PrelaunchUncertaintyError, match="read unavailable"):
        arm_prelaunch(prelaunch_ready, independently_read_launcher=outage)


def test_cannot_arm_inside_existing_protected_transaction(
    prelaunch_ready: dict[str, Any],
) -> None:
    db = prelaunch_ready["db"]
    db.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(PrelaunchUncertaintyError, match="inputs unavailable"):
            arm_prelaunch(prelaunch_ready)
    finally:
        db.execute("ROLLBACK")


def test_reopen_persisted_barrier(
    prelaunch_ready: dict[str, Any],
) -> None:
    result = arm_prelaunch(prelaunch_ready)
    prelaunch_ready["db"].close()
    db = sqlite3.connect(prelaunch_ready["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=prelaunch_ready["authorize"])
    claims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(claims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    prewrite = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatch = ProtectedLocalReceiptDispatcher(prewrite)
    convergence = ProtectedLocalConvergenceCoordinator(dispatch)
    clearance = ProtectedCapsuleClearancePreflightLedger(convergence)
    predelete = ProtectedCapsulePredeleteUncertaintyLedger(clearance)
    deleter = ProtectedCapsuleDeleteDispatcher(predelete)
    reconciler = ProtectedCapsulePostdeleteReconciler(deleter)
    readiness = ProtectedLauncherReadinessPreflightLedger(reconciler)
    intents = ProtectedLaunchIntentLedger(readiness)
    reloaded = ProtectedPrelaunchUncertaintyLedger(intents)
    assert reloaded.observe(INSTALL, service_context=ACTOR) == result
    db.close()


def test_invalid_stored_barrier_fails_closed(
    prelaunch_ready: dict[str, Any],
) -> None:
    arm_prelaunch(prelaunch_ready)
    with pytest.raises(sqlite3.IntegrityError):
        prelaunch_ready["db"].execute(
            "UPDATE plan_prelaunch_uncertainty_v1 SET status='READY' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    prelaunch_ready["db"].execute(
        "UPDATE plan_prelaunch_uncertainty_v1 "
        "SET protected_launch_intent_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(PrelaunchUncertaintyError, match="corrupt"):
        prelaunch_ready["prelaunch_api"].observe(INSTALL, service_context=ACTOR)


def test_barrier_grants_no_hidden_execution_rights(
    prelaunch_ready: dict[str, Any],
) -> None:
    before = len(prelaunch_ready["delete_calls"])
    arm_prelaunch(prelaunch_ready)
    assert len(prelaunch_ready["delete_calls"]) == before
    assert (
        prelaunch_ready["db"]
        .execute("SELECT count(*) FROM plan_prelaunch_uncertainty_v1")
        .fetchone()[0]
        == 1
    )
    assert prelaunch_ready["db"].in_transaction is False
