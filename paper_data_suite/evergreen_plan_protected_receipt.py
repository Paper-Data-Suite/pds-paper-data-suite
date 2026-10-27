"""Issue #49 Slice 80: one-shot protected-service receipt recording.

Write the canonical signed successor receipt into the SAME protected SQLite
connection as the Slice-78 reservation and Slice-79 preclaim. A single DB
transaction provides an atomic protected record, not an atomic update of any
local file. It cannot activate a teacher-local installed composition, publish
its local active receipt, clear the recovery capsule, switch slots or launch.

Every real deployment must provide separately administered service identity,
SQLite custody, writer shutdown, physical verification and consent. Callbacks
or in-memory objects passed by a classroom process are not proof of that trust
boundary. After uncertainty, observe; NEVER automatically retry publication.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationReader,
    PlanFinalizationFenceError,
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    PlanPublicationPreclaimError,
    ProtectedPlanPublicationPreclaimLedger,
    ProtectedPublicationPreclaim,
    _fresh_basis_matches,
    _request_and_reservation,
    _reservation_hash,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    inspect_uncertain_witness_commit,
)

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_STATUS: Final = "PROTECTED_RECEIPT_RECORDED_LOCAL_RECOVERY_PENDING"
_AUTHORITY: Final = (
    "NO_LOCAL_RECEIPT_PUBLICATION_CAPSULE_CLEAR_LAUNCH_ROLLBACK_SWITCH_OR_CAS"
)
_PRECLAIM_STATUS: Final = "PUBLICATION_PRECLAIMED_NO_RECEIPT_WRITE_DISPATCHED"
_PRECLAIM_AUTH: Final = (
    "NO_RETRY_RECEIPT_WRITE_CAPSULE_CLEAR_LAUNCH_ROLLBACK_OR_CAS_AUTHORITY"
)
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_protected_receipt_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_receipt_bytes BLOB NOT NULL,
    successor_generation INTEGER NOT NULL,
    witnessed_revision INTEGER NOT NULL,
    finalization_reservation_sha256 TEXT NOT NULL,
    publication_preclaim_sha256 TEXT NOT NULL,
    independent_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'PROTECTED_RECEIPT_RECORDED_LOCAL_RECOVERY_PENDING'
    )
)
"""


class ProtectedPlanReceiptError(ValueError):
    """Refuse an unauthenticated, changed, duplicate or uncertain receipt."""


