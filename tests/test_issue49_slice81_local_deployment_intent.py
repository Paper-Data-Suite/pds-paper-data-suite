"""Slice 81: physical predecessor and capsule-bound protected deployment intent.

Uses real Slice 78-80 SQLite flows and signed synthetic witness. Does not
create service OS isolation or write a local active receipt.
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
    LocalDeploymentIntentError,
    ProtectedLocalReceiptDeploymentPlanner,
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


def test_prepare_exact_intent_keeps_active_predecessor_and_capsule(
    ready: dict[str, Any],
) -> None:
    prior_files = {p.name: p.read_bytes() for p in ready["local"].iterdir()}
    before = ready["planner"].observe(INSTALL, service_context=ACTOR)
    assert before is None
    intent = prepare(ready)
    assert intent.status == "LOCAL_RECEIPT_DEPLOYMENT_PREPARED_NO_FILE_WRITE"
    assert intent.authority.startswith("NO_LOCAL_RECEIPT_WRITE")
    assert intent.predecessor_receipt_sha256 == sha(ready["old"])
    assert intent.successor_sha256 == sha(ready["new"])
    assert intent.target_identity_sha256 == TARGET
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) == intent
    assert {p.name: p.read_bytes() for p in ready["local"].iterdir()} == prior_files
    assert ready["writer"].observe(INSTALL, service_context=ACTOR) == ready["record"]
    assert not any(
        hasattr(ready["planner"], name)
        for name in (
            "publish",
            "activate",
            "launch",
            "rollback",
            "clear",
            "switch",
            "dispatch",
        )
    )
    assert ready["physical_calls"] == ["read-protected-local-state"]


def test_preparation_replay_is_always_refused(ready: dict[str, Any]) -> None:
    first = prepare(ready)
    before = len(ready["witness_reads"])
    with pytest.raises(LocalDeploymentIntentError, match="already prepared"):
        prepare(ready)
    assert len(ready["witness_reads"]) == before
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) == first


def test_reopen_protected_database_preserves_one_shot(ready: dict[str, Any]) -> None:
    first = prepare(ready)
    ready["db"].close()
    db = sqlite3.connect(ready["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=ready["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    assert planner.observe(INSTALL, service_context=ACTOR) == first
    ready["planner"] = planner
    with pytest.raises(LocalDeploymentIntentError, match="already prepared"):
        prepare(ready)
    db.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "f" * 32),
        ("transaction_id", "f" * 32),
        ("request_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("witnessed_revision", 9),
        ("successor_generation", 9),
        ("finalization_reservation_sha256", "f" * 64),
        ("publication_preclaim_sha256", "f" * 64),
        ("independent_evidence_sha256", "f" * 64),
        ("status", "ACTIVE"),
        ("authority", "LAUNCH"),
    ],
)
def test_forged_record_cannot_prepare(
    ready: dict[str, Any], field: str, value: object
) -> None:
    with pytest.raises(LocalDeploymentIntentError, match="inputs invalid"):
        prepare(ready, record=replace(ready["record"], **{field: value}))
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) is None
    assert ready["physical_calls"] == []


@pytest.mark.parametrize("actor", (None, "teacher", "another-service", True))
def test_unprivileged_actor_refused(ready: dict[str, Any], actor: object) -> None:
    with pytest.raises(LocalDeploymentIntentError, match="authorization"):
        prepare(ready, service_context=actor)
    assert ready["physical_calls"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "f" * 32),
        ("transaction_id", "f" * 32),
        ("request_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("predecessor_receipt_sha256", "f" * 64),
        ("current_active_receipt_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("proposal_sha256", "f" * 64),
        ("selection_sha256", "f" * 64),
        ("recovery_capsule_sha256", "f" * 64),
        ("journal_sha256", "f" * 64),
        ("local_snapshot_sha256", "bad"),
        ("prior_receipt_is_protected_ordinary_file", False),
        ("capsule_is_protected_ordinary_file", False),
        ("candidate_physical_bytes_rechecked", False),
        ("installation_writers_exclusively_fenced", False),
    ],
)
def test_mismatched_independent_local_state_fails_closed(
    ready: dict[str, Any], field: str, value: object
) -> None:
    original = ready["physical_reader"]

    def changed(
        req: WitnessCommitRequest, ctx: object
    ) -> IndependentLocalDeploymentInspection:
        return replace(original(req, ctx), **{field: value})

    with pytest.raises(LocalDeploymentIntentError, match="changed"):
        prepare(ready, independently_read_local=changed)
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) is None


def test_actual_local_predecessor_change_blocks_preparation(
    ready: dict[str, Any],
) -> None:
    ready["active"].write_bytes(ready["new"])
    with pytest.raises(LocalDeploymentIntentError, match="changed"):
        prepare(ready)
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) is None


def test_independent_local_reader_outage(ready: dict[str, Any]) -> None:
    def outage(req: WitnessCommitRequest, ctx: object) -> Any:
        raise OSError("independent reader unavailable")

    with pytest.raises(LocalDeploymentIntentError, match="inspection unavailable"):
        prepare(ready, independently_read_local=outage)


def test_absent_actual_protected_record_refused(ready: dict[str, Any]) -> None:
    ready["db"].execute("DELETE FROM plan_protected_receipt_v1")
    with pytest.raises(LocalDeploymentIntentError, match="records differ"):
        prepare(ready)
    assert ready["physical_calls"] == []


def test_changed_service_basis_refused(ready: dict[str, Any]) -> None:
    original = ready["reader"]

    def denied(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), operator_consent_confirmed=False)

    with pytest.raises(LocalDeploymentIntentError, match="consent changed"):
        prepare(ready, independently_read_evidence=denied)
    assert ready["physical_calls"] == []


def test_predecessor_signed_head_cannot_prepare(ready: dict[str, Any]) -> None:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    db = sqlite3.connect(":memory:", isolation_level=None)
    witness_store = MonotonicCheckpointStore(
        db,
        witness_id="independent_witness",
        authorize=lambda ins, op, ctx: ins == INSTALL and ctx == ACTOR,
        sign=key.sign,
    )
    witness_store.commit_receipt(INSTALL, ready["old"], context=ACTOR)
    with pytest.raises(LocalDeploymentIntentError, match="signed successor head"):
        prepare(
            ready,
            pinned_public_key=public,
            witness_transport=lambda challenge: witness_store.answer_challenge(
                challenge,
                context=ACTOR,
                now=NOW,
            ),
        )
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) is None
    db.close()


@pytest.mark.parametrize("bad", (None, b"short", True, "wrong"))
def test_invalid_witness_key_refused(ready: dict[str, Any], bad: object) -> None:
    with pytest.raises(LocalDeploymentIntentError, match="inputs invalid"):
        prepare(ready, pinned_public_key=bad)
    assert ready["physical_calls"] == []


def test_invalid_configured_target_refused(ready: dict[str, Any]) -> None:
    with pytest.raises(LocalDeploymentIntentError, match="inputs invalid"):
        prepare(ready, pinned_target_identity_sha256="wrong")
    assert ready["physical_calls"] == []


def test_invalid_active_transaction_refused(ready: dict[str, Any]) -> None:
    ready["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LocalDeploymentIntentError, match="inputs invalid"):
            prepare(ready)
    finally:
        ready["db"].execute("ROLLBACK")


def test_durable_row_status_constraint_and_integrity(ready: dict[str, Any]) -> None:
    prepare(ready)
    with pytest.raises(sqlite3.IntegrityError):
        ready["db"].execute(
            "UPDATE plan_local_deployment_intent_v1 "
            "SET status='BAD' WHERE installation_id=?",
            (INSTALL,),
        )
    ready["db"].execute(
        "UPDATE plan_local_deployment_intent_v1 "
        "SET target_identity_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(LocalDeploymentIntentError, match="corrupt"):
        ready["planner"].observe(INSTALL, service_context=ACTOR)


def test_no_local_mutation_on_unsigned_or_outage(ready: dict[str, Any]) -> None:
    old = {p.name: p.read_bytes() for p in ready["local"].iterdir()}

    def outage(challenge: bytes) -> bytes:
        raise OSError("unreachable")

    with pytest.raises(LocalDeploymentIntentError, match="signed successor head"):
        prepare(ready, witness_transport=outage)
    assert {p.name: p.read_bytes() for p in ready["local"].iterdir()} == old
    assert ready["planner"].observe(INSTALL, service_context=ACTOR) is None
