"""Issue #49 Slice 78: durable, service-owned *pre-publication* finalization fence.

Reserve a canonical successor and the exact pending-local preimages for an
independently controlled finalizer. An in-memory Slice-77 preflight object is
untrusted. The service must separately authenticate its actor, pinned state,
physical-byte verification and operator consent; its protected SQLite DB must
be inaccessible to the teacher-local process. Reservation is once per install.

There is NO active-receipt write, capsule cleanup, witness CAS, launcher,
selection change or publication capability in this module. Crash/commit
ambiguity requires inspection; automatic retry is deliberately prohibited.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Final, Protocol

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_plan_finalization_preflight import (
    PlanFinalizationPreflight,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    parse_witness_commit_request,
    serialize_witness_commit_request,
)

_HEX: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_STATUS: Final = "PREPARED_NO_ACTIVE_RECEIPT_WRITE"
_AUTHORITY: Final = (
    "NO_RECEIPT_WRITE_CAPSULE_CLEAR_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY"
)
_REVIEW_STATUS: Final = (
    "LOCAL_FINALIZATION_PREFLIGHT_REVIEW_ONLY_RECOVERY_CAPSULE_REQUIRED"
)
_REVIEW_AUTHORITY: Final = (
    "NO_RECEIPT_WRITE_CAPSULE_CLEANUP_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY"
)
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_finalization_fence_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    proposal_sha256 TEXT NOT NULL,
    selection_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    journal_sha256 TEXT NOT NULL,
    service_envelope_sha256 TEXT NOT NULL,
    independent_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'PREPARED_NO_ACTIVE_RECEIPT_WRITE')
)
"""


class PlanFinalizationFenceError(ValueError):
    """A protected finalization reservation/observation was refused."""


@dataclass(frozen=True, slots=True)
class IndependentFinalizationEvidence:
    """Service reader's assertion; fields do NOT prove its provenance.

    Production MUST obtain this from independently administered live state,
    *not* deserialize it from a client request or reuse Slice-77's dataclass.
    """

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    proposal_sha256: str
    selection_sha256: str
    recovery_capsule_sha256: str
    journal_sha256: str
    service_envelope_sha256: str
    independent_evidence_sha256: str
    all_writers_stopped: bool
    independently_reaudited_bytes: bool
    operator_consent_confirmed: bool


class IndependentFinalizationReader(Protocol):
    """Protected service callback, not a caller-controlled fixture in production."""

    def __call__(
        self, request: WitnessCommitRequest, service_context: object, /
    ) -> IndependentFinalizationEvidence: ...


FinalizationAuthorizer = Callable[[str, str, object], bool]


