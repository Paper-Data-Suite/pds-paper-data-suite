"""Issue #49 Slice 81: service-owned one-shot local receipt deployment *intent*.

After protected Slice-80 successor recording, reserve exact local predecessor,
receipt target identity, and retained recovery evidence. The reservation is a
WRITE-AHEAD marker, not authorization to touch a teacher-local active receipt.
No local file, pointer, capsule, journal, witness CAS or launcher is mutated.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final, Protocol

from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationReader,
    PlanFinalizationFenceError,
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedPlanReceiptError,
    ProtectedPlanReceiptWriter,
    ProtectedServiceReceiptRecord,
    _preclaim_hash,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    PlanPublicationPreclaimError,
    ProtectedPublicationPreclaim,
    _fresh_basis_matches,
    _request_and_reservation,
    _reservation_hash,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    inspect_uncertain_witness_commit,
)

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_STATUS: Final = "LOCAL_RECEIPT_DEPLOYMENT_PREPARED_NO_FILE_WRITE"
_AUTHORITY: Final = "NO_LOCAL_RECEIPT_WRITE_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_RECORDED: Final = "PROTECTED_RECEIPT_RECORDED_LOCAL_RECOVERY_PENDING"
_RECORDED_AUTH: Final = (
    "NO_LOCAL_RECEIPT_PUBLICATION_CAPSULE_CLEAR_LAUNCH_ROLLBACK_SWITCH_OR_CAS"
)
_SIGNED_NEXT: Final = "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_local_deployment_intent_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    protected_receipt_record_sha256 TEXT NOT NULL,
    predecessor_receipt_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    proposal_sha256 TEXT NOT NULL,
    selection_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    journal_sha256 TEXT NOT NULL,
    independent_evidence_sha256 TEXT NOT NULL,
    local_snapshot_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LOCAL_RECEIPT_DEPLOYMENT_PREPARED_NO_FILE_WRITE'
    )
)
"""


class LocalDeploymentIntentError(ValueError):
    """Protected deployment prerequisites are unverified or state is uncertain."""


@dataclass(frozen=True, slots=True)
class IndependentLocalDeploymentInspection:
    """Service-owned physical observation, never proof merely from its shape.

    Production MUST establish actor/OS separation, exclusive writer fencing,
    original-receipt integrity, ordinary-file safety, and retained recovery
    using a genuinely independent reader with protected target configuration.
    """

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    predecessor_receipt_sha256: str
    current_active_receipt_sha256: str
    target_identity_sha256: str
    proposal_sha256: str
    selection_sha256: str
    recovery_capsule_sha256: str
    journal_sha256: str
    local_snapshot_sha256: str
    prior_receipt_is_protected_ordinary_file: bool
    capsule_is_protected_ordinary_file: bool
    candidate_physical_bytes_rechecked: bool
    installation_writers_exclusively_fenced: bool


class IndependentLocalDeploymentReader(Protocol):
    """Service-provisioned physical reader, not a teacher-supplied callback."""

    def __call__(
        self, request: WitnessCommitRequest, service_context: object, /
    ) -> IndependentLocalDeploymentInspection: ...


