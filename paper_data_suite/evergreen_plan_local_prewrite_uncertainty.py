"""Issue #49 Slice 82: write-ahead uncertainty and local classification.

A service-owned PREWRITE marker is committed before any future local receipt
writer may be dispatched. No writer is present here. Neither predecessor
readback nor absence of a file grants a retry, rollback, capsule cleanup,
launcher readiness, or further witness CAS. Production independent service
and filesystem isolation are external deployment obligations.
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
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    IndependentLocalDeploymentReader,
    LocalDeploymentIntentError,
    ProtectedLocalDeploymentIntent,
    ProtectedLocalReceiptDeploymentPlanner,
    _local_matches,
    _record_hash,
    _valid_protected_record,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedPlanReceiptError,
    ProtectedServiceReceiptRecord,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    PlanPublicationPreclaimError,
    ProtectedPublicationPreclaim,
    _fresh_basis_matches,
    _request_and_reservation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    inspect_uncertain_witness_commit,
)

_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_PREPARED: Final = "LOCAL_RECEIPT_DEPLOYMENT_PREPARED_NO_FILE_WRITE"
_PREPARED_AUTH: Final = (
    "NO_LOCAL_RECEIPT_WRITE_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
)
_MARKER: Final = "LOCAL_PREWRITE_UNCERTAINTY_ARMED_NO_WRITER_DISPATCH"
_AUTHORITY: Final = "NO_RETRY_WRITE_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_SIGNED: Final = "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_local_prewrite_uncertainty_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    local_deployment_intent_sha256 TEXT NOT NULL,
    protected_receipt_record_sha256 TEXT NOT NULL,
    predecessor_receipt_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    local_snapshot_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LOCAL_PREWRITE_UNCERTAINTY_ARMED_NO_WRITER_DISPATCH'
    )
)
"""


class LocalPrewriteUncertaintyError(ValueError):
    """Refuse a changed protected basis, unauthorized read, or uncertain write."""


