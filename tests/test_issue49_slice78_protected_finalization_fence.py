"""Slice 78: independent service reservation only, never local finalization.

The SQLite DB, witness receipts and roles are synthetic test doubles. In
production service custody must be established independently of local Suite.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from paper_data_suite.evergreen_active_receipts import (
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationEvidence,
    PlanFinalizationFenceError,
    ProtectedFinalizationReservation,
    ProtectedPlanFinalizationFence,
)
from paper_data_suite.evergreen_plan_finalization_preflight import (
    PlanFinalizationPreflight,
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


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
    directory = tmp_path / "protected-service"
    directory.mkdir()
    db_file = directory / "reservation.sqlite3"
    db = sqlite3.connect(db_file, isolation_level=None)
    calls: list[tuple[str, str]] = []

    def authorize(install: str, operation: str, context: object) -> bool:
        calls.append((operation, install))
        return install == INSTALL and context == ACTOR

    reader_calls: list[str] = []

    def read(
        req: WitnessCommitRequest, context: object
    ) -> IndependentFinalizationEvidence:
        reader_calls.append("read_service_protected_basis")
        assert req == request and context == ACTOR
        return evidence

    fence = ProtectedPlanFinalizationFence(db, authorize=authorize)
    # Neither the pending marker nor the teacher workspace is touched.
    local = tmp_path / "teacher-local"
    local.mkdir()
    (local / "pending-slot-recovery.json").write_bytes(b"pending-capsule")
    (local / "student-work.txt").write_bytes(b"untouched")
    return dict(
        request=request,
        raw=raw,
        preflight=preflight,
        evidence=evidence,
        fence=fence,
        db=db,
        db_file=db_file,
        authorize=authorize,
        read=read,
        calls=calls,
        reader_calls=reader_calls,
        local=local,
    )


def reserve(scene: dict[str, Any], **kwargs: Any) -> ProtectedFinalizationReservation:
    args = {
        "request_bytes": scene["raw"],
        "preflight": scene["preflight"],
        "service_context": ACTOR,
        "independently_read_evidence": scene["read"],
    }
    return scene["fence"].reserve(**(args | kwargs))


def test_one_shot_reservation_preserves_local_capsule_and_is_not_grant(
    scene: dict[str, Any],
) -> None:
    baseline = {p.name: p.read_bytes() for p in scene["local"].iterdir()}
    before = scene["fence"].observe(INSTALL, service_context=ACTOR)
    assert before is None
    result = reserve(scene)
    assert result.status == "PREPARED_NO_ACTIVE_RECEIPT_WRITE"
    assert result.authority.startswith("NO_RECEIPT_WRITE_CAPSULE_CLEAR")
    assert result.request_sha256 == scene["preflight"].request_sha256
    assert result.independent_evidence_sha256 == "d" * 64
    assert scene["fence"].observe(INSTALL, service_context=ACTOR) == result
    assert {p.name: p.read_bytes() for p in scene["local"].iterdir()} == baseline
    assert not any(
        hasattr(scene["fence"], name)
        for name in (
            "publish",
            "activate",
            "clear",
            "launch",
            "rollback",
            "dispatch",
        )
    )
    assert scene["reader_calls"] == ["read_service_protected_basis"]


def test_replay_identical_request_refused(scene: dict[str, Any]) -> None:
    prior = reserve(scene)
    with pytest.raises(PlanFinalizationFenceError, match="already reserved"):
        reserve(scene)
    assert scene["fence"].observe(INSTALL, service_context=ACTOR) == prior


def test_reservation_survives_connection_reopen(scene: dict[str, Any]) -> None:
    prior = reserve(scene)
    scene["db"].close()
    new = sqlite3.connect(scene["db_file"], isolation_level=None)
    fence = ProtectedPlanFinalizationFence(new, authorize=scene["authorize"])
    assert fence.observe(INSTALL, service_context=ACTOR) == prior
    with pytest.raises(PlanFinalizationFenceError, match="already reserved"):
        fence.reserve(
            scene["raw"],
            scene["preflight"],
            service_context=ACTOR,
            independently_read_evidence=scene["read"],
        )
    new.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "b" * 32),
        ("transaction_id", "b" * 32),
        ("request_sha256", "0" * 64),
        ("successor_sha256", "0" * 64),
        ("generation", 3),
        ("witness_revision", 3),
        ("proposal_sha256", "0" * 64),
        ("selection_sha256", "0" * 64),
        ("recovery_capsule_sha256", "0" * 64),
        ("journal_sha256", "0" * 64),
        ("service_envelope_sha256", "0" * 64),
        ("status", "FINALIZED"),
        ("authority", "LAUNCH_ALLOWED"),
    ],
)
def test_untrusted_preflight_fields_fail_closed(
    scene: dict[str, Any], field: str, value: object
) -> None:
    wrong = replace(scene["preflight"], **{field: value})
    with pytest.raises(PlanFinalizationFenceError):
        reserve(scene, preflight=wrong)
    assert scene["fence"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_sha256", "0" * 64),
        ("installation_id", "b" * 32),
        ("transaction_id", "b" * 32),
        ("successor_sha256", "0" * 64),
        ("successor_generation", 9),
        ("witness_revision", 8),
        ("proposal_sha256", "0" * 64),
        ("selection_sha256", "0" * 64),
        ("recovery_capsule_sha256", "0" * 64),
        ("journal_sha256", "0" * 64),
        ("service_envelope_sha256", "0" * 64),
        ("independent_evidence_sha256", "0"),
        ("all_writers_stopped", False),
        ("independently_reaudited_bytes", False),
        ("operator_consent_confirmed", False),
    ],
)
def test_independent_evidence_disagreement_refused(
    scene: dict[str, Any], field: str, value: object
) -> None:
    wrong = replace(scene["evidence"], **{field: value})
    with pytest.raises(PlanFinalizationFenceError, match="service-protected"):
        reserve(scene, independently_read_evidence=lambda req, ctx: wrong)
    assert scene["fence"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize("context", ["teacher", None, True])
def test_local_actor_cannot_reserve_or_observe(
    scene: dict[str, Any], context: object
) -> None:
    with pytest.raises(PlanFinalizationFenceError, match="authorization"):
        reserve(scene, service_context=context)
    with pytest.raises(PlanFinalizationFenceError, match="authorization"):
        scene["fence"].observe(INSTALL, service_context=context)
    assert scene["reader_calls"] == []


def test_missing_or_revoked_reader_never_prepares(scene: dict[str, Any]) -> None:
    with pytest.raises(PlanFinalizationFenceError, match="reader missing"):
        reserve(scene, independently_read_evidence=None)
    with pytest.raises(PlanFinalizationFenceError, match="evidence unavailable"):
        reserve(scene, independently_read_evidence=lambda req, ctx: 1 / 0)
    assert scene["fence"].observe(INSTALL, service_context=ACTOR) is None


def test_invalid_request_bytes_refuse_before_service_reads(
    scene: dict[str, Any],
) -> None:
    with pytest.raises(PlanFinalizationFenceError):
        reserve(scene, request_bytes=scene["raw"] + b" ")
    with pytest.raises(PlanFinalizationFenceError):
        reserve(scene, request_bytes=b"not a request")
    assert scene["reader_calls"] == []


def test_corrupt_durable_state_fails_closed(scene: dict[str, Any]) -> None:
    reserve(scene)
    with pytest.raises(sqlite3.IntegrityError):
        scene["db"].execute(
            "UPDATE plan_finalization_fence_v1 SET status = 'INVALID' "
            "WHERE installation_id = ?",
            (INSTALL,),
        )
    scene["db"].execute(
        "UPDATE plan_finalization_fence_v1 SET proposal_sha256 = 'oops' "
        "WHERE installation_id = ?",
        (INSTALL,),
    )
    with pytest.raises(PlanFinalizationFenceError, match="corrupt"):
        scene["fence"].observe(INSTALL, service_context=ACTOR)


def test_connection_does_not_accept_active_transaction(scene: dict[str, Any]) -> None:
    scene["db"].execute("BEGIN IMMEDIATE")
    with pytest.raises(PlanFinalizationFenceError, match="autocommit"):
        ProtectedPlanFinalizationFence(scene["db"], authorize=scene["authorize"])
    scene["db"].execute("ROLLBACK")