@dataclass(frozen=True, slots=True)
class ProtectedServiceReceiptRecord:
    """Diagnostic signed-successor record, never local install/launch authority."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witnessed_revision: int
    finalization_reservation_sha256: str
    publication_preclaim_sha256: str
    independent_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _preclaim_hash(value: ProtectedPublicationPreclaim) -> str:
    """Bind every Slice-79 durable field including non-authorizing markers."""
    return _sha(
        json.dumps(
            {field.name: getattr(value, field.name) for field in fields(value)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_preclaim(
    reservation: ProtectedFinalizationReservation,
    preclaim: ProtectedPublicationPreclaim,
) -> None:
    if (
        not isinstance(preclaim, ProtectedPublicationPreclaim)
        or any(
            type(getattr(preclaim, field.name))
            is not (
                int
                if field.name in ("successor_generation", "witness_revision")
                else str
            )
            for field in fields(ProtectedPublicationPreclaim)
        )
        or preclaim.status != _PRECLAIM_STATUS
        or preclaim.authority != _PRECLAIM_AUTH
        or preclaim.installation_id != reservation.installation_id
        or preclaim.transaction_id != reservation.transaction_id
        or preclaim.request_sha256 != reservation.request_sha256
        or preclaim.successor_sha256 != reservation.successor_sha256
        or preclaim.successor_generation != reservation.successor_generation
        or preclaim.witness_revision != reservation.witness_revision
        or preclaim.finalization_reservation_sha256 != _reservation_hash(reservation)
        or preclaim.independent_evidence_sha256
        != reservation.independent_evidence_sha256
    ):
        raise ProtectedPlanReceiptError(
            "untrusted preclaim does not match canonical reserved successor"
        )


class ProtectedPlanReceiptWriter:
    """Append-once service receipt storage sharing the exact 78/79 DB.

    This deliberately has NO local active-receipt path or capsule mutation.
    Production protection is an external OS/service responsibility.
    """

    def __init__(self, preclaims: ProtectedPlanPublicationPreclaimLedger) -> None:
        if (
            not isinstance(preclaims, ProtectedPlanPublicationPreclaimLedger)
            or not isinstance(preclaims._db, sqlite3.Connection)
            or preclaims._db is not preclaims._fence._db
            or preclaims._db.in_transaction
        ):
            raise ProtectedPlanReceiptError(
                "exact protected service connection required"
            )
        self._preclaims = preclaims
        self._db = preclaims._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise ProtectedPlanReceiptError(
                "protected receipt table unavailable"
            ) from error

    def _check(
        self, installation_id: str, operation: str, service_context: object
    ) -> None:
        try:
            self._preclaims._check_authority(
                installation_id, operation, service_context
            )
        except PlanPublicationPreclaimError as error:
            raise ProtectedPlanReceiptError(
                "independent service receipt authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedServiceReceiptRecord | None:
        """Read-only independently authorized integrity inspection."""
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise ProtectedPlanReceiptError("invalid installation identity")
        self._check(installation_id, "observe_protected_receipt", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_protected_receipt_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise ProtectedPlanReceiptError("protected receipt unreadable") from error
        if row is None:
            return None
        try:
            (
                install,
                tx,
                request_sha,
                receipt_sha,
                receipt_bytes,
                generation,
                revision,
                reservation_sha,
                preclaim_sha,
                evidence_sha,
                status,
            ) = row
            receipt = parse_untrusted_active_receipt(receipt_bytes)
            result = ProtectedServiceReceiptRecord(
                install,
                tx,
                request_sha,
                receipt_sha,
                generation,
                revision,
                reservation_sha,
                preclaim_sha,
                evidence_sha,
            )
        except (TypeError, ValueError, ActiveReceiptError) as error:
            raise ProtectedPlanReceiptError("malformed protected receipt") from error
        if (
            type(install) is not str
            or install != installation_id
            or type(tx) is not str
            or _TX.fullmatch(tx) is None
            or type(receipt_bytes) is not bytes
            or type(generation) is not int
            or not 1 <= generation <= 2**53 - 1
            or type(revision) is not int
            or not 1 <= revision <= 2**53 - 1
            or any(
                type(value) is not str or _SHA.fullmatch(value) is None
                for value in (
                    request_sha,
                    receipt_sha,
                    reservation_sha,
                    preclaim_sha,
                    evidence_sha,
                )
            )
            or _sha(receipt_bytes) != receipt_sha
            or receipt.transaction_id != tx
            or receipt.generation != generation
            or status != _STATUS
            or result.status != _STATUS
            or result.authority != _AUTHORITY
        ):
            raise ProtectedPlanReceiptError("protected receipt record is corrupt")
        return result

    def record_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedServiceReceiptRecord:
        """Atomically record a verified successor *only in protected SQLite*.

        The caller must supply independently operated witness and verifier
        facilities. Every error or lost COMMIT ACK forbids automatic retry.
        Local active-receipt publication is NOT performed.
        """
        try:
            request = _request_and_reservation(request_bytes, reservation)
        except PlanPublicationPreclaimError as error:
            raise ProtectedPlanReceiptError("noncanonical reserved request") from error
        _exact_preclaim(reservation, preclaim)
        if (
            not callable(independently_read_evidence)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise ProtectedPlanReceiptError("protected service witness inputs missing")
        self._check(
            request.installation_id, "record_protected_receipt_once", service_context
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                persisted_reservation = self._preclaims._fence.observe(
                    request.installation_id, service_context=service_context
                )
                persisted_preclaim = self._preclaims.observe(
                    request.installation_id, service_context=service_context
                )
                if (
                    persisted_reservation != reservation
                    or persisted_preclaim != preclaim
                    or type(persisted_reservation) is not type(reservation)
                    or type(persisted_preclaim) is not type(preclaim)
                ):
                    raise ProtectedPlanReceiptError(
                        "missing or changed independently protected preimages"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_protected_receipt_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise ProtectedPlanReceiptError(
                        "protected receipt already recorded; no replay or retry"
                    )
                try:
                    basis = independently_read_evidence(request, service_context)
                except Exception as error:
                    raise ProtectedPlanReceiptError(
                        "current independent physical evidence unavailable"
                    ) from error
                if not _fresh_basis_matches(basis, reservation):
                    raise ProtectedPlanReceiptError(
                        "stopped writers, protected installed bytes or consent changed"
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
                    raise ProtectedPlanReceiptError(
                        "independently signed successor head unavailable"
                    ) from error
                if (
                    signed.status
                    != "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
                    or signed.installation_id != request.installation_id
                    or type(signed.witness_revision) is not int
                    or signed.witness_revision != reservation.witness_revision
                    or type(signed.generation) is not int
                    or signed.generation != reservation.successor_generation
                    or signed.receipt_sha256 != request.successor_sha256
                ):
                    raise ProtectedPlanReceiptError(
                        "signed witness successor differs; retain recovery"
                    )
                record = ProtectedServiceReceiptRecord(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    signed.witness_revision,
                    _reservation_hash(reservation),
                    _preclaim_hash(preclaim),
                    reservation.independent_evidence_sha256,
                )
                self._db.execute(
                    "INSERT INTO plan_protected_receipt_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.installation_id,
                        record.transaction_id,
                        record.request_sha256,
                        record.successor_sha256,
                        request.successor_receipt_bytes,
                        record.successor_generation,
                        record.witnessed_revision,
                        record.finalization_reservation_sha256,
                        record.publication_preclaim_sha256,
                        record.independent_evidence_sha256,
                        record.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except ProtectedPlanReceiptError:
            raise
        except (
            sqlite3.Error,
            PlanFinalizationFenceError,
            PlanPublicationPreclaimError,
        ) as error:
            raise ProtectedPlanReceiptError(
                "protected recording may be uncertain; read-only reconcile only"
            ) from error
        return record


__all__ = (
    "ProtectedPlanReceiptError",
    "ProtectedPlanReceiptWriter",
    "ProtectedServiceReceiptRecord",
)