@dataclass(frozen=True, slots=True)
class ProtectedFinalizationReservation:
    """Durable service-side fence observation, never a finalization grant."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    proposal_sha256: str
    selection_sha256: str
    recovery_capsule_sha256: str
    journal_sha256: str
    service_envelope_sha256: str
    independent_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_request(
    request_bytes: bytes,
    preflight: PlanFinalizationPreflight,
) -> WitnessCommitRequest:
    if (
        type(request_bytes) is not bytes
        or not 1 <= len(request_bytes) <= 48 * 1024
        or not isinstance(preflight, PlanFinalizationPreflight)
        or any(
            type(getattr(preflight, f.name)) is not ftype
            for f, ftype in (
                (fields(PlanFinalizationPreflight)[0], str),
                (fields(PlanFinalizationPreflight)[1], str),
                (fields(PlanFinalizationPreflight)[2], str),
                (fields(PlanFinalizationPreflight)[3], str),
                (fields(PlanFinalizationPreflight)[4], int),
                (fields(PlanFinalizationPreflight)[5], int),
            )
        )
        or preflight.status != _REVIEW_STATUS
        or preflight.authority != _REVIEW_AUTHORITY
        or any(
            type(value) is not str or _HEX.fullmatch(value) is None
            for value in (
                preflight.request_sha256,
                preflight.successor_sha256,
                preflight.proposal_sha256,
                preflight.selection_sha256,
                preflight.recovery_capsule_sha256,
                preflight.journal_sha256,
                preflight.service_envelope_sha256,
            )
        )
    ):
        raise PlanFinalizationFenceError("noncanonical, non-authorizing preflight")
    try:
        request = parse_witness_commit_request(request_bytes)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
        canonical = serialize_witness_commit_request(request)
    except (WitnessCommitProtocolError, ActiveReceiptError) as error:
        raise PlanFinalizationFenceError(
            "invalid canonical successor request"
        ) from error
    if (
        canonical != request_bytes
        or preflight.installation_id != request.installation_id
        or preflight.transaction_id != successor.transaction_id
        or preflight.request_sha256 != _sha(canonical)
        or preflight.successor_sha256 != request.successor_sha256
        or preflight.generation != successor.generation
        or preflight.witness_revision != request.expected_witness_revision + 1
        or _TX.fullmatch(preflight.installation_id) is None
        or _TX.fullmatch(preflight.transaction_id) is None
    ):
        raise PlanFinalizationFenceError("preflight differs from exact request")
    return request


def _basis_matches(
    evidence: IndependentFinalizationEvidence,
    preflight: PlanFinalizationPreflight,
) -> bool:
    if not isinstance(evidence, IndependentFinalizationEvidence):
        return False
    bindings = (
        ("installation_id", "installation_id"),
        ("transaction_id", "transaction_id"),
        ("request_sha256", "request_sha256"),
        ("successor_sha256", "successor_sha256"),
        ("successor_generation", "generation"),
        ("witness_revision", "witness_revision"),
        ("proposal_sha256", "proposal_sha256"),
        ("selection_sha256", "selection_sha256"),
        ("recovery_capsule_sha256", "recovery_capsule_sha256"),
        ("journal_sha256", "journal_sha256"),
        ("service_envelope_sha256", "service_envelope_sha256"),
    )
    for evidence_name, review_name in bindings:
        original = getattr(preflight, review_name)
        proposed = getattr(evidence, evidence_name)
        if type(proposed) is not type(original) or proposed != original:
            return False
    return (
        type(evidence.independent_evidence_sha256) is str
        and _HEX.fullmatch(evidence.independent_evidence_sha256) is not None
        and evidence.all_writers_stopped is True
        and evidence.independently_reaudited_bytes is True
        and evidence.operator_consent_confirmed is True
    )


class ProtectedPlanFinalizationFence:
    """Service-owned SQLite one-per-installation reservation, never a writer.

    SQLite location, file permissions, lock reliability, process identity and
    service callbacks MUST all be protected independently in production.
    This class cannot prove that a Python process actually crosses a trust
    boundary; an untrusted local process MUST NOT own its connections.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        authorize: FinalizationAuthorizer,
    ) -> None:
        if (
            not isinstance(connection, sqlite3.Connection)
            or not callable(authorize)
            or connection.in_transaction
        ):
            raise PlanFinalizationFenceError("protected autocommit service DB required")
        self._db = connection
        self._authorize = authorize
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise PlanFinalizationFenceError(
                "cannot provision service fence"
            ) from error

    def _check_authority(
        self, installation_id: str, operation: str, service_context: object
    ) -> None:
        try:
            allowed = self._authorize(installation_id, operation, service_context)
        except Exception as error:
            raise PlanFinalizationFenceError(
                "service authorization unavailable"
            ) from error
        if allowed is not True:
            raise PlanFinalizationFenceError(
                "independent service authorization refused"
            )

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedFinalizationReservation | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise PlanFinalizationFenceError("invalid installation identity")
        self._check_authority(installation_id, "observe_finalization", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_finalization_fence_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise PlanFinalizationFenceError(
                "protected reservation unavailable"
            ) from error
        if row is None:
            return None
        try:
            record = ProtectedFinalizationReservation(*row)
        except (TypeError, ValueError) as error:
            raise PlanFinalizationFenceError("malformed durable reservation") from error
        if (
            record.status != _STATUS
            or record.authority != _AUTHORITY
            or record.installation_id != installation_id
            or type(record.transaction_id) is not str
            or _TX.fullmatch(record.transaction_id) is None
            or type(record.successor_generation) is not int
            or record.successor_generation < 1
            or type(record.witness_revision) is not int
            or record.witness_revision < 1
            or any(
                type(getattr(record, field)) is not str
                or _HEX.fullmatch(getattr(record, field)) is None
                for field in (
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
            raise PlanFinalizationFenceError("durable reservation corrupt")
        return record

    def reserve(
        self,
        request_bytes: bytes,
        preflight: PlanFinalizationPreflight,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
    ) -> ProtectedFinalizationReservation:
        """Write precisely one PREPARED reservation, without publication.

        A later retry is forbidden even with identical bytes. After any
        uncertain SQLite COMMIT, inspect read-only and reconcile explicitly.
        """
        request = _canonical_request(request_bytes, preflight)
        self._check_authority(
            request.installation_id, "reserve_finalization", service_context
        )
        if not callable(independently_read_evidence):
            raise PlanFinalizationFenceError("independent evidence reader missing")
        try:
            basis = independently_read_evidence(request, service_context)
        except Exception as error:
            raise PlanFinalizationFenceError(
                "independent evidence unavailable"
            ) from error
        if not _basis_matches(basis, preflight):
            raise PlanFinalizationFenceError(
                "service-protected witness, physical bytes, recovery and consent differ"
            )
        reservation = ProtectedFinalizationReservation(
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
            basis.independent_evidence_sha256,
        )
        # Atomic PRIMARY KEY reservation; never UPDATE/DELETE or clear a fence.
        # Reject anything already present, even when the request is identical.
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT installation_id FROM plan_finalization_fence_v1 "
                    "WHERE installation_id = ?",
                    (request.installation_id,),
                ).fetchone()
                if existing is not None:
                    raise PlanFinalizationFenceError(
                        "finalization already reserved; retry/overwrite refused"
                    )
                self._db.execute(
                    "INSERT INTO plan_finalization_fence_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        reservation.installation_id,
                        reservation.transaction_id,
                        reservation.request_sha256,
                        reservation.successor_sha256,
                        reservation.successor_generation,
                        reservation.witness_revision,
                        reservation.proposal_sha256,
                        reservation.selection_sha256,
                        reservation.recovery_capsule_sha256,
                        reservation.journal_sha256,
                        reservation.service_envelope_sha256,
                        reservation.independent_evidence_sha256,
                        reservation.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except PlanFinalizationFenceError:
            raise
        except sqlite3.Error as error:
            raise PlanFinalizationFenceError(
                "reservation possibly indeterminate; read-only inspection required"
            ) from error
        return reservation


__all__ = (
    "IndependentFinalizationEvidence",
    "IndependentFinalizationReader",
    "PlanFinalizationFenceError",
    "ProtectedFinalizationReservation",
    "ProtectedPlanFinalizationFence",
)
