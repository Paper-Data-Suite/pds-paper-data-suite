"""Slice 79: service publication preclaim, never receipt publication.

The SQLite DB, witness receipts and roles are synthetic test doubles. In
production service custody must be established independently of local Suite.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import fields, replace
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
    ProtectedFinalizationReservation,
    ProtectedPlanFinalizationFence,
)
from paper_data_suite.evergreen_plan_finalization_preflight import (
    PlanFinalizationPreflight,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    PlanPublicationPreclaimError,
    ProtectedPlanPublicationPreclaimLedger,
    ProtectedPublicationPreclaim,
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
        ledger=ProtectedPlanPublicationPreclaimLedger(fence),
        db=db,
        db_file=db_file,
        authorize=authorize,
        read=read,
        calls=calls,
        reader_calls=reader_calls,
        local=local,
    )


def reserve(scene: dict[str, Any]) -> ProtectedFinalizationReservation:
    return scene["fence"].reserve(
        scene["raw"],
        scene["preflight"],
        service_context=ACTOR,
        independently_read_evidence=scene["read"],
    )


def preclaim(scene: dict[str, Any], **changes: Any) -> ProtectedPublicationPreclaim:
    args: dict[str, Any] = {
        "request_bytes": scene["raw"],
        "reservation": scene["reservation"],
        "service_context": ACTOR,
        "independently_read_evidence": scene["read"],
    }
    return scene["ledger"].preclaim_once(**(args | changes))


@pytest.fixture
def ready(scene: dict[str, Any]) -> dict[str, Any]:
    scene["reservation"] = reserve(scene)
    return scene


def test_preclaim_is_durable_but_never_receipt_write(ready: dict[str, Any]) -> None:
    local = {p.name: p.read_bytes() for p in ready["local"].iterdir()}
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) is None
    marker = preclaim(ready)
    assert marker.status == "PUBLICATION_PRECLAIMED_NO_RECEIPT_WRITE_DISPATCHED"
    assert marker.authority.startswith("NO_RETRY_RECEIPT_WRITE_CAPSULE_CLEAR")
    assert marker.request_sha256 == ready["preflight"].request_sha256
    assert marker.finalization_reservation_sha256 != marker.request_sha256
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) == marker
    assert {p.name: p.read_bytes() for p in ready["local"].iterdir()} == local
    for method in (
        "publish",
        "commit_receipt",
        "clear",
        "activate",
        "rollback",
        "launch",
    ):
        assert not hasattr(ready["ledger"], method)


def test_preclaim_cannot_repeat_identical_or_modified_request(
    ready: dict[str, Any],
) -> None:
    first = preclaim(ready)
    with pytest.raises(PlanPublicationPreclaimError, match="already preclaimed"):
        preclaim(ready)
    with pytest.raises(PlanPublicationPreclaimError):
        preclaim(ready, request_bytes=ready["raw"] + b" ")
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) == first


def test_preclaim_survives_closed_db_and_reopened_connection(
    ready: dict[str, Any],
) -> None:
    marker = preclaim(ready)
    ready["db"].close()
    reopened = sqlite3.connect(ready["db_file"], isolation_level=None)
    try:
        fence = ProtectedPlanFinalizationFence(reopened, authorize=ready["authorize"])
        ledger = ProtectedPlanPublicationPreclaimLedger(fence)
        assert ledger.observe(INSTALL, service_context=ACTOR) == marker
        with pytest.raises(PlanPublicationPreclaimError, match="already preclaimed"):
            ledger.preclaim_once(
                ready["raw"],
                ready["reservation"],
                service_context=ACTOR,
                independently_read_evidence=ready["read"],
            )
    finally:
        reopened.close()


def test_preclaim_fails_if_protected_reservation_missing(scene: dict[str, Any]) -> None:
    fake = ProtectedFinalizationReservation(
        INSTALL,
        NEXT,
        scene["preflight"].request_sha256,
        sha(scene["request"].successor_receipt_bytes),
        2,
        2,
        "5" * 64,
        "6" * 64,
        "7" * 64,
        "8" * 64,
        "9" * 64,
        "d" * 64,
    )
    with pytest.raises(PlanPublicationPreclaimError, match="absent"):
        scene["ledger"].preclaim_once(
            scene["raw"],
            fake,
            service_context=ACTOR,
            independently_read_evidence=scene["read"],
        )
    assert scene["ledger"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "b" * 32),
        ("transaction_id", "b" * 32),
        ("request_sha256", "0" * 64),
        ("successor_sha256", "0" * 64),
        ("successor_generation", 3),
        ("witness_revision", 3),
        ("proposal_sha256", "0" * 64),
        ("selection_sha256", "0" * 64),
        ("recovery_capsule_sha256", "0" * 64),
        ("journal_sha256", "0" * 64),
        ("service_envelope_sha256", "0" * 64),
        ("independent_evidence_sha256", "0" * 64),
        ("status", "ACTIVE"),
        ("authority", "MAY_LAUNCH"),
        ("witness_revision", True),
    ],
)
def test_mutated_reservation_refused(
    ready: dict[str, Any], field: str, value: object
) -> None:
    forged = replace(ready["reservation"], **{field: value})
    with pytest.raises(PlanPublicationPreclaimError):
        preclaim(ready, reservation=forged)
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "b" * 32),
        ("transaction_id", "b" * 32),
        ("request_sha256", "0" * 64),
        ("successor_sha256", "0" * 64),
        ("successor_generation", 10),
        ("witness_revision", 9),
        ("proposal_sha256", "0" * 64),
        ("selection_sha256", "0" * 64),
        ("recovery_capsule_sha256", "0" * 64),
        ("journal_sha256", "0" * 64),
        ("service_envelope_sha256", "0" * 64),
        ("independent_evidence_sha256", "0" * 64),
        ("all_writers_stopped", False),
        ("independently_reaudited_bytes", False),
        ("operator_consent_confirmed", False),
        ("all_writers_stopped", 1),
    ],
)
def test_changed_independent_evidence_refused(
    ready: dict[str, Any], field: str, value: object
) -> None:
    forged = replace(ready["evidence"], **{field: value})
    with pytest.raises(PlanPublicationPreclaimError, match="protected witness"):
        preclaim(ready, independently_read_evidence=lambda req, ctx: forged)
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) is None


@pytest.mark.parametrize("actor", ["teacher", None, True, "other-service"])
def test_unprivileged_actor_cannot_observe_or_preclaim(
    ready: dict[str, Any], actor: object
) -> None:
    with pytest.raises(PlanPublicationPreclaimError, match="authorization"):
        preclaim(ready, service_context=actor)
    with pytest.raises(PlanPublicationPreclaimError, match="authorization"):
        ready["ledger"].observe(INSTALL, service_context=actor)
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_missing_or_throwing_reader_refuses_without_write(
    ready: dict[str, Any],
) -> None:
    with pytest.raises(PlanPublicationPreclaimError, match="current evidence missing"):
        preclaim(ready, independently_read_evidence=None)
    with pytest.raises(PlanPublicationPreclaimError, match="revalidation failed"):
        preclaim(ready, independently_read_evidence=lambda req, ctx: 1 / 0)
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_bad_request_is_refused_before_reader_or_sql(ready: dict[str, Any]) -> None:
    count = len(ready["reader_calls"])
    with pytest.raises(PlanPublicationPreclaimError):
        preclaim(ready, request_bytes=ready["raw"] + b" ")
    with pytest.raises(PlanPublicationPreclaimError):
        preclaim(ready, request_bytes=b"not a canonical witness request")
    assert len(ready["reader_calls"]) == count
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) is None


def test_corrupt_written_preclaim_is_detected_and_never_rearmed(
    ready: dict[str, Any],
) -> None:
    preclaim(ready)
    with pytest.raises(sqlite3.IntegrityError):
        ready["db"].execute(
            "UPDATE plan_publication_preclaim_v1 "
            "SET status='BAD' WHERE installation_id=?",
            (INSTALL,),
        )
    ready["db"].execute(
        "UPDATE plan_publication_preclaim_v1 "
        "SET request_sha256='bad' WHERE installation_id=?",
        (INSTALL,),
    )
    with pytest.raises(PlanPublicationPreclaimError, match="corrupt"):
        ready["ledger"].observe(INSTALL, service_context=ACTOR)
    with pytest.raises(PlanPublicationPreclaimError, match="already preclaimed"):
        preclaim(ready)


def test_preclaim_ledger_rejects_active_transaction(ready: dict[str, Any]) -> None:
    ready["db"].execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(PlanPublicationPreclaimError, match="service fence"):
            ProtectedPlanPublicationPreclaimLedger(ready["fence"])
    finally:
        ready["db"].execute("ROLLBACK")


def test_ledger_is_plain_immutable_one_row_per_install(ready: dict[str, Any]) -> None:
    marker = preclaim(ready)
    assert len(fields(marker)) == 10
    with pytest.raises(sqlite3.IntegrityError):
        ready["db"].execute(
            "INSERT INTO plan_publication_preclaim_v1 SELECT * "
            "FROM plan_publication_preclaim_v1 WHERE installation_id = ?",
            (INSTALL,),
        )
    assert ready["ledger"].observe(INSTALL, service_context=ACTOR) == marker
