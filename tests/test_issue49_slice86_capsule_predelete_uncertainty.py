"""Slice 86: protected capsule pre-delete uncertainty, no deletion.

Exercises real Slice 78-85 SQLite and Ed25519 witness paths. Test callbacks
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
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    CapsulePredeleteUncertaintyError,
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


def test_one_shot_durable_marker_leaves_capsule_and_local_receipt(
    clearance_ready: dict[str, Any],
) -> None:
    ready = clearance_ready
    before = {p.name: p.read_bytes() for p in ready["local"].iterdir()}
    assert ready["predelete"].observe(INSTALL, service_context=ACTOR) is None
    marker = arm_predelete(ready)
    assert marker.status == "CAPSULE_PREDELETE_UNCERTAINTY_ARMED_NO_DELETE_DISPATCH"
    assert marker.authority.startswith("NO_DELETE_RETRY")
    assert marker.successor_sha256 == sha(ready["new"])
    assert marker.recovery_capsule_sha256 == sha(b"must-remain")
    assert marker.capsule_identity_sha256 == CAPSULE_ID
    assert marker.target_identity_sha256 == TARGET
    assert ready["predelete"].observe(INSTALL, service_context=ACTOR) == marker
    assert {p.name: p.read_bytes() for p in ready["local"].iterdir()} == before
    assert len(ready["writes"]) == 1
    assert len(ready["capsule_reads"]) == 4
    assert not any(
        hasattr(ready["predelete"], name)
        for name in ("delete", "clear", "retry", "dispatch", "launch", "rollback")
    )


def test_duplicate_arm_refused_without_another_physical_inspection(
    clearance_ready: dict[str, Any],
) -> None:
    ready = clearance_ready
    first = arm_predelete(ready)
    samples = len(ready["capsule_reads"])
    with pytest.raises(CapsulePredeleteUncertaintyError, match="already armed"):
        arm_predelete(ready)
    assert len(ready["capsule_reads"]) == samples
    assert ready["predelete"].observe(INSTALL, service_context=ACTOR) == first


def test_reopen_protected_database_preserves_one_shot(
    clearance_ready: dict[str, Any],
) -> None:
    ready = clearance_ready
    first = arm_predelete(ready)
    ready["db"].close()
    db = sqlite3.connect(ready["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=ready["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    ledger = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatcher = ProtectedLocalReceiptDispatcher(ledger)
    convergence = ProtectedLocalConvergenceCoordinator(dispatcher)
    clearance = ProtectedCapsuleClearancePreflightLedger(convergence)
    reopened = ProtectedCapsulePredeleteUncertaintyLedger(clearance)
    ready["predelete"] = reopened
    assert reopened.observe(INSTALL, service_context=ACTOR) == first
    with pytest.raises(CapsulePredeleteUncertaintyError, match="already armed"):
        arm_predelete(ready)
    db.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "f" * 32),
        ("transaction_id", "f" * 32),
        ("request_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("successor_generation", 9),
        ("witness_revision", 9),
        ("convergence_record_sha256", "f" * 64),
        ("recovery_capsule_sha256", "f" * 64),
        ("capsule_identity_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("independent_fence_sha256", "f" * 64),
        ("status", "DELETE_ALLOWED"),
        ("authority", "LAUNCH_ALLOWED"),
    ],
)
def test_forged_clearance_preflight_refused_before_physical_reads(
    clearance_ready: dict[str, Any], field: str, value: object
) -> None:
    forged = replace(clearance_ready["preflight"], **{field: value})
    count = len(clearance_ready["capsule_reads"])
    with pytest.raises(CapsulePredeleteUncertaintyError, match="invalid"):
        arm_predelete(clearance_ready, clearance_preflight=forged)
    assert len(clearance_ready["capsule_reads"]) == count
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize("context", (None, "teacher", "other-service", True))
def test_unprivileged_actor_refused(
    clearance_ready: dict[str, Any], context: object
) -> None:
    with pytest.raises(CapsulePredeleteUncertaintyError, match="authorization"):
        arm_predelete(clearance_ready, service_context=context)
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_actual_preflight_refused(clearance_ready: dict[str, Any]) -> None:
    clearance_ready["db"].execute("DELETE FROM plan_capsule_clearance_preflight_v1")
    with pytest.raises(CapsulePredeleteUncertaintyError, match="preflight drifted"):
        arm_predelete(clearance_ready)
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_actual_convergence_refused(clearance_ready: dict[str, Any]) -> None:
    clearance_ready["db"].execute("DELETE FROM plan_local_convergence_v1")
    with pytest.raises(CapsulePredeleteUncertaintyError, match="convergence"):
        arm_predelete(clearance_ready)


def test_capsule_changed_after_preflight_is_refused(
    clearance_ready: dict[str, Any],
) -> None:
    path = clearance_ready["local"] / "pending-slot-recovery.json"
    path.write_bytes(b"changed-after-preflight")
    with pytest.raises(CapsulePredeleteUncertaintyError, match="capsule bytes"):
        arm_predelete(clearance_ready)
    assert path.exists()


def test_capsule_disappears_after_preflight_is_refused(
    clearance_ready: dict[str, Any],
) -> None:
    path = clearance_ready["local"] / "pending-slot-recovery.json"
    path.unlink()
    with pytest.raises(
        CapsulePredeleteUncertaintyError, match="inspection unavailable"
    ):
        arm_predelete(clearance_ready)
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize(
    "field",
    (
        "capsule_is_protected_regular_file",
        "parent_directory_protected",
        "exclusive_service_capsule_fence_held",
        "no_other_capsule_writer_can_start",
    ),
)
def test_protected_capsule_custody_must_still_be_true(
    clearance_ready: dict[str, Any], field: str
) -> None:
    previous = clearance_ready["capsule_reader"]

    def weak(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(previous(req, ctx), **{field: False})

    with pytest.raises(CapsulePredeleteUncertaintyError, match="capsule bytes"):
        arm_predelete(clearance_ready, independently_read_capsule=weak)


def test_changes_between_physical_samples_refused(
    clearance_ready: dict[str, Any],
) -> None:
    previous = clearance_ready["capsule_reader"]
    count = 0

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal count
        count += 1
        if count == 2:
            (clearance_ready["local"] / "pending-slot-recovery.json").write_bytes(
                b"drifted"
            )
        return previous(req, ctx)

    with pytest.raises(CapsulePredeleteUncertaintyError, match="drifted"):
        arm_predelete(clearance_ready, independently_read_capsule=drift)
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR) is None


def test_revoked_no_inflight_fence_refused(clearance_ready: dict[str, Any]) -> None:
    prior = clearance_ready["quiet"]

    def bad(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(prior(req, ctx), no_unaccounted_writer_in_flight=False)

    with pytest.raises(CapsulePredeleteUncertaintyError, match="uncertain"):
        arm_predelete(clearance_ready, independently_confirm_quiescence=bad)


def test_successor_receipt_replaced_after_preflight_refused(
    clearance_ready: dict[str, Any],
) -> None:
    clearance_ready["active"].write_bytes(clearance_ready["old"])
    with pytest.raises(CapsulePredeleteUncertaintyError, match="successor"):
        arm_predelete(clearance_ready)
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR) is None


def test_bad_witness_key_prevents_predelete(clearance_ready: dict[str, Any]) -> None:
    wrong = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(CapsulePredeleteUncertaintyError, match="uncertain"):
        arm_predelete(clearance_ready, pinned_public_key=wrong)
    assert (clearance_ready["local"] / "pending-slot-recovery.json").exists()


def test_pinned_capsule_identity_must_match_preflight(
    clearance_ready: dict[str, Any],
) -> None:
    with pytest.raises(CapsulePredeleteUncertaintyError, match="invalid"):
        arm_predelete(clearance_ready, pinned_capsule_identity_sha256="f" * 64)


def test_missing_protected_service_database_transaction_refused(
    clearance_ready: dict[str, Any],
) -> None:
    clearance_ready["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(CapsulePredeleteUncertaintyError, match="inputs refused"):
            arm_predelete(clearance_ready)
    finally:
        clearance_ready["db"].execute("ROLLBACK")


def test_durable_row_status_and_digest_integrity(
    clearance_ready: dict[str, Any],
) -> None:
    arm_predelete(clearance_ready)
    with pytest.raises(sqlite3.IntegrityError):
        clearance_ready["db"].execute(
            "UPDATE plan_capsule_predelete_uncertainty_v1 SET status='DELETE' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    clearance_ready["db"].execute(
        "UPDATE plan_capsule_predelete_uncertainty_v1 "
        "SET clearance_preflight_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(CapsulePredeleteUncertaintyError, match="corrupt"):
        clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR)


def test_no_rearm_after_prior_capsule_change(clearance_ready: dict[str, Any]) -> None:
    arm_predelete(clearance_ready)
    (clearance_ready["local"] / "pending-slot-recovery.json").unlink()
    with pytest.raises(CapsulePredeleteUncertaintyError, match="already armed"):
        arm_predelete(clearance_ready)
    assert clearance_ready["predelete"].observe(INSTALL, service_context=ACTOR)
