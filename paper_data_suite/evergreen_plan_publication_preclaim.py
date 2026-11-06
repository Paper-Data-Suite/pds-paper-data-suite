"""Issue #49 Slice 79: service-owned, durable one-shot publication preclaim.

This boundary marks a possible *future* protected active-receipt publication.
It deliberately performs NO receipt write, capsule deletion, journal update,
slot switch, CAS dispatch or launch. A preclaim must not be automatically
retried or cleared; crash recovery is a separate independently supervised task.

The code cannot establish physical isolation of a service, its key material,
its database, local filesystem or actual operator consent. Those properties
must be provided by the production deployer, not by caller-built callbacks.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from typing import Final

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationEvidence,
    IndependentFinalizationReader,
    PlanFinalizationFenceError,
    ProtectedFinalizationReservation,
    ProtectedPlanFinalizationFence,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    parse_witness_commit_request,
    serialize_witness_commit_request,
)

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_STATUS: Final = "PUBLICATION_PRECLAIMED_NO_RECEIPT_WRITE_DISPATCHED"
_AUTHORITY: Final = (
    "NO_RETRY_RECEIPT_WRITE_CAPSULE_CLEAR_LAUNCH_ROLLBACK_OR_CAS_AUTHORITY"
)
_RESERVED: Final = "PREPARED_NO_ACTIVE_RECEIPT_WRITE"
_RESERVED_AUTH: Final = (
    "NO_RECEIPT_WRITE_CAPSULE_CLEAR_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY"
)
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_publication_preclaim_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    finalization_reservation_sha256 TEXT NOT NULL,
    independent_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'PUBLICATION_PRECLAIMED_NO_RECEIPT_WRITE_DISPATCHED'
    )
)
"""


class PlanPublicationPreclaimError(ValueError):
    """Protected preclaim is unavailable, inconsistent or already consumed."""