@dataclass(frozen=True, slots=True)
class ProtectedLocalDeploymentIntent:
    """Immutable service write-ahead description; NO file mutation authority."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    protected_receipt_record_sha256: str
    predecessor_receipt_sha256: str
    target_identity_sha256: str
    proposal_sha256: str
    selection_sha256: str
    recovery_capsule_sha256: str
    journal_sha256: str
    independent_evidence_sha256: str
    local_snapshot_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record_hash(record: ProtectedServiceReceiptRecord) -> str:
    """Canonical binding to ALL Slice-80 metadata (not a bearer credential)."""
    return _sha(
        json.dumps(
            {field.name: getattr(record, field.name) for field in fields(record)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _valid_protected_record(
    record: ProtectedServiceReceiptRecord,
    reservation: ProtectedFinalizationReservation,
    preclaim: ProtectedPublicationPreclaim,
) -> bool:
    if not isinstance(record, ProtectedServiceReceiptRecord):
        return False
    if any(
        type(getattr(record, field.name))
        is not (
            int if field.name in ("successor_generation", "witnessed_revision") else str
        )
        for field in fields(ProtectedServiceReceiptRecord)
    ):
        return False
    return (
        record.status == _RECORDED
        and record.authority == _RECORDED_AUTH
        and record.installation_id == reservation.installation_id
        and record.transaction_id == reservation.transaction_id
        and record.request_sha256 == reservation.request_sha256
        and record.successor_sha256 == reservation.successor_sha256
        and record.successor_generation == reservation.successor_generation
        and record.witnessed_revision == reservation.witness_revision
        and record.finalization_reservation_sha256 == _reservation_hash(reservation)
        and record.publication_preclaim_sha256 == _preclaim_hash(preclaim)
        and record.independent_evidence_sha256
        == reservation.independent_evidence_sha256
    )


def _local_matches(
    inspected: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    *,
    pinned_target_identity_sha256: str,
) -> bool:
    if not isinstance(inspected, IndependentLocalDeploymentInspection):
        return False
    for field in fields(IndependentLocalDeploymentInspection):
        value = getattr(inspected, field.name)
        expected_type = (
            bool
            if field.name
            in (
                "prior_receipt_is_protected_ordinary_file",
                "capsule_is_protected_ordinary_file",
                "candidate_physical_bytes_rechecked",
                "installation_writers_exclusively_fenced",
            )
            else str
        )
        if type(value) is not expected_type:
            return False
    return (
        inspected.installation_id == request.installation_id
        and inspected.transaction_id == reservation.transaction_id
        and inspected.request_sha256 == reservation.request_sha256
        and inspected.successor_sha256 == request.successor_sha256
        and inspected.predecessor_receipt_sha256 == request.predecessor_sha256
        and inspected.current_active_receipt_sha256 == request.predecessor_sha256
        and inspected.target_identity_sha256 == pinned_target_identity_sha256
        and inspected.proposal_sha256 == reservation.proposal_sha256
        and inspected.selection_sha256 == reservation.selection_sha256
        and inspected.recovery_capsule_sha256 == reservation.recovery_capsule_sha256
        and inspected.journal_sha256 == reservation.journal_sha256
        and _SHA.fullmatch(inspected.local_snapshot_sha256) is not None
        and inspected.prior_receipt_is_protected_ordinary_file is True
        and inspected.capsule_is_protected_ordinary_file is True
        and inspected.candidate_physical_bytes_rechecked is True
        and inspected.installation_writers_exclusively_fenced is True
    )


class ProtectedLocalReceiptDeploymentPlanner:
    """Same independently administered SQLite as Slices 78–80; never a writer."""

    def __init__(self, writer: ProtectedPlanReceiptWriter) -> None:
        if (
            not isinstance(writer, ProtectedPlanReceiptWriter)
            or not isinstance(writer._db, sqlite3.Connection)
            or writer._db is not writer._preclaims._db
            or writer._db is not writer._preclaims._fence._db
            or writer._db.in_transaction
        ):
            raise LocalDeploymentIntentError(
                "exact protected finalization/receipt connection required"
            )
        self._writer = writer
        self._db = writer._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LocalDeploymentIntentError(
                "deployment intent table unavailable"
            ) from error

    def _authorize(
        self, installation_id: str, operation: str, service_context: object
    ) -> None:
        try:
            self._writer._check(installation_id, operation, service_context)
        except ProtectedPlanReceiptError as error:
            raise LocalDeploymentIntentError(
                "independent deployment authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLocalDeploymentIntent | None:
        """Read an existing deployment intent; no retry or clearance rights."""
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LocalDeploymentIntentError("invalid installation identity")
        self._authorize(
            installation_id, "observe_local_deployment_intent", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_local_deployment_intent_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LocalDeploymentIntentError(
                "durable deployment intent unavailable"
            ) from error
        if row is None:
            return None
        try:
            intent = ProtectedLocalDeploymentIntent(*row)
        except (TypeError, ValueError) as error:
            raise LocalDeploymentIntentError(
                "invalid durable deployment row"
            ) from error
        if (
            intent.installation_id != installation_id
            or type(intent.transaction_id) is not str
            or _TX.fullmatch(intent.transaction_id) is None
            or type(intent.successor_generation) is not int
            or not 1 <= intent.successor_generation <= 2**53 - 1
            or type(intent.witness_revision) is not int
            or not 1 <= intent.witness_revision <= 2**53 - 1
            or any(
                type(getattr(intent, field.name)) is not str
                or _SHA.fullmatch(getattr(intent, field.name)) is None
                for field in fields(ProtectedLocalDeploymentIntent)
                if field.name.endswith("_sha256")
            )
            or intent.status != _STATUS
            or intent.authority != _AUTHORITY
        ):
            raise LocalDeploymentIntentError("protected deployment intent is corrupt")
        return intent

    def prepare_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local: IndependentLocalDeploymentReader,
        pinned_target_identity_sha256: str,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLocalDeploymentIntent:
        """Record one immutable deployment *intent* only, with NO local writes.

        A trustworthy deployment must protect its configured active-receipt
        target and retain OS-level exclusive writer locks while verifying the
        current predecessor receipt, recovery capsule and installed bytes.
        Dataclass hashes alone do not establish these physical properties.
        """
        try:
            request = _request_and_reservation(request_bytes, reservation)
        except PlanPublicationPreclaimError as error:
            raise LocalDeploymentIntentError(
                "noncanonical successor request"
            ) from error
        if (
            not _valid_protected_record(record, reservation, preclaim)
            or type(pinned_target_identity_sha256) is not str
            or _SHA.fullmatch(pinned_target_identity_sha256) is None
            or not callable(independently_read_evidence)
            or not callable(independently_read_local)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise LocalDeploymentIntentError("protected deployment inputs invalid")
        self._authorize(
            request.installation_id, "prepare_local_deployment_once", service_context
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                # No caller-provided dataclass is permission to mutate a file.
                actual_reservation = self._writer._preclaims._fence.observe(
                    request.installation_id, service_context=service_context
                )
                actual_preclaim = self._writer._preclaims.observe(
                    request.installation_id, service_context=service_context
                )
                actual_record = self._writer.observe(
                    request.installation_id, service_context=service_context
                )
                if (
                    type(actual_reservation) is not type(reservation)
                    or type(actual_preclaim) is not type(preclaim)
                    or type(actual_record) is not type(record)
                    or actual_reservation != reservation
                    or actual_preclaim != preclaim
                    or actual_record != record
                ):
                    raise LocalDeploymentIntentError(
                        "protected reservation/preclaim/receipt records differ"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_local_deployment_intent_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LocalDeploymentIntentError(
                        "deployment already prepared; no replay or automatic retry"
                    )
                try:
                    independent = independently_read_evidence(request, service_context)
                except Exception as error:
                    raise LocalDeploymentIntentError(
                        "service physical evidence unavailable"
                    ) from error
                if not _fresh_basis_matches(independent, reservation):
                    raise LocalDeploymentIntentError(
                        "service physical evidence, stopped writers or consent changed"
                    )
                try:
                    inspected = independently_read_local(request, service_context)
                except Exception as error:
                    raise LocalDeploymentIntentError(
                        "independent local receipt/capsule inspection unavailable"
                    ) from error
                if not _local_matches(
                    inspected,
                    request,
                    reservation,
                    pinned_target_identity_sha256=pinned_target_identity_sha256,
                ):
                    raise LocalDeploymentIntentError(
                        "prior receipt, protected target or recovery capsule changed"
                    )
                try:
                    signed = inspect_uncertain_witness_commit(
                        request,
                        witness_transport=witness_transport,
                        pinned_public_key=pinned_public_key,
                        now=now,
                        minimum_witness_revision=reservation.witness_revision,
                    )
                except WitnessCommitProtocolError as error:
                    raise LocalDeploymentIntentError(
                        "fresh pinned signed successor head unavailable"
                    ) from error
                if (
                    signed.status != _SIGNED_NEXT
                    or signed.installation_id != request.installation_id
                    or type(signed.witness_revision) is not int
                    or signed.witness_revision != reservation.witness_revision
                    or type(signed.generation) is not int
                    or signed.generation != reservation.successor_generation
                    or signed.receipt_sha256 != request.successor_sha256
                ):
                    raise LocalDeploymentIntentError(
                        "signed witness disagrees; retain pending recovery"
                    )
                assert isinstance(inspected, IndependentLocalDeploymentInspection)
                intent = ProtectedLocalDeploymentIntent(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _record_hash(record),
                    request.predecessor_sha256,
                    pinned_target_identity_sha256,
                    reservation.proposal_sha256,
                    reservation.selection_sha256,
                    reservation.recovery_capsule_sha256,
                    reservation.journal_sha256,
                    reservation.independent_evidence_sha256,
                    inspected.local_snapshot_sha256,
                )
                self._db.execute(
                    "INSERT INTO plan_local_deployment_intent_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        intent.installation_id,
                        intent.transaction_id,
                        intent.request_sha256,
                        intent.successor_sha256,
                        intent.successor_generation,
                        intent.witness_revision,
                        intent.protected_receipt_record_sha256,
                        intent.predecessor_receipt_sha256,
                        intent.target_identity_sha256,
                        intent.proposal_sha256,
                        intent.selection_sha256,
                        intent.recovery_capsule_sha256,
                        intent.journal_sha256,
                        intent.independent_evidence_sha256,
                        intent.local_snapshot_sha256,
                        intent.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LocalDeploymentIntentError:
            raise
        except (
            sqlite3.Error,
            PlanFinalizationFenceError,
            PlanPublicationPreclaimError,
            ProtectedPlanReceiptError,
        ) as error:
            raise LocalDeploymentIntentError(
                "deployment preparation possibly uncertain; observe only"
            ) from error
        return intent


__all__ = (
    "IndependentLocalDeploymentInspection",
    "IndependentLocalDeploymentReader",
    "LocalDeploymentIntentError",
    "ProtectedLocalDeploymentIntent",
    "ProtectedLocalReceiptDeploymentPlanner",
)
