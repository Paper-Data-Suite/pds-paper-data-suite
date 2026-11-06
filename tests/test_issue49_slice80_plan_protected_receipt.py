"""Slice 80: atomic protected receipt record, NOT a local active receipt.

Synthetic keys/service roles and SQLite prove ordered code contracts, not
independent OS/process custody or a production launch capability.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import fields, replace
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
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedPlanReceiptError,
    ProtectedPlanReceiptWriter,
    ProtectedServiceReceiptRecord,
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


def record(scene: dict[str, Any], **changes: Any) -> ProtectedServiceReceiptRecord:
    inputs: dict[str, Any] = {
        "request_bytes": scene["raw"],
        "reservation": scene["reservation"],
        "preclaim": scene["preclaim"],
        "service_context": ACTOR,
        "independently_read_evidence": scene["reader"],
        "witness_transport": scene["witness"],
        "pinned_public_key": scene["public"],
        "now": NOW,
    }
    return scene["writer"].record_once(**(inputs | changes))


def test_atomic_protected_record_keeps_pending_capsule(scene: dict[str, Any]) -> None:
    untouched = {p.name: p.read_bytes() for p in scene["local"].iterdir()}
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None
    result = record(scene)
    assert result.status == "PROTECTED_RECEIPT_RECORDED_LOCAL_RECOVERY_PENDING"
    assert result.authority.startswith("NO_LOCAL_RECEIPT_PUBLICATION")
    assert result.successor_sha256 == sha(scene["new"])
    assert result.successor_generation == 2 and result.witnessed_revision == 2
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) == result
    assert scene["witness_reads"] == ["signed_witness"]
    assert {p.name: p.read_bytes() for p in scene["local"].iterdir()} == untouched
    assert (
        scene["preclaims"].observe(INSTALL, service_context=ACTOR) == scene["preclaim"]
    )
    assert (
        scene["fence"].observe(INSTALL, service_context=ACTOR) == scene["reservation"]
    )
    assert not any(
        hasattr(scene["writer"], name)
        for name in ("clear", "activate", "launch", "rollback", "switch")
    )


def test_once_only_replay_refused(scene: dict[str, Any]) -> None:
    previous = record(scene)
    with pytest.raises(ProtectedPlanReceiptError, match="already recorded"):
        record(scene)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) == previous
    assert len(scene["witness_reads"]) == 1


def test_reopen_protected_service_database(scene: dict[str, Any]) -> None:
    original = record(scene)
    scene["db"].close()
    with sqlite3.connect(scene["db_path"], isolation_level=None) as reopened:
        fence = ProtectedPlanFinalizationFence(reopened, authorize=scene["authorize"])
        preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
        writer = ProtectedPlanReceiptWriter(preclaims)
        assert writer.observe(INSTALL, service_context=ACTOR) == original
        with pytest.raises(ProtectedPlanReceiptError, match="already recorded"):
            writer.record_once(
                scene["raw"],
                scene["reservation"],
                scene["preclaim"],
                service_context=ACTOR,
                independently_read_evidence=scene["reader"],
                witness_transport=scene["witness"],
                pinned_public_key=scene["public"],
                now=NOW,
            )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("installation_id", "b" * 32),
        ("transaction_id", "b" * 32),
        ("request_sha256", "0" * 64),
        ("successor_sha256", "0" * 64),
        ("successor_generation", 8),
        ("witness_revision", 10),
        ("finalization_reservation_sha256", "1" * 64),
        ("independent_evidence_sha256", "1" * 64),
        ("status", "ALREADY_PUBLISHED"),
        ("authority", "LAUNCH_ALLOWED"),
        ("successor_generation", True),
    ],
)
def test_forged_preclaim_refused(
    scene: dict[str, Any], field: str, bad: object
) -> None:
    changed = replace(scene["preclaim"], **{field: bad})
    with pytest.raises(ProtectedPlanReceiptError):
        record(scene, preclaim=changed)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None
    assert scene["witness_reads"] == []


@pytest.mark.parametrize(
    "field,bad",
    [
        ("request_sha256", "0" * 64),
        ("successor_sha256", "0" * 64),
        ("successor_generation", True),
        ("witness_revision", 7),
        ("status", "COMPLETE"),
        ("authority", "ACTIVATE"),
        ("selection_sha256", "0" * 64),
        ("recovery_capsule_sha256", "0" * 64),
    ],
)
def test_forged_reservation_refused(
    scene: dict[str, Any], field: str, bad: object
) -> None:
    changed = replace(scene["reservation"], **{field: bad})
    with pytest.raises(ProtectedPlanReceiptError):
        record(scene, reservation=changed)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize("actor", [None, "teacher", "other-service", True])
def test_unprivileged_actor_denied(scene: dict[str, Any], actor: object) -> None:
    with pytest.raises(ProtectedPlanReceiptError, match="authorization"):
        record(scene, service_context=actor)
    with pytest.raises(ProtectedPlanReceiptError, match="authorization"):
        scene["writer"].observe(INSTALL, service_context=actor)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_actual_preclaim_refused(scene: dict[str, Any]) -> None:
    scene["db"].execute("DELETE FROM plan_publication_preclaim_v1")
    with pytest.raises(ProtectedPlanReceiptError, match="preimages"):
        record(scene)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_actual_reservation_refused(scene: dict[str, Any]) -> None:
    scene["db"].execute("DELETE FROM plan_finalization_fence_v1")
    with pytest.raises(ProtectedPlanReceiptError, match="preimages"):
        record(scene)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_evidence_reader_fails_closed(scene: dict[str, Any]) -> None:
    with pytest.raises(ProtectedPlanReceiptError, match="inputs missing"):
        record(scene, independently_read_evidence=None)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize(
    "field",
    (
        "all_writers_stopped",
        "independently_reaudited_bytes",
        "operator_consent_confirmed",
    ),
)
def test_revoked_independent_approval_fails_closed(
    scene: dict[str, Any], field: str
) -> None:
    original = scene["reader"]

    def revoked(req: WitnessCommitRequest, ctx: object) -> object:
        return replace(original(req, ctx), **{field: False})

    with pytest.raises(ProtectedPlanReceiptError, match="changed"):
        record(scene, independently_read_evidence=revoked)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None
    assert scene["witness_reads"] == []


def test_reader_exception_fails_closed(scene: dict[str, Any]) -> None:
    def unavailable(req: WitnessCommitRequest, ctx: object) -> Any:
        raise RuntimeError("service offline")

    with pytest.raises(ProtectedPlanReceiptError, match="unavailable"):
        record(scene, independently_read_evidence=unavailable)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_wrong_witness_pin_fails_closed(scene: dict[str, Any]) -> None:
    with pytest.raises(ProtectedPlanReceiptError, match="signed successor head"):
        record(scene, pinned_public_key=b"x" * 32)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_witness_outage_fails_closed(scene: dict[str, Any]) -> None:
    def outage(challenge: bytes) -> bytes:
        raise OSError("network unavailable")

    with pytest.raises(ProtectedPlanReceiptError, match="signed successor head"):
        record(scene, witness_transport=outage)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_signed_predecessor_is_not_publication(scene: dict[str, Any]) -> None:
    key = Ed25519PrivateKey.generate()
    previous_key = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    db = sqlite3.connect(":memory:", isolation_level=None)
    store = MonotonicCheckpointStore(
        db,
        witness_id="independent_witness",
        authorize=lambda install, operation, context: (
            install == INSTALL and context == ACTOR
        ),
        sign=key.sign,
    )
    store.commit_receipt(INSTALL, scene["old"], context=ACTOR)
    with pytest.raises(ProtectedPlanReceiptError, match="signed successor head"):
        record(
            scene,
            pinned_public_key=previous_key,
            witness_transport=lambda challenge: store.answer_challenge(
                challenge, context=ACTOR, now=NOW
            ),
        )
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_invalid_request_rejected_before_signed_read(scene: dict[str, Any]) -> None:
    with pytest.raises(ProtectedPlanReceiptError):
        record(scene, request_bytes=scene["raw"] + b" ")
    assert scene["witness_reads"] == []


@pytest.mark.parametrize("bad", [None, b"short", True, "wrong"])
def test_invalid_pinned_key_refused(scene: dict[str, Any], bad: object) -> None:
    with pytest.raises(ProtectedPlanReceiptError, match="inputs missing"):
        record(scene, pinned_public_key=bad)
    assert scene["writer"].observe(INSTALL, service_context=ACTOR) is None


def test_read_only_observation_detects_corrupted_record(scene: dict[str, Any]) -> None:
    record(scene)
    scene["db"].execute(
        "UPDATE plan_protected_receipt_v1 SET successor_sha256 = ? "
        "WHERE installation_id = ?",
        ("0" * 64, INSTALL),
    )
    with pytest.raises(ProtectedPlanReceiptError, match="corrupt"):
        scene["writer"].observe(INSTALL, service_context=ACTOR)


def test_sql_status_constraint_rejects_tamper(scene: dict[str, Any]) -> None:
    record(scene)
    with pytest.raises(sqlite3.IntegrityError):
        scene["db"].execute(
            "UPDATE plan_protected_receipt_v1 SET status = 'ACTIVE' "
            "WHERE installation_id = ?",
            (INSTALL,),
        )


def test_invalid_active_transaction_refused(scene: dict[str, Any]) -> None:
    scene["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ProtectedPlanReceiptError, match="inputs missing"):
            record(scene)
    finally:
        scene["db"].execute("ROLLBACK")


def test_db_cannot_recreate_writer_inside_transaction(scene: dict[str, Any]) -> None:
    scene["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ProtectedPlanReceiptError, match="connection"):
            ProtectedPlanReceiptWriter(scene["preclaims"])
    finally:
        scene["db"].execute("ROLLBACK")


def test_record_has_no_bearer_capability(scene: dict[str, Any]) -> None:
    result = record(scene)
    assert len(fields(result)) == 11
    assert not hasattr(result, "receipt_bytes")
    assert not hasattr(result, "authorize")
    assert not hasattr(result, "clear_recovery")
    assert scene["local"].joinpath("pending-slot-recovery.json").exists()
