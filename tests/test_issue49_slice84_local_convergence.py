"""Slice 84: post-dispatch convergence and no-inflight service observation.

Uses exact prior Slice 78-81 service SQLite chains and signed synthetic
witness. The test callbacks are NOT protected production readers.
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
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationEvidence,
    ProtectedPlanFinalizationFence,
)
from paper_data_suite.evergreen_plan_finalization_preflight import (
    PlanFinalizationPreflight,
)
from paper_data_suite.evergreen_plan_local_convergence import (
    IndependentNoInflightEvidence,
    LocalConvergenceError,
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
        "7" * 64,
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


def test_successor_read_only_classification_has_no_authority(
    completed: dict[str, Any],
) -> None:
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None
    previous = (completed["local"] / "pending-slot-recovery.json").read_bytes()
    response = reconcile(completed)
    assert response.status == "SUCCESSOR_VISIBLE_CONVERGENCE_NOT_YET_AUTHORIZED"
    assert response.authority.startswith("NO_RETRY_CAPSULE_CLEAR")
    assert response.observed_receipt_sha256 == sha(completed["new"])
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None
    assert (completed["local"] / "pending-slot-recovery.json").read_bytes() == previous
    assert len(completed["writes"]) == 1


def test_certify_once_records_unchanged_capsule_and_no_launch(
    completed: dict[str, Any],
) -> None:
    untouched = (completed["local"] / "pending-slot-recovery.json").read_bytes()
    result = reconcile(completed, certify=True)
    assert result.status == "LOCAL_RECEIPT_CONVERGENCE_RECORDED_CAPSULE_RETAINED"
    assert result.successor_sha256 == sha(completed["new"])
    assert result.independently_fenced_evidence_sha256 == sha(
        bytes.fromhex("f" * 64) + bytes.fromhex("e" * 64)
    )
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) == result
    assert completed["quiet_calls"] == ["independent-no-inflight"] * 2
    assert completed["active"].read_bytes() == completed["new"]
    assert (completed["local"] / "pending-slot-recovery.json").read_bytes() == untouched
    assert completed["writes"] == ["one-protected-file-operation"]
    assert not any(
        hasattr(completed["convergence"], name)
        for name in ("launch", "clear", "rollback", "retry", "dispatch", "activate")
    )


def test_replay_certification_refused(completed: dict[str, Any]) -> None:
    first = reconcile(completed, certify=True)
    old_reads = len(completed["quiet_calls"])
    with pytest.raises(LocalConvergenceError, match="already certified"):
        reconcile(completed, certify=True)
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) == first
    assert len(completed["quiet_calls"]) == old_reads
    assert len(completed["writes"]) == 1


@pytest.mark.parametrize(
    "local_bytes,expected",
    [
        ("predecessor", "PREDECESSOR_VISIBLE_NO_RETRY_AUTHORITY"),
        ("missing", "ACTIVE_RECEIPT_MISSING_MANUAL_RECOVERY_REQUIRED"),
        ("unknown", "UNKNOWN_ACTIVE_RECEIPT_QUARANTINE_REQUIRED"),
    ],
)
def test_uncertain_state_classified_without_permission(
    completed: dict[str, Any], local_bytes: str, expected: str
) -> None:
    path = completed["active"]
    if local_bytes == "predecessor":
        path.write_bytes(completed["old"])
    elif local_bytes == "missing":
        path.unlink()
    else:
        path.write_bytes(b"unfamiliar")
    result = reconcile(completed)
    assert result.status == expected
    assert result.authority.startswith("NO_RETRY")
    with pytest.raises(LocalConvergenceError, match="successor not present"):
        reconcile(completed, certify=True)
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None
    assert len(completed["writes"]) == 1
    assert (completed["local"] / "pending-slot-recovery.json").exists()


@pytest.mark.parametrize(
    "field",
    [
        "all_prior_writer_operations_terminated",
        "exclusive_os_fence_held",
        "no_unaccounted_writer_in_flight",
        "local_target_durability_independently_checked",
        "candidate_physical_bytes_independently_reaudited",
    ],
)
def test_unproven_writer_quiescence_refuses_every_path(
    completed: dict[str, Any], field: str
) -> None:
    original = completed["quiet"]

    def bad(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(LocalConvergenceError, match="writer still in flight"):
        reconcile(completed, independently_confirm_quiescence=bad)
    with pytest.raises(LocalConvergenceError, match="writer still in flight"):
        reconcile(completed, certify=True, independently_confirm_quiescence=bad)
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize(
    "field",
    [
        "installation_id",
        "transaction_id",
        "dispatch_claim_sha256",
        "target_identity_sha256",
        "writer_fence_sha256",
        "termination_evidence_sha256",
    ],
)
def test_forged_writer_evidence_refused(completed: dict[str, Any], field: str) -> None:
    prior = completed["quiet"]

    def bad(req: WitnessCommitRequest, ctx: object) -> Any:
        wrong = (
            "bad"
            if field.endswith("_evidence_sha256") or field == "writer_fence_sha256"
            else "0" * (32 if field in ("installation_id", "transaction_id") else 64)
        )
        return replace(prior(req, ctx), **{field: wrong})

    with pytest.raises(LocalConvergenceError, match="writer still in flight"):
        reconcile(completed, independently_confirm_quiescence=bad)


@pytest.mark.parametrize("context", (None, "teacher", "outsider", True))
def test_unauthorized_actor_refused(completed: dict[str, Any], context: object) -> None:
    with pytest.raises(LocalConvergenceError, match="authorization"):
        reconcile(completed, service_context=context)
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None


def test_changed_capsule_refused(completed: dict[str, Any]) -> None:
    prior = completed["read_local"]

    def bad(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(prior(req, ctx), recovery_capsule_sha256="0" * 64)

    with pytest.raises(LocalConvergenceError, match="capsule changed"):
        reconcile(completed, independently_read_local_receipt=bad)


def test_missing_durable_dispatch_claim_refused(completed: dict[str, Any]) -> None:
    completed["db"].execute("DELETE FROM plan_local_receipt_dispatch_v1")
    with pytest.raises(LocalConvergenceError, match="claim drifted"):
        reconcile(completed, certify=True)


def test_forged_claim_refused_before_readers(completed: dict[str, Any]) -> None:
    forged = replace(completed["claim"], successor_sha256="0" * 64)
    with pytest.raises(LocalConvergenceError, match="forged dispatch"):
        reconcile(completed, claim=forged)


def test_wrong_witness_key_refused(completed: dict[str, Any]) -> None:
    key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(LocalConvergenceError, match="transaction uncertain"):
        reconcile(completed, pinned_public_key=key)
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None


def test_readback_drift_between_samples_refuses_commit(
    completed: dict[str, Any],
) -> None:
    original = completed["read_local"]
    count = 0

    def drift(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal count
        count += 1
        if count == 2:
            completed["active"].write_bytes(completed["old"])
        return original(req, ctx)

    with pytest.raises(LocalConvergenceError, match="drifted"):
        reconcile(completed, certify=True, independently_read_local_receipt=drift)
    assert completed["convergence"].observe(INSTALL, service_context=ACTOR) is None


def test_reopen_durable_convergence(completed: dict[str, Any]) -> None:
    result = reconcile(completed, certify=True)
    completed["db"].close()
    db = sqlite3.connect(completed["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=completed["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    ledger = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatcher = ProtectedLocalReceiptDispatcher(ledger)
    convergence = ProtectedLocalConvergenceCoordinator(dispatcher)
    assert convergence.observe(INSTALL, service_context=ACTOR) == result
    db.close()


def test_corrupt_stored_record_refused(completed: dict[str, Any]) -> None:
    reconcile(completed, certify=True)
    with pytest.raises(sqlite3.IntegrityError):
        completed["db"].execute(
            "UPDATE plan_local_convergence_v1 SET status='WRITTEN' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    completed["db"].execute(
        "UPDATE plan_local_convergence_v1 SET successor_sha256='bad' "
        "WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(LocalConvergenceError, match="corrupt"):
        completed["convergence"].observe(INSTALL, service_context=ACTOR)


def test_revoked_service_basis_refused(completed: dict[str, Any]) -> None:
    original = completed["reader"]

    def bad(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), operator_consent_confirmed=False)

    with pytest.raises(LocalConvergenceError, match="capsule changed"):
        reconcile(completed, independently_read_evidence=bad)


def test_missing_quiescence_reader_refused(completed: dict[str, Any]) -> None:
    with pytest.raises(LocalConvergenceError, match="inputs unavailable"):
        reconcile(completed, independently_confirm_quiescence=None)


def test_nested_sqlite_transaction_refused(completed: dict[str, Any]) -> None:
    completed["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LocalConvergenceError, match="inputs unavailable"):
            reconcile(completed, certify=True)
    finally:
        completed["db"].execute("ROLLBACK")