@dataclass(frozen=True, slots=True)
class ProtectedPublicationPreclaim:
    """A durable *possibility* marker, never an active-receipt authorization."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    finalization_reservation_sha256: str
    independent_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reservation_hash(reservation: ProtectedFinalizationReservation) -> str:
    """Canonical binding to every immutable Slice-78 field (no local grant)."""
    return _sha(
        json.dumps(
            {
                field.name: getattr(reservation, field.name)
                for field in fields(reservation)
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    )


def _request_and_reservation(
    request_bytes: bytes,
    reservation: ProtectedFinalizationReservation,
) -> WitnessCommitRequest:
    if (
        type(request_bytes) is not bytes
        or not 1 <= len(request_bytes) <= 48 * 1024
        or not isinstance(reservation, ProtectedFinalizationReservation)
        or any(
            type(getattr(reservation, field.name))
            is not (
                int
                if field.name in ("successor_generation", "witness_revision")
                else str
            )
            for field in fields(ProtectedFinalizationReservation)
        )
        or reservation.status != _RESERVED
        or reservation.authority != _RESERVED_AUTH
    ):
        raise PlanPublicationPreclaimError("invalid non-authorizing reservation")
    if (
        _TX.fullmatch(reservation.installation_id) is None
        or _TX.fullmatch(reservation.transaction_id) is None
        or any(
            _SHA.fullmatch(getattr(reservation, name)) is None
            for name in (
                "request_sha256",
                "successor_sha256",
                "proposal_sha256",
                "selection_sha256",
                "recovery_capsule_sha256",
                "journal_sha256",
                "service_envelope_sha256",
                "independent_evidence_sha256",
            )
        )
    ):
        raise PlanPublicationPreclaimError("reservation identities are malformed")
    try:
        request = parse_witness_commit_request(request_bytes)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
        original = serialize_witness_commit_request(request)
    except (WitnessCommitProtocolError, ActiveReceiptError) as error:
        raise PlanPublicationPreclaimError(
            "canonical witness request refused"
        ) from error
    if (
        original != request_bytes
        or reservation.installation_id != request.installation_id
        or reservation.transaction_id != successor.transaction_id
        or reservation.request_sha256 != _sha(original)
        or reservation.successor_sha256 != request.successor_sha256
        or reservation.successor_generation != successor.generation
        or reservation.witness_revision != request.expected_witness_revision + 1
    ):
        raise PlanPublicationPreclaimError("reservation is not this signed successor")
    return request


def _fresh_basis_matches(
    basis: object, reservation: ProtectedFinalizationReservation
) -> bool:
    if not isinstance(basis, IndependentFinalizationEvidence):
        return False
    columns = (
        "installation_id",
        "transaction_id",
        "request_sha256",
        "successor_sha256",
        "witness_revision",
        "proposal_sha256",
        "selection_sha256",
        "recovery_capsule_sha256",
        "journal_sha256",
        "service_envelope_sha256",
        "independent_evidence_sha256",
    )
    if any(
        type(getattr(basis, name)) is not type(getattr(reservation, name))
        or getattr(basis, name) != getattr(reservation, name)
        for name in columns
    ):
        return False
    return (
        type(basis.successor_generation) is int
        and basis.successor_generation == reservation.successor_generation
        and basis.all_writers_stopped is True
        and basis.independently_reaudited_bytes is True
        and basis.operator_consent_confirmed is True
    )


class ProtectedPlanPublicationPreclaimLedger:
    """Append-only service boundary on the EXACT Slice-78 SQLite connection.

    Every real publication writer must check this durable marker, but the
    marker itself cannot authorize a write. If a preclaim exists, independent
    reconciliation is mandatory; no retry/rearm/clear operation is exposed.
    """

    def __init__(self, fence: ProtectedPlanFinalizationFence) -> None:
        if (
            not isinstance(fence, ProtectedPlanFinalizationFence)
            or not isinstance(fence._db, sqlite3.Connection)
            or fence._db.in_transaction
        ):
            raise PlanPublicationPreclaimError("independent service fence required")
        self._fence = fence
        self._db = fence._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise PlanPublicationPreclaimError("preclaim DB unavailable") from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedPublicationPreclaim | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise PlanPublicationPreclaimError("invalid installation identity")
        self._check_authority(
            installation_id, "observe_publication_preclaim", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_publication_preclaim_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise PlanPublicationPreclaimError("preclaim state unavailable") from error
        if row is None:
            return None
        try:
            preclaim = ProtectedPublicationPreclaim(*row)
        except (TypeError, ValueError) as error:
            raise PlanPublicationPreclaimError("preclaim row malformed") from error
        if (
            preclaim.installation_id != installation_id
            or type(preclaim.transaction_id) is not str
            or _TX.fullmatch(preclaim.transaction_id) is None
            or type(preclaim.successor_generation) is not int
            or not 1 <= preclaim.successor_generation <= 2**53 - 1
            or type(preclaim.witness_revision) is not int
            or not 1 <= preclaim.witness_revision <= 2**53 - 1
            or any(
                type(getattr(preclaim, name)) is not str
                or _SHA.fullmatch(getattr(preclaim, name)) is None
                for name in (
                    "request_sha256",
                    "successor_sha256",
                    "finalization_reservation_sha256",
                    "independent_evidence_sha256",
                )
            )
            or preclaim.status != _STATUS
            or preclaim.authority != _AUTHORITY
        ):
            raise PlanPublicationPreclaimError("protected preclaim is corrupt")
        return preclaim

    def _check_authority(
        self, installation_id: str, operation: str, service_context: object
    ) -> None:
        try:
            self._fence._check_authority(installation_id, operation, service_context)
        except PlanFinalizationFenceError as error:
            raise PlanPublicationPreclaimError(
                "independent service preclaim authorization refused"
            ) from error

    def preclaim_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
    ) -> ProtectedPublicationPreclaim:
        """Durably mark the transition point; NO active-receipt writer is called.

        The service must take separately protected OS/process-level locks and
        revalidate installed bytes and consent outside Python in production.
        Losing an acknowledgment after COMMIT must NOT trigger retry.
        """
        request = _request_and_reservation(request_bytes, reservation)
        self._check_authority(
            request.installation_id, "preclaim_publication_once", service_context
        )
        if not callable(independently_read_evidence):
            raise PlanPublicationPreclaimError("independent current evidence missing")
        try:
            basis = independently_read_evidence(request, service_context)
        except Exception as error:
            raise PlanPublicationPreclaimError(
                "independent pre-publication revalidation failed"
            ) from error
        if not _fresh_basis_matches(basis, reservation):
            raise PlanPublicationPreclaimError(
                "protected witness, physical bytes or operator approval changed"
            )
        preclaim = ProtectedPublicationPreclaim(
            reservation.installation_id,
            reservation.transaction_id,
            reservation.request_sha256,
            reservation.successor_sha256,
            reservation.successor_generation,
            reservation.witness_revision,
            _reservation_hash(reservation),
            reservation.independent_evidence_sha256,
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                # The actual protected, authoritative row is mandatory. A
                # locally forged dataclass is NOT the reservation.
                persisted = self._fence.observe(
                    request.installation_id, service_context=service_context
                )
                if persisted != reservation or type(persisted) is not type(reservation):
                    raise PlanPublicationPreclaimError(
                        "durable finalization reservation has changed or is absent"
                    )
                old = self._db.execute(
                    "SELECT installation_id FROM plan_publication_preclaim_v1 "
                    "WHERE installation_id = ?",
                    (request.installation_id,),
                ).fetchone()
                if old is not None:
                    raise PlanPublicationPreclaimError(
                        "publication already preclaimed; no replay or automatic retry"
                    )
                self._db.execute(
                    "INSERT INTO plan_publication_preclaim_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        preclaim.installation_id,
                        preclaim.transaction_id,
                        preclaim.request_sha256,
                        preclaim.successor_sha256,
                        preclaim.successor_generation,
                        preclaim.witness_revision,
                        preclaim.finalization_reservation_sha256,
                        preclaim.independent_evidence_sha256,
                        preclaim.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except (PlanFinalizationFenceError, sqlite3.Error) as error:
            raise PlanPublicationPreclaimError(
                "preclaim may be indeterminate; read-only reconciliation mandatory"
            ) from error
        return preclaim


__all__ = (
    "PlanPublicationPreclaimError",
    "ProtectedPlanPublicationPreclaimLedger",
    "ProtectedPublicationPreclaim",
)
