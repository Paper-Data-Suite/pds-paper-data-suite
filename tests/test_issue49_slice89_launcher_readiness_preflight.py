"""Slice 89: protected non-activating launch readiness preflight.

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
from paper_data_suite.evergreen_plan_launcher_readiness_preflight import (
    IndependentLauncherReadinessInspection,
    LauncherReadinessPreflightError,
    ProtectedLauncherReadinessPreflightLedger,
    _record_hash,
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


def test_record_once_without_launch_or_file_write(launch_ready: dict[str, Any]) -> None:
    ready = launch_ready
    data = (ready["local"] / "student-work.txt").read_bytes()
    entry = check_launch(ready)
    assert entry.status == "LAUNCH_READINESS_PREFLIGHT_RECORDED_NO_LAUNCH_DISPATCH"
    assert entry.authority == (
        "NO_LAUNCH_SWITCH_ROLLBACK_CAS_REDELETE_OR_WRITER_AUTHORITY"
    )
    assert entry.postdelete_certificate_sha256 == _record_hash(
        ready["postdelete_certificate"]
    )
    assert entry.successor_sha256 == sha(ready["new"])
    assert ready["launcher_preflight"].observe(INSTALL, service_context=ACTOR) == entry
    assert ready["launch_reads"] == ["independent-runtime-audit"] * 2
    assert ready["active"].read_bytes() == ready["new"]
    assert not (ready["local"] / "pending-slot-recovery.json").exists()
    assert (ready["local"] / "student-work.txt").read_bytes() == data
    assert ready["delete_calls"] == ["one-service-deletion"]
    assert not any(
        hasattr(ready["launcher_preflight"], name)
        for name in (
            "launch",
            "activate",
            "switch",
            "rollback",
            "clear",
            "delete",
            "retry",
        )
    )


def test_replay_refused_without_new_runtime_read(launch_ready: dict[str, Any]) -> None:
    first = check_launch(launch_ready)
    count = len(launch_ready["launch_reads"])
    with pytest.raises(LauncherReadinessPreflightError, match="already recorded"):
        check_launch(launch_ready)
    assert count == len(launch_ready["launch_reads"])
    assert (
        launch_ready["launcher_preflight"].observe(INSTALL, service_context=ACTOR)
        == first
    )


@pytest.mark.parametrize(
    "field",
    (
        "read_only_runtime_audit_completed",
        "candidate_dependencies_independently_verified",
        "installed_candidate_identity_matches_signed_successor",
        "active_receipt_and_capsule_directories_os_fenced",
        "no_inflight_deleter_writer_or_launcher",
        "classroom_and_user_data_untouched",
        "no_launcher_execution_attempted",
    ),
)
def test_missing_runtime_attestation_refused(
    launch_ready: dict[str, Any], field: str
) -> None:
    prior = launch_ready["launch_reader"]

    def compromised(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(prior(req, ctx), **{field: False})

    with pytest.raises(LauncherReadinessPreflightError, match="unsafe execution"):
        check_launch(launch_ready, independently_read_launcher=compromised)
    assert (
        launch_ready["launcher_preflight"].observe(INSTALL, service_context=ACTOR)
        is None
    )


@pytest.mark.parametrize(
    "field",
    (
        "installation_id",
        "transaction_id",
        "request_sha256",
        "target_identity_sha256",
        "capsule_identity_sha256",
        "selection_sha256",
        "journal_sha256",
    ),
)
def test_runtime_identity_drift_refused(
    launch_ready: dict[str, Any], field: str
) -> None:
    prior = launch_ready["launch_reader"]

    def compromised(req: WitnessCommitRequest, ctx: object) -> Any:
        value = "0" * (32 if field in ("installation_id", "transaction_id") else 64)
        return replace(prior(req, ctx), **{field: value})

    with pytest.raises(LauncherReadinessPreflightError, match="unsafe execution"):
        check_launch(launch_ready, independently_read_launcher=compromised)


@pytest.mark.parametrize(
    "field",
    (
        "executable_identity_sha256",
        "installed_runtime_sha256",
        "service_boundary_sha256",
    ),
)
def test_malformed_runtime_digest_refused(
    launch_ready: dict[str, Any], field: str
) -> None:
    prior = launch_ready["launch_reader"]

    def compromised(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(prior(req, ctx), **{field: "bad"})

    with pytest.raises(LauncherReadinessPreflightError, match="unsafe execution"):
        check_launch(launch_ready, independently_read_launcher=compromised)


def test_postdelete_absence_revoked_refused(launch_ready: dict[str, Any]) -> None:
    path = launch_ready["local"] / "pending-slot-recovery.json"
    path.write_bytes(b"must-remain")
    with pytest.raises(LauncherReadinessPreflightError, match="capsule is not absent"):
        check_launch(launch_ready)
    assert (
        launch_ready["launcher_preflight"].observe(INSTALL, service_context=ACTOR)
        is None
    )
    assert launch_ready["delete_calls"] == ["one-service-deletion"]


def test_unfamiliar_capsule_refused(launch_ready: dict[str, Any]) -> None:
    (launch_ready["local"] / "pending-slot-recovery.json").write_bytes(b"tampered")
    with pytest.raises(LauncherReadinessPreflightError, match="capsule is not absent"):
        check_launch(launch_ready)


def test_active_receipt_change_refused(launch_ready: dict[str, Any]) -> None:
    launch_ready["active"].write_bytes(launch_ready["old"])
    with pytest.raises(LauncherReadinessPreflightError, match="changed active"):
        check_launch(launch_ready)


def test_delete_termination_uncertain_refused(launch_ready: dict[str, Any]) -> None:
    prior = launch_ready["termination_reader"]

    def unsafe(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(prior(req, ctx), all_prior_delete_operations_terminated=False)

    with pytest.raises(LauncherReadinessPreflightError, match="termination"):
        check_launch(launch_ready, independently_confirm_delete_termination=unsafe)


def test_changed_certificate_refused_before_probes(
    launch_ready: dict[str, Any],
) -> None:
    fake = replace(launch_ready["postdelete_certificate"], successor_sha256="0" * 64)
    before = len(launch_ready["launch_reads"])
    with pytest.raises(LauncherReadinessPreflightError, match="deletion chain"):
        check_launch(launch_ready, postdelete_certificate=fake)
    assert len(launch_ready["launch_reads"]) == before


def test_missing_stored_certificate_refused(launch_ready: dict[str, Any]) -> None:
    launch_ready["db"].execute("DELETE FROM plan_capsule_postdelete_reconciliation_v1")
    with pytest.raises(LauncherReadinessPreflightError, match="chain changed"):
        check_launch(launch_ready)


def test_changed_stored_certificate_refused(launch_ready: dict[str, Any]) -> None:
    launch_ready["db"].execute(
        "UPDATE plan_capsule_postdelete_reconciliation_v1 "
        "SET absence_evidence_sha256 = ?",
        ("0" * 64,),
    )
    with pytest.raises(LauncherReadinessPreflightError, match="chain changed"):
        check_launch(launch_ready)


def test_changed_delete_claim_refused(launch_ready: dict[str, Any]) -> None:
    launch_ready["db"].execute("DELETE FROM plan_capsule_delete_dispatch_v1")
    with pytest.raises(LauncherReadinessPreflightError, match="chain changed"):
        check_launch(launch_ready)


def test_signed_witness_pin_mismatch_refused(launch_ready: dict[str, Any]) -> None:
    key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(LauncherReadinessPreflightError, match="signed successor"):
        check_launch(launch_ready, pinned_public_key=key)


def test_two_read_runtime_drift_refused(launch_ready: dict[str, Any]) -> None:
    original = launch_ready["launch_reader"]
    count = 0

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal count
        count += 1
        result = original(req, ctx)
        if count == 2:
            return replace(result, installed_runtime_sha256="f" * 64)
        return result

    with pytest.raises(LauncherReadinessPreflightError, match="drifted"):
        check_launch(launch_ready, independently_read_launcher=drift)


def test_read_callback_exception_fails_closed(launch_ready: dict[str, Any]) -> None:
    def raises(_req: WitnessCommitRequest, _ctx: object) -> Any:
        raise OSError("untrusted callback failed")

    with pytest.raises(LauncherReadinessPreflightError, match="inspection unavailable"):
        check_launch(launch_ready, independently_read_launcher=raises)


@pytest.mark.parametrize("context", (None, "student", "teacher", True))
def test_unauthorized_context_refused(
    launch_ready: dict[str, Any], context: object
) -> None:
    with pytest.raises(LauncherReadinessPreflightError, match="authorization"):
        check_launch(launch_ready, service_context=context)


def test_durable_reopen_readback(launch_ready: dict[str, Any]) -> None:
    entry = check_launch(launch_ready)
    launch_ready["db"].close()
    db = sqlite3.connect(launch_ready["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=launch_ready["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    ledger = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatcher = ProtectedLocalReceiptDispatcher(ledger)
    convergence = ProtectedLocalConvergenceCoordinator(dispatcher)
    clearance = ProtectedCapsuleClearancePreflightLedger(convergence)
    predelete = ProtectedCapsulePredeleteUncertaintyLedger(clearance)
    delete = ProtectedCapsuleDeleteDispatcher(predelete)
    post = ProtectedCapsulePostdeleteReconciler(delete)
    new = ProtectedLauncherReadinessPreflightLedger(post)
    assert new.observe(INSTALL, service_context=ACTOR) == entry
    db.close()


def test_corrupt_stored_preflight_refused(launch_ready: dict[str, Any]) -> None:
    check_launch(launch_ready)
    with pytest.raises(sqlite3.IntegrityError):
        launch_ready["db"].execute(
            "UPDATE plan_launcher_readiness_preflight_v1 SET status = 'LAUNCHED'"
        )
    launch_ready["db"].execute(
        "UPDATE plan_launcher_readiness_preflight_v1 "
        "SET launcher_runtime_evidence_sha256 = 'not-a-hash'"
    )
    with pytest.raises(LauncherReadinessPreflightError, match="record corrupt"):
        launch_ready["launcher_preflight"].observe(INSTALL, service_context=ACTOR)


def test_prepare_is_non_destructive(launch_ready: dict[str, Any]) -> None:
    check_launch(launch_ready)
    assert len(launch_ready["delete_calls"]) == 1
    assert (launch_ready["local"] / "student-work.txt").exists()
    assert launch_ready["active"].read_bytes() == launch_ready["new"]
    assert not (launch_ready["local"] / "pending-slot-recovery.json").exists()