@dataclass(frozen=True, slots=True)
class ProtectedLocalPrewriteUncertainty:
    """Service-owned immutable pre-write marker; no file-write capability."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    local_deployment_intent_sha256: str
    protected_receipt_record_sha256: str
    predecessor_receipt_sha256: str
    target_identity_sha256: str
    recovery_capsule_sha256: str
    local_snapshot_sha256: str
    status: str = _MARKER
    authority: str = _AUTHORITY


@dataclass(frozen=True, slots=True)
class IndependentLocalReceiptReadback:
    """Raw file sample from the *independently operated* protected reader.

    Mere Python construction of this type is not service authentication.
    The caller must not control the reader, its path, pinned target or locks.
    """

    installation_id: str
    transaction_id: str
    request_sha256: str
    target_identity_sha256: str
    active_receipt_bytes: bytes | None
    proposal_sha256: str
    selection_sha256: str
    recovery_capsule_sha256: str
    journal_sha256: str
    protected_target_parent: bool
    protected_ordinary_active_file: bool
    protected_ordinary_capsule: bool
    installation_writers_exclusively_fenced: bool
    candidate_physical_bytes_rechecked: bool


class IndependentLocalReceiptReader(Protocol):
    """Independently provisioned file reader; never a teacher callback."""

    def __call__(
        self, request: WitnessCommitRequest, service_context: object, /
    ) -> IndependentLocalReceiptReadback: ...


@dataclass(frozen=True, slots=True)
class ProtectedLocalReceiptClassification:
    """Diagnostic readback only. All outcomes require protected reconciliation."""

    installation_id: str
    transaction_id: str
    observed_receipt_sha256: str | None
    witness_revision: int
    status: str
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _intent_hash(intent: ProtectedLocalDeploymentIntent) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(intent, f.name) for f in fields(intent)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _intent_matches(
    intent: ProtectedLocalDeploymentIntent,
    reservation: ProtectedFinalizationReservation,
    record: ProtectedServiceReceiptRecord,
    request: WitnessCommitRequest,
) -> bool:
    if not isinstance(intent, ProtectedLocalDeploymentIntent):
        return False
    for field in fields(intent):
        value = getattr(intent, field.name)
        expected = (
            int if field.name in ("successor_generation", "witness_revision") else str
        )
        if type(value) is not expected:
            return False
        if field.name.endswith("_sha256") and (
            not isinstance(value, str) or _SHA.fullmatch(value) is None
        ):
            return False
    return (
        intent.status == _PREPARED
        and intent.authority == _PREPARED_AUTH
        and intent.installation_id == request.installation_id
        and intent.transaction_id == reservation.transaction_id
        and intent.request_sha256 == reservation.request_sha256
        and intent.successor_sha256 == request.successor_sha256
        and intent.successor_generation == reservation.successor_generation
        and intent.witness_revision == reservation.witness_revision
        and intent.protected_receipt_record_sha256 == _record_hash(record)
        and intent.predecessor_receipt_sha256 == request.predecessor_sha256
        and intent.proposal_sha256 == reservation.proposal_sha256
        and intent.selection_sha256 == reservation.selection_sha256
        and intent.recovery_capsule_sha256 == reservation.recovery_capsule_sha256
        and intent.journal_sha256 == reservation.journal_sha256
        and intent.independent_evidence_sha256
        == reservation.independent_evidence_sha256
    )


def _readback_matches(
    observed: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
) -> bool:
    if not isinstance(observed, IndependentLocalReceiptReadback):
        return False
    for field in fields(observed):
        v = getattr(observed, field.name)
        if field.name == "active_receipt_bytes":
            if v is not None and (type(v) is not bytes or len(v) > 16 * 1024):
                return False
        elif field.name.startswith("protected_") or field.name in (
            "installation_writers_exclusively_fenced",
            "candidate_physical_bytes_rechecked",
        ):
            if type(v) is not bool:
                return False
        elif type(v) is not str:
            return False
    return (
        observed.installation_id == request.installation_id
        and observed.transaction_id == reservation.transaction_id
        and observed.request_sha256 == reservation.request_sha256
        and observed.target_identity_sha256 == intent.target_identity_sha256
        and observed.proposal_sha256 == intent.proposal_sha256
        and observed.selection_sha256 == intent.selection_sha256
        and observed.recovery_capsule_sha256 == intent.recovery_capsule_sha256
        and observed.journal_sha256 == intent.journal_sha256
        and observed.protected_target_parent is True
        and observed.protected_ordinary_capsule is True
        and observed.installation_writers_exclusively_fenced is True
        and observed.candidate_physical_bytes_rechecked is True
        and (
            observed.active_receipt_bytes is None
            or observed.protected_ordinary_active_file is True
        )
    )


class ProtectedLocalPrewriteUncertaintyLedger:
    """Share the exact protected SQLite connection of Slices 78--81."""

    def __init__(self, planner: ProtectedLocalReceiptDeploymentPlanner) -> None:
        if (
            not isinstance(planner, ProtectedLocalReceiptDeploymentPlanner)
            or not isinstance(planner._db, sqlite3.Connection)
            or planner._db is not planner._writer._db
            or planner._db is not planner._writer._preclaims._db
            or planner._db is not planner._writer._preclaims._fence._db
            or planner._db.in_transaction
        ):
            raise LocalPrewriteUncertaintyError("exact protected connection required")
        self._planner = planner
        self._db = planner._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LocalPrewriteUncertaintyError("prewrite table unavailable") from error

    def _authorize(self, install: str, op: str, context: object) -> None:
        try:
            self._planner._authorize(install, op, context)
        except LocalDeploymentIntentError as error:
            raise LocalPrewriteUncertaintyError(
                "independent prewrite authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLocalPrewriteUncertainty | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LocalPrewriteUncertaintyError("invalid installation identity")
        self._authorize(installation_id, "observe_local_prewrite", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_local_prewrite_uncertainty_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LocalPrewriteUncertaintyError("prewrite row unreadable") from error
        if row is None:
            return None
        try:
            item = ProtectedLocalPrewriteUncertainty(*row)
        except (TypeError, ValueError) as error:
            raise LocalPrewriteUncertaintyError("prewrite row malformed") from error
        if (
            item.installation_id != installation_id
            or type(item.transaction_id) is not str
            or _TX.fullmatch(item.transaction_id) is None
            or type(item.successor_generation) is not int
            or not 1 <= item.successor_generation <= 2**53 - 1
            or type(item.witness_revision) is not int
            or not 1 <= item.witness_revision <= 2**53 - 1
            or any(
                type(getattr(item, field.name)) is not str
                or _SHA.fullmatch(getattr(item, field.name)) is None
                for field in fields(item)
                if field.name.endswith("_sha256")
            )
            or item.status != _MARKER
            or item.authority != _AUTHORITY
        ):
            raise LocalPrewriteUncertaintyError("durable prewrite row corrupt")
        return item

    def _basis(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
    ) -> WitnessCommitRequest:
        try:
            request = _request_and_reservation(request_bytes, reservation)
        except PlanPublicationPreclaimError as error:
            raise LocalPrewriteUncertaintyError(
                "noncanonical successor request"
            ) from error
        if not _valid_protected_record(
            record, reservation, preclaim
        ) or not _intent_matches(intent, reservation, record, request):
            raise LocalPrewriteUncertaintyError("noncanonical protected prewrite basis")
        return request

    def _durable_basis(
        self,
        request: WitnessCommitRequest,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        *,
        service_context: object,
    ) -> None:
        f = self._planner._writer._preclaims._fence
        p = self._planner._writer._preclaims
        w = self._planner._writer
        actual = (
            f.observe(request.installation_id, service_context=service_context),
            p.observe(request.installation_id, service_context=service_context),
            w.observe(request.installation_id, service_context=service_context),
            self._planner.observe(
                request.installation_id, service_context=service_context
            ),
        )
        expected = (reservation, preclaim, record, intent)
        if any(type(a) is not type(b) or a != b for a, b in zip(actual, expected)):
            raise LocalPrewriteUncertaintyError(
                "durable protected reservation, receipt or intent changed"
            )

    @staticmethod
    def _signed(
        request: WitnessCommitRequest,
        reservation: ProtectedFinalizationReservation,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> None:
        try:
            signed = inspect_uncertain_witness_commit(
                request,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                minimum_witness_revision=reservation.witness_revision,
            )
        except WitnessCommitProtocolError as error:
            raise LocalPrewriteUncertaintyError(
                "fresh signed successor head unavailable"
            ) from error
        if (
            signed.status != _SIGNED
            or signed.installation_id != request.installation_id
            or type(signed.witness_revision) is not int
            or signed.witness_revision != reservation.witness_revision
            or type(signed.generation) is not int
            or signed.generation != reservation.successor_generation
            or signed.receipt_sha256 != request.successor_sha256
        ):
            raise LocalPrewriteUncertaintyError("signed successor mismatch")

    @staticmethod
    def _validate_runtime(
        *,
        independently_read_evidence: IndependentFinalizationReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> None:
        if (
            not callable(independently_read_evidence)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
        ):
            raise LocalPrewriteUncertaintyError("independent service inputs missing")

    def arm_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local: IndependentLocalDeploymentReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLocalPrewriteUncertainty:
        """Commit uncertainty *before* any future writer. No writer here."""
        request = self._basis(request_bytes, reservation, preclaim, record, intent)
        self._validate_runtime(
            independently_read_evidence=independently_read_evidence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
        )
        if not callable(independently_read_local) or self._db.in_transaction:
            raise LocalPrewriteUncertaintyError("independent local reader unavailable")
        self._authorize(
            request.installation_id, "arm_local_prewrite_once", service_context
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._durable_basis(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    service_context=service_context,
                )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_local_prewrite_uncertainty_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LocalPrewriteUncertaintyError(
                        "prewrite already armed; no replay or automatic retry"
                    )
                try:
                    independent = independently_read_evidence(request, service_context)
                    local = independently_read_local(request, service_context)
                except Exception as error:
                    raise LocalPrewriteUncertaintyError(
                        "independent physical read unavailable"
                    ) from error
                if (
                    not _fresh_basis_matches(independent, reservation)
                    or not _local_matches(
                        local,
                        request,
                        reservation,
                        pinned_target_identity_sha256=intent.target_identity_sha256,
                    )
                    or local.local_snapshot_sha256 != intent.local_snapshot_sha256
                ):
                    raise LocalPrewriteUncertaintyError(
                        "protected installed bytes, predecessor or capsule changed"
                    )
                self._signed(
                    request, reservation, witness_transport, pinned_public_key, now
                )
                marker = ProtectedLocalPrewriteUncertainty(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _intent_hash(intent),
                    _record_hash(record),
                    request.predecessor_sha256,
                    intent.target_identity_sha256,
                    intent.recovery_capsule_sha256,
                    intent.local_snapshot_sha256,
                )
                self._db.execute(
                    "INSERT INTO plan_local_prewrite_uncertainty_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        marker.installation_id,
                        marker.transaction_id,
                        marker.request_sha256,
                        marker.successor_sha256,
                        marker.successor_generation,
                        marker.witness_revision,
                        marker.local_deployment_intent_sha256,
                        marker.protected_receipt_record_sha256,
                        marker.predecessor_receipt_sha256,
                        marker.target_identity_sha256,
                        marker.recovery_capsule_sha256,
                        marker.local_snapshot_sha256,
                        marker.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LocalPrewriteUncertaintyError:
            raise
        except (
            sqlite3.Error,
            PlanFinalizationFenceError,
            PlanPublicationPreclaimError,
            ProtectedPlanReceiptError,
            LocalDeploymentIntentError,
        ) as error:
            raise LocalPrewriteUncertaintyError(
                "prewrite COMMIT possibly uncertain; read-only reconciliation required"
            ) from error
        return marker

    def inspect_after_uncertainty(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLocalReceiptClassification:
        """Read-only classification, never proof that an in-flight write stopped."""
        request = self._basis(request_bytes, reservation, preclaim, record, intent)
        self._validate_runtime(
            independently_read_evidence=independently_read_evidence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
        )
        if not callable(independently_read_local_receipt) or self._db.in_transaction:
            raise LocalPrewriteUncertaintyError("independent readback unavailable")
        self._authorize(
            request.installation_id, "inspect_local_prewrite", service_context
        )
        marker = self.observe(request.installation_id, service_context=service_context)
        if marker is None:
            raise LocalPrewriteUncertaintyError("prewrite marker absent; no inference")
        self._durable_basis(
            request,
            reservation,
            preclaim,
            record,
            intent,
            service_context=service_context,
        )
        if (
            marker.local_deployment_intent_sha256 != _intent_hash(intent)
            or marker.protected_receipt_record_sha256 != _record_hash(record)
            or marker.predecessor_receipt_sha256 != request.predecessor_sha256
            or marker.target_identity_sha256 != intent.target_identity_sha256
            or marker.recovery_capsule_sha256 != intent.recovery_capsule_sha256
            or marker.local_snapshot_sha256 != intent.local_snapshot_sha256
            or marker.request_sha256 != reservation.request_sha256
            or marker.successor_sha256 != request.successor_sha256
            or marker.transaction_id != reservation.transaction_id
            or marker.successor_generation != reservation.successor_generation
            or marker.witness_revision != reservation.witness_revision
        ):
            raise LocalPrewriteUncertaintyError("armed marker differs from intent")
        try:
            independent = independently_read_evidence(request, service_context)
            physical = independently_read_local_receipt(request, service_context)
        except Exception as error:
            raise LocalPrewriteUncertaintyError(
                "independent post-uncertainty read unavailable"
            ) from error
        if not _fresh_basis_matches(independent, reservation) or not _readback_matches(
            physical, request, reservation, intent
        ):
            raise LocalPrewriteUncertaintyError(
                "protected witness, target, capsule or physical readback changed"
            )
        self._signed(request, reservation, witness_transport, pinned_public_key, now)
        assert isinstance(physical, IndependentLocalReceiptReadback)
        raw = physical.active_receipt_bytes
        if raw is None:
            status = "LOCAL_RECEIPT_MISSING_MANUAL_RECOVERY_REQUIRED"
        elif raw == request.previous_receipt_bytes:
            status = "PREDECESSOR_VISIBLE_NO_RETRY_AUTHORITY"
        elif raw == request.successor_receipt_bytes:
            status = "SUCCESSOR_VISIBLE_RECOVERY_STILL_PENDING"
        else:
            status = "UNKNOWN_LOCAL_RECEIPT_QUARANTINE_REQUIRED"
        return ProtectedLocalReceiptClassification(
            request.installation_id,
            reservation.transaction_id,
            _sha(raw) if raw is not None else None,
            reservation.witness_revision,
            status,
        )


__all__ = (
    "IndependentLocalReceiptReadback",
    "IndependentLocalReceiptReader",
    "LocalPrewriteUncertaintyError",
    "ProtectedLocalPrewriteUncertainty",
    "ProtectedLocalPrewriteUncertaintyLedger",
    "ProtectedLocalReceiptClassification",
)
