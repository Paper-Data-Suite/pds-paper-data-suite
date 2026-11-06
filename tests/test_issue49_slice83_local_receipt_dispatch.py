"""Slice 83: protected once-only dispatch and independent post-write readback.

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
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    IndependentLocalDeploymentInspection,
    ProtectedLocalReceiptDeploymentPlanner,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    IndependentLocalReceiptReadback,
    ProtectedLocalPrewriteUncertaintyLedger,
)
from paper_data_suite.evergreen_plan_local_receipt_dispatch import (
    LocalReceiptDispatchError,
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


def test_claim_precedes_single_service_write_and_capsule_remains(
    armed: dict[str, Any],
) -> None:
    capsule = armed["local"] / "pending-slot-recovery.json"
    previous = capsule.read_bytes()
    result = dispatch(armed)
    assert result.status == "LOCAL_SUCCESSOR_VISIBLE_CAPSULE_RETAINED_RECOVERY_REQUIRED"
    assert result.authority.startswith("NO_REDISPATCH")
    assert armed["active"].read_bytes() == armed["new"]
    assert capsule.read_bytes() == previous
    assert armed["writes"] == ["one-protected-file-operation"]
    claim = armed["dispatcher"].observe(INSTALL, service_context=ACTOR)
    assert claim is not None
    assert claim.status == "LOCAL_RECEIPT_DISPATCH_CLAIMED_WRITE_OUTCOME_UNCERTAIN"
    assert claim.successor_sha256 == sha(armed["new"])
    assert not any(
        hasattr(armed["dispatcher"], name)
        for name in ("clear", "launch", "rollback", "reset", "retry", "activate")
    )


def test_no_replay_or_second_writer_call(armed: dict[str, Any]) -> None:
    dispatch(armed)
    with pytest.raises(LocalReceiptDispatchError, match="already claimed"):
        dispatch(armed)
    assert len(armed["writes"]) == 1


def test_reopen_service_database_preserves_claim(armed: dict[str, Any]) -> None:
    dispatch(armed)
    claim = armed["dispatcher"].observe(INSTALL, service_context=ACTOR)
    armed["db"].close()
    db = sqlite3.connect(armed["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=armed["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    ledger = ProtectedLocalPrewriteUncertaintyLedger(planner)
    new = ProtectedLocalReceiptDispatcher(ledger)
    assert new.observe(INSTALL, service_context=ACTOR) == claim
    armed["dispatcher"] = new
    with pytest.raises(LocalReceiptDispatchError, match="already claimed"):
        dispatch(armed)
    assert len(armed["writes"]) == 1
    db.close()


@pytest.mark.parametrize("actor", [None, "teacher", "outsider", True])
def test_wrong_actor_never_dispatches(armed: dict[str, Any], actor: object) -> None:
    with pytest.raises(LocalReceiptDispatchError, match="authorization"):
        dispatch(armed, service_context=actor)
    assert armed["writes"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "f" * 32),
        ("transaction_id", "f" * 32),
        ("request_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("successor_generation", 9),
        ("witness_revision", 9),
        ("predecessor_receipt_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("recovery_capsule_sha256", "f" * 64),
        ("local_snapshot_sha256", "f" * 64),
        ("protected_receipt_record_sha256", "f" * 64),
        ("local_deployment_intent_sha256", "f" * 64),
        ("status", "DISPATCHED"),
        ("authority", "LAUNCH_ALLOWED"),
    ],
)
def test_forged_prewrite_never_dispatches(
    armed: dict[str, Any], field: str, value: object
) -> None:
    bogus = replace(armed["marker"], **{field: value})
    with pytest.raises(LocalReceiptDispatchError, match="invalid non-authorizing"):
        dispatch(armed, marker=bogus)
    assert armed["writes"] == []


def test_missing_durable_marker_blocks_dispatch(armed: dict[str, Any]) -> None:
    armed["db"].execute("DELETE FROM plan_local_prewrite_uncertainty_v1")
    with pytest.raises(LocalReceiptDispatchError, match="marker changed or absent"):
        dispatch(armed)
    assert armed["writes"] == []


def test_predecessor_drift_blocks_dispatch(armed: dict[str, Any]) -> None:
    armed["active"].write_bytes(armed["new"])
    with pytest.raises(LocalReceiptDispatchError, match="predecessor"):
        dispatch(armed)
    assert armed["writes"] == []
    assert armed["dispatcher"].observe(INSTALL, service_context=ACTOR) is None


def test_capsule_mismatch_blocks_dispatch(armed: dict[str, Any]) -> None:
    original = armed["read_local"]

    def changed(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), recovery_capsule_sha256="f" * 64)

    with pytest.raises(LocalReceiptDispatchError, match="pending capsule"):
        dispatch(armed, independently_read_local_receipt=changed)
    assert armed["writes"] == []


def test_writer_exception_is_uncertain_and_never_retried(
    armed: dict[str, Any],
) -> None:
    called: list[str] = []

    def half_written(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        called.append("write-called")
        armed["active"].write_bytes(req.successor_receipt_bytes)
        raise OSError("lost acknowledgment after replacement")

    with pytest.raises(LocalReceiptDispatchError, match="outcome uncertain"):
        dispatch(armed, service_owned_write=half_written)
    assert called == ["write-called"]
    assert armed["active"].read_bytes() == armed["new"]
    assert armed["dispatcher"].observe(INSTALL, service_context=ACTOR)
    with pytest.raises(LocalReceiptDispatchError, match="already claimed"):
        dispatch(armed, service_owned_write=half_written)
    assert called == ["write-called"]
    assert (armed["local"] / "pending-slot-recovery.json").exists()


def test_writer_reports_success_but_no_replacement_fails_closed(
    armed: dict[str, Any],
) -> None:
    def no_write(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        pass

    with pytest.raises(LocalReceiptDispatchError, match="post-write receipt"):
        dispatch(armed, service_owned_write=no_write)
    assert armed["active"].read_bytes() == armed["old"]
    assert armed["dispatcher"].observe(INSTALL, service_context=ACTOR)


def test_lost_readback_after_write_is_uncertain(armed: dict[str, Any]) -> None:
    first = armed["read_local"]
    calls = 0

    def read(req: WitnessCommitRequest, ctx: object) -> Any:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("post-write reader offline")
        return first(req, ctx)

    with pytest.raises(LocalReceiptDispatchError, match="post-write verification"):
        dispatch(armed, independently_read_local_receipt=read)
    assert armed["active"].read_bytes() == armed["new"]
    assert armed["dispatcher"].observe(INSTALL, service_context=ACTOR)


def test_post_write_capsule_drift_fails_closed(armed: dict[str, Any]) -> None:
    original = armed["write"]

    def write_then_change(req: WitnessCommitRequest, target: str, ctx: object) -> None:
        original(req, target, ctx)
        (armed["local"] / "pending-slot-recovery.json").write_bytes(b"changed")

    prior = armed["read_local"]

    def check_capsule(req: WitnessCommitRequest, ctx: object) -> Any:
        seen = prior(req, ctx)
        capsule = (armed["local"] / "pending-slot-recovery.json").read_bytes()
        if capsule != b"must-remain":
            return replace(seen, recovery_capsule_sha256="f" * 64)
        return seen

    with pytest.raises(LocalReceiptDispatchError, match="post-write receipt"):
        dispatch(
            armed,
            service_owned_write=write_then_change,
            independently_read_local_receipt=check_capsule,
        )
    assert armed["dispatcher"].observe(INSTALL, service_context=ACTOR)


def test_signed_witness_outage_prevents_claim(armed: dict[str, Any]) -> None:
    def outage(challenge: bytes) -> bytes:
        raise OSError("offline")

    with pytest.raises(LocalReceiptDispatchError, match="read-only inspection"):
        dispatch(armed, witness_transport=outage)
    assert armed["dispatcher"].observe(INSTALL, service_context=ACTOR) is None
    assert armed["writes"] == []


def test_missing_callback_prevents_claim(armed: dict[str, Any]) -> None:
    with pytest.raises(LocalReceiptDispatchError, match="inputs missing"):
        dispatch(armed, service_owned_write=None)
    assert armed["writes"] == []


def test_durable_corrupt_status_fails_closed(armed: dict[str, Any]) -> None:
    dispatch(armed)
    with pytest.raises(sqlite3.IntegrityError):
        armed["db"].execute(
            "UPDATE plan_local_receipt_dispatch_v1 "
            "SET status='BAD' WHERE installation_id=?",
            (INSTALL,),
        )
    armed["db"].execute(
        "UPDATE plan_local_receipt_dispatch_v1 "
        "SET target_identity_sha256='invalid' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(LocalReceiptDispatchError, match="corrupt"):
        armed["dispatcher"].observe(INSTALL, service_context=ACTOR)


def test_active_transaction_prevents_dispatch(armed: dict[str, Any]) -> None:
    armed["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LocalReceiptDispatchError, match="inputs missing"):
            dispatch(armed)
    finally:
        armed["db"].execute("ROLLBACK")
    assert armed["writes"] == []
