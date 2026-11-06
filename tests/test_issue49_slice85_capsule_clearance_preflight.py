"""Slice 85: protected non-destructive recovery capsule clearance preflight.

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
from paper_data_suite.evergreen_plan_capsule_clearance_preflight import (
    CapsuleClearancePreflightError,
    IndependentlyHeldCapsule,
    ProtectedCapsuleClearancePreflightLedger,
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


def test_preflight_persists_no_delete_and_preserves_capsule(
    converged: dict[str, Any],
) -> None:
    capsule = converged["local"] / "pending-slot-recovery.json"
    before = capsule.read_bytes()
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) is None
    record = prepare_clearance(converged)
    assert record.status == "CAPSULE_CLEARANCE_PREFLIGHT_RECORDED_NO_DELETE_DISPATCH"
    assert record.authority.startswith("NO_CAPSULE_DELETE")
    assert record.recovery_capsule_sha256 == sha(before)
    assert record.capsule_identity_sha256 == CAPSULE_ID
    assert record.successor_sha256 == sha(converged["new"])
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) == record
    assert converged["capsule_reads"] == ["independent capsule physical read"] * 2
    assert converged["active"].read_bytes() == converged["new"]
    assert capsule.read_bytes() == before
    assert len(converged["writes"]) == 1
    assert not any(
        hasattr(converged["clearance"], x)
        for x in ("delete", "clear", "launch", "rollback", "retry", "dispatch")
    )


def test_duplicate_preflight_refused_before_physical_read(
    converged: dict[str, Any],
) -> None:
    previous = prepare_clearance(converged)
    count = len(converged["capsule_reads"])
    with pytest.raises(CapsuleClearancePreflightError, match="already recorded"):
        prepare_clearance(converged)
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) == previous
    assert len(converged["capsule_reads"]) == count


def test_protected_db_reopened_preserves_preflight_once(
    converged: dict[str, Any],
) -> None:
    first = prepare_clearance(converged)
    converged["db"].close()
    db = sqlite3.connect(converged["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=converged["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    ledger = ProtectedLocalPrewriteUncertaintyLedger(planner)
    dispatch = ProtectedLocalReceiptDispatcher(ledger)
    convergence = ProtectedLocalConvergenceCoordinator(dispatch)
    preflight = ProtectedCapsuleClearancePreflightLedger(convergence)
    assert preflight.observe(INSTALL, service_context=ACTOR) == first
    converged["clearance"] = preflight
    with pytest.raises(CapsuleClearancePreflightError, match="already recorded"):
        prepare_clearance(converged)
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
        ("dispatch_claim_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("recovery_capsule_sha256", "f" * 64),
        ("independently_fenced_evidence_sha256", "f" * 64),
        ("status", "LAUNCH_AUTHORIZED"),
        ("authority", "DELETE_ALLOWED"),
    ],
)
def test_forged_convergence_refused_before_any_capsule_read(
    converged: dict[str, Any], field: str, value: object
) -> None:
    forged = replace(converged["certified"], **{field: value})
    with pytest.raises(CapsuleClearancePreflightError):
        prepare_clearance(converged, convergence=forged)
    assert converged["capsule_reads"] == []
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize("context", (None, "teacher", "other-service", True))
def test_unprivileged_actor_refused(converged: dict[str, Any], context: object) -> None:
    with pytest.raises(CapsuleClearancePreflightError, match="authorization"):
        prepare_clearance(converged, service_context=context)
    assert converged["capsule_reads"] == []


@pytest.mark.parametrize(
    "field",
    (
        "capsule_is_protected_regular_file",
        "parent_directory_protected",
        "exclusive_service_capsule_fence_held",
        "no_other_capsule_writer_can_start",
    ),
)
def test_capsule_custody_flags_required(converged: dict[str, Any], field: str) -> None:
    original = converged["capsule_reader"]

    def weak(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(CapsuleClearancePreflightError, match="capsule bytes"):
        prepare_clearance(converged, independently_read_capsule=weak)
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) is None


def test_actual_capsule_drift_fails_closed(converged: dict[str, Any]) -> None:
    (converged["local"] / "pending-slot-recovery.json").write_bytes(b"altered")
    with pytest.raises(CapsuleClearancePreflightError, match="capsule bytes"):
        prepare_clearance(converged)
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) is None


def test_no_capsule_file_fails_closed(converged: dict[str, Any]) -> None:
    (converged["local"] / "pending-slot-recovery.json").unlink()
    with pytest.raises(CapsuleClearancePreflightError, match="inspection unavailable"):
        prepare_clearance(converged)


def test_missing_actual_convergence_refused(converged: dict[str, Any]) -> None:
    converged["db"].execute("DELETE FROM plan_local_convergence_v1")
    with pytest.raises(CapsuleClearancePreflightError, match="convergence absent"):
        prepare_clearance(converged)
    assert converged["capsule_reads"] == []


def test_active_predecessor_refused_and_capsule_retained(
    converged: dict[str, Any],
) -> None:
    converged["active"].write_bytes(converged["old"])
    with pytest.raises(CapsuleClearancePreflightError, match="successor no longer"):
        prepare_clearance(converged)
    assert (converged["local"] / "pending-slot-recovery.json").exists()


def test_capsule_changes_between_readbacks_refused(
    converged: dict[str, Any],
) -> None:
    original = converged["capsule_reader"]
    calls = 0

    def changing(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            (converged["local"] / "pending-slot-recovery.json").write_bytes(b"bad")
        return original(req, ctx)

    with pytest.raises(CapsuleClearancePreflightError, match="drifted"):
        prepare_clearance(converged, independently_read_capsule=changing)
    assert converged["clearance"].observe(INSTALL, service_context=ACTOR) is None


def test_writer_inflight_blocks_clearance(converged: dict[str, Any]) -> None:
    original = converged["quiet"]

    def in_flight(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), no_unaccounted_writer_in_flight=False)

    with pytest.raises(CapsuleClearancePreflightError, match="transaction uncertain"):
        prepare_clearance(converged, independently_confirm_quiescence=in_flight)


def test_capsule_identity_must_be_service_pinned(converged: dict[str, Any]) -> None:
    with pytest.raises(CapsuleClearancePreflightError, match="capsule bytes"):
        prepare_clearance(converged, pinned_capsule_identity_sha256="f" * 64)


def test_bad_witness_key_fails_closed(converged: dict[str, Any]) -> None:
    another = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    with pytest.raises(CapsuleClearancePreflightError, match="transaction uncertain"):
        prepare_clearance(converged, pinned_public_key=another)


def test_read_only_stored_row_detects_corruption(converged: dict[str, Any]) -> None:
    prepare_clearance(converged)
    with pytest.raises(sqlite3.IntegrityError):
        converged["db"].execute(
            "UPDATE plan_capsule_clearance_preflight_v1 SET status='BAD' "
            "WHERE installation_id=?",
            (INSTALL,),
        )
    converged["db"].execute(
        "UPDATE plan_capsule_clearance_preflight_v1 "
        "SET capsule_identity_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(CapsuleClearancePreflightError, match="corrupt"):
        converged["clearance"].observe(INSTALL, service_context=ACTOR)


def test_invalid_capsule_preflight_database_transaction(
    converged: dict[str, Any],
) -> None:
    converged["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(
            CapsuleClearancePreflightError, match="authorization/inputs"
        ):
            prepare_clearance(converged)
    finally:
        converged["db"].execute("ROLLBACK")


def test_no_capsule_writer_or_delete_api(converged: dict[str, Any]) -> None:
    assert not any(
        hasattr(converged["clearance"], name)
        for name in (
            "delete_capsule",
            "clear_capsule",
            "delete",
            "unlink",
            "publish",
            "recover",
            "rollback",
            "launch",
            "dispatch",
            "retry",
            "activate",
        )
    )
    assert (converged["local"] / "pending-slot-recovery.json").exists()
