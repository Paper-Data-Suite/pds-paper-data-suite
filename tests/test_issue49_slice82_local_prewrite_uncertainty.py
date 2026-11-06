"""Slice 82: write-ahead uncertainty, simulated physical recovery readbacks.

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
    LocalPrewriteUncertaintyError,
    ProtectedLocalPrewriteUncertaintyLedger,
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


def test_arm_is_durable_and_local_files_untouched(prepared: dict[str, Any]) -> None:
    before = {p.name: p.read_bytes() for p in prepared["local"].iterdir()}
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) is None
    result = arm(prepared)
    assert result.status == "LOCAL_PREWRITE_UNCERTAINTY_ARMED_NO_WRITER_DISPATCH"
    assert result.authority.startswith("NO_RETRY_WRITE_CAPSULE_CLEAR")
    assert result.predecessor_receipt_sha256 == sha(prepared["old"])
    assert result.successor_sha256 == sha(prepared["new"])
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) == result
    assert {p.name: p.read_bytes() for p in prepared["local"].iterdir()} == before
    assert not any(
        hasattr(prepared["ledger"], name)
        for name in (
            "write",
            "publish",
            "clear",
            "rollback",
            "activate",
            "launch",
            "retry",
        )
    )


def test_replay_refused_even_if_same_inputs(prepared: dict[str, Any]) -> None:
    prior = arm(prepared)
    reads = len(prepared["witness_reads"])
    with pytest.raises(LocalPrewriteUncertaintyError, match="already armed"):
        arm(prepared)
    assert len(prepared["witness_reads"]) == reads
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) == prior


def test_prewrite_survives_reopening_service_db(prepared: dict[str, Any]) -> None:
    prior = arm(prepared)
    prepared["db"].close()
    db = sqlite3.connect(prepared["db_path"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(db, authorize=prepared["authorize"])
    preclaims = ProtectedPlanPublicationPreclaimLedger(fence)
    writer = ProtectedPlanReceiptWriter(preclaims)
    planner = ProtectedLocalReceiptDeploymentPlanner(writer)
    ledger = ProtectedLocalPrewriteUncertaintyLedger(planner)
    assert ledger.observe(INSTALL, service_context=ACTOR) == prior
    prepared["ledger"] = ledger
    with pytest.raises(LocalPrewriteUncertaintyError, match="already armed"):
        arm(prepared)
    db.close()


def test_cannot_classify_without_marker(prepared: dict[str, Any]) -> None:
    with pytest.raises(LocalPrewriteUncertaintyError, match="marker absent"):
        classify(prepared)
    assert prepared["read_calls"] == []


@pytest.mark.parametrize(
    "observed,expected",
    [
        ("predecessor", "PREDECESSOR_VISIBLE_NO_RETRY_AUTHORITY"),
        ("successor", "SUCCESSOR_VISIBLE_RECOVERY_STILL_PENDING"),
        ("different", "UNKNOWN_LOCAL_RECEIPT_QUARANTINE_REQUIRED"),
        ("missing", "LOCAL_RECEIPT_MISSING_MANUAL_RECOVERY_REQUIRED"),
    ],
)
def test_observation_outcomes_never_authorize_recovery(
    prepared: dict[str, Any], observed: str, expected: str
) -> None:
    arm(prepared)
    if observed == "successor":
        prepared["active"].write_bytes(prepared["new"])
    elif observed == "different":
        prepared["active"].write_bytes(b"not a canonical receipt")
    elif observed == "missing":
        prepared["active"].unlink()
    before_capsule = (prepared["local"] / "pending-slot-recovery.json").read_bytes()
    result = classify(prepared)
    assert result.status == expected
    assert result.authority.startswith("NO_RETRY_WRITE_CAPSULE_CLEAR")
    assert result.witness_revision == 2
    assert (
        prepared["local"] / "pending-slot-recovery.json"
    ).read_bytes() == before_capsule
    assert prepared["read_calls"] == ["protected-readback"]


@pytest.mark.parametrize("actor", [None, "teacher", "untrusted", True])
def test_unauthorized_prewrite_arm_refused(
    prepared: dict[str, Any], actor: object
) -> None:
    with pytest.raises(LocalPrewriteUncertaintyError, match="authorization"):
        arm(prepared, service_context=actor)
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize("actor", [None, "teacher", True])
def test_unauthorized_readback_refused(prepared: dict[str, Any], actor: object) -> None:
    arm(prepared)
    with pytest.raises(LocalPrewriteUncertaintyError, match="authorization"):
        classify(prepared, service_context=actor)
    assert prepared["read_calls"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "f" * 32),
        ("transaction_id", "f" * 32),
        ("request_sha256", "f" * 64),
        ("successor_sha256", "f" * 64),
        ("predecessor_receipt_sha256", "f" * 64),
        ("target_identity_sha256", "f" * 64),
        ("local_snapshot_sha256", "f" * 64),
        ("protected_receipt_record_sha256", "f" * 64),
        ("witness_revision", 7),
        ("status", "WRITTEN"),
        ("authority", "RETRY_ALLOWED"),
    ],
)
def test_untrusted_intent_mismatch_refused(
    prepared: dict[str, Any], field: str, value: object
) -> None:
    forged = replace(prepared["intent"], **{field: value})
    expected_error = "basis"
    if field in ("target_identity_sha256", "local_snapshot_sha256"):
        expected_error = "durable protected"
    with pytest.raises(LocalPrewriteUncertaintyError, match=expected_error):
        arm(prepared, intent=forged)
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_actual_intent_refused(prepared: dict[str, Any]) -> None:
    prepared["db"].execute("DELETE FROM plan_local_deployment_intent_v1")
    with pytest.raises(LocalPrewriteUncertaintyError, match="durable protected"):
        arm(prepared)


def test_predecessor_changed_before_arming_refused(prepared: dict[str, Any]) -> None:
    prepared["active"].write_bytes(prepared["new"])
    with pytest.raises(LocalPrewriteUncertaintyError, match="changed"):
        arm(prepared)
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_local_snapshot_changed_before_arming_refused(prepared: dict[str, Any]) -> None:
    original = prepared["physical_reader"]

    def changed(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), local_snapshot_sha256="f" * 64)

    with pytest.raises(LocalPrewriteUncertaintyError, match="changed"):
        arm(prepared, independently_read_local=changed)


def test_unsigned_witness_never_arms(prepared: dict[str, Any]) -> None:
    def outage(challenge: bytes) -> bytes:
        raise OSError("witness unavailable")

    with pytest.raises(LocalPrewriteUncertaintyError, match="signed successor"):
        arm(prepared, witness_transport=outage)
    assert prepared["ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_recovery_capsule_drift_refused_during_inspection(
    prepared: dict[str, Any],
) -> None:
    arm(prepared)
    original = prepared["read_local"]

    def changed(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), recovery_capsule_sha256="f" * 64)

    with pytest.raises(LocalPrewriteUncertaintyError, match="changed"):
        classify(prepared, independently_read_local_receipt=changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("protected_target_parent", False),
        ("protected_ordinary_active_file", False),
        ("protected_ordinary_capsule", False),
        ("installation_writers_exclusively_fenced", False),
        ("candidate_physical_bytes_rechecked", False),
        ("target_identity_sha256", "f" * 64),
        ("active_receipt_bytes", b"a" * 20000),
    ],
)
def test_unsafe_independent_readback_refused(
    prepared: dict[str, Any], field: str, value: object
) -> None:
    arm(prepared)
    original = prepared["read_local"]

    def changed(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), **{field: value})

    with pytest.raises(LocalPrewriteUncertaintyError, match="changed"):
        classify(prepared, independently_read_local_receipt=changed)


def test_prewrite_corruption_fails_closed(prepared: dict[str, Any]) -> None:
    arm(prepared)
    with pytest.raises(sqlite3.IntegrityError):
        prepared["db"].execute(
            "UPDATE plan_local_prewrite_uncertainty_v1 "
            "SET status='BAD' WHERE installation_id=?",
            (INSTALL,),
        )
    prepared["db"].execute(
        "UPDATE plan_local_prewrite_uncertainty_v1 "
        "SET request_sha256='invalid' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(LocalPrewriteUncertaintyError, match="corrupt"):
        prepared["ledger"].observe(INSTALL, service_context=ACTOR)


def test_protected_evidence_revoked(prepared: dict[str, Any]) -> None:
    original = prepared["reader"]

    def revoked(req: WitnessCommitRequest, ctx: object) -> Any:
        return replace(original(req, ctx), operator_consent_confirmed=False)

    with pytest.raises(LocalPrewriteUncertaintyError, match="changed"):
        arm(prepared, independently_read_evidence=revoked)


def test_invalid_transaction_refused(prepared: dict[str, Any]) -> None:
    prepared["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LocalPrewriteUncertaintyError, match="unavailable"):
            arm(prepared)
    finally:
        prepared["db"].execute("ROLLBACK")


def test_marker_is_not_a_dispatch_or_launch_grant(prepared: dict[str, Any]) -> None:
    marker = arm(prepared)
    assert not any(
        hasattr(marker, a)
        for a in (
            "write",
            "dispatch",
            "activate",
            "clear",
            "launch",
            "rollback",
            "retry",
        )
    )
