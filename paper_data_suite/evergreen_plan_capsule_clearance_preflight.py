"""Issue #49 Slice 85: protected capsule-clearance *preflight*, not deletion.

A durable no-delete record is appended after independent byte-exact capsule
readback, certified successor convergence, fresh witness and quiescence.
NO method deletes a capsule, switches a slot or authorizes launch. A Python
callback/dataclass cannot establish actual OS custody or writer isolation.
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
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_local_convergence import (
    IndependentNoInflightReader,
    LocalConvergenceError,
    ProtectedLocalConvergenceCoordinator,
    ProtectedLocalConvergenceRecord,
    _claim_hash,
    _quiescent,
)
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    ProtectedLocalDeploymentIntent,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    IndependentLocalReceiptReader,
    LocalPrewriteUncertaintyError,
    ProtectedLocalPrewriteUncertainty,
)
from paper_data_suite.evergreen_plan_local_receipt_dispatch import (
    ProtectedLocalReceiptDispatchClaim,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedServiceReceiptRecord,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    ProtectedPublicationPreclaim,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_READY: Final = "LOCAL_RECEIPT_CONVERGENCE_RECORDED_CAPSULE_RETAINED"
_READY_AUTH: Final = "NO_RETRY_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS_AUTHORITY"
_STATUS: Final = "CAPSULE_CLEARANCE_PREFLIGHT_RECORDED_NO_DELETE_DISPATCH"
_AUTH: Final = "NO_CAPSULE_DELETE_RETRY_ROLLBACK_SWITCH_LAUNCH_OR_CAS_AUTHORITY"
_SUCCESSOR: Final = "SUCCESSOR_VISIBLE_CONVERGENCE_NOT_YET_AUTHORIZED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_capsule_clearance_preflight_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    convergence_record_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    capsule_identity_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    independent_fence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'CAPSULE_CLEARANCE_PREFLIGHT_RECORDED_NO_DELETE_DISPATCH'
    )
)
"""


class CapsuleClearancePreflightError(ValueError):
    """No capsule clearance or automatic retry is authorized."""


@dataclass(frozen=True, slots=True)
class IndependentlyHeldCapsule:
    """Physical sample from service-owned reader under independently held locks.

    The provisioner MUST protect the reader, path, filesystem, ACLs and lock.
    Merely instantiating this dataclass proves none of those properties.
    """

    installation_id: str
    transaction_id: str
    capsule_identity_sha256: str
    capsule_bytes: bytes
    capsule_is_protected_regular_file: bool
    parent_directory_protected: bool
    exclusive_service_capsule_fence_held: bool
    no_other_capsule_writer_can_start: bool


class IndependentCapsuleReader(Protocol):
    def __call__(
        self, request: WitnessCommitRequest, context: object, /
    ) -> IndependentlyHeldCapsule: ...


@dataclass(frozen=True, slots=True)
class ProtectedCapsuleClearancePreflight:
    """Immutable service-side audit marker, never a bearer deletion grant."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    convergence_record_sha256: str
    recovery_capsule_sha256: str
    capsule_identity_sha256: str
    target_identity_sha256: str
    independent_fence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _convergence_hash(value: ProtectedLocalConvergenceRecord) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(value, f.name) for f in fields(value)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_convergence(
    convergence: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    claim: ProtectedLocalReceiptDispatchClaim,
) -> bool:
    if not isinstance(convergence, ProtectedLocalConvergenceRecord):
        return False
    for f in fields(convergence):
        val = getattr(convergence, f.name)
        if type(val) is not (
            int if f.name in ("successor_generation", "witness_revision") else str
        ):
            return False
        if f.name.endswith("_sha256") and (
            not isinstance(val, str) or _SHA.fullmatch(val) is None
        ):
            return False
    return (
        convergence.status == _READY
        and convergence.authority == _READY_AUTH
        and convergence.installation_id == request.installation_id
        and convergence.transaction_id == reservation.transaction_id
        and convergence.request_sha256 == reservation.request_sha256
        and convergence.successor_sha256 == request.successor_sha256
        and convergence.successor_generation == reservation.successor_generation
        and convergence.witness_revision == reservation.witness_revision
        and convergence.dispatch_claim_sha256 == _claim_hash(claim)
        and convergence.target_identity_sha256 == intent.target_identity_sha256
        and convergence.recovery_capsule_sha256 == intent.recovery_capsule_sha256
    )


def _exact_capsule(
    observed: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    pinned_identity: str,
) -> bool:
    if not isinstance(observed, IndependentlyHeldCapsule):
        return False
    if (
        type(observed.installation_id) is not str
        or type(observed.transaction_id) is not str
        or type(observed.capsule_identity_sha256) is not str
        or type(observed.capsule_bytes) is not bytes
        or not 1 <= len(observed.capsule_bytes) <= 80 * 1024
        or any(
            type(getattr(observed, f.name)) is not bool
            or getattr(observed, f.name) is not True
            for f in fields(observed)
            if f.name
            in (
                "capsule_is_protected_regular_file",
                "parent_directory_protected",
                "exclusive_service_capsule_fence_held",
                "no_other_capsule_writer_can_start",
            )
        )
    ):
        return False
    return (
        observed.installation_id == request.installation_id
        and observed.transaction_id == reservation.transaction_id
        and observed.capsule_identity_sha256 == pinned_identity
        and _sha(observed.capsule_bytes) == reservation.recovery_capsule_sha256
    )


class ProtectedCapsuleClearancePreflightLedger:
    """Append-only preflight on exact protected Slice-78..84 SQLite connection."""

    def __init__(self, convergence: ProtectedLocalConvergenceCoordinator) -> None:
        if (
            not isinstance(convergence, ProtectedLocalConvergenceCoordinator)
            or not isinstance(convergence._db, sqlite3.Connection)
            or convergence._db is not convergence._dispatch._db
            or convergence._db is not convergence._dispatch._prewrite._db
            or convergence._db.in_transaction
        ):
            raise CapsuleClearancePreflightError("protected convergence DB required")
        self._convergence = convergence
        self._db = convergence._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise CapsuleClearancePreflightError(
                "preflight table unavailable"
            ) from error

    def _authorize(self, install: str, operation: str, context: object) -> None:
        try:
            self._convergence._authorize(install, operation, context)
        except LocalConvergenceError as error:
            raise CapsuleClearancePreflightError(
                "independent capsule preflight authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedCapsuleClearancePreflight | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise CapsuleClearancePreflightError("invalid installation identity")
        self._authorize(
            installation_id, "observe_capsule_clearance_preflight", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_capsule_clearance_preflight_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise CapsuleClearancePreflightError("preflight row unavailable") from error
        if row is None:
            return None
        try:
            result = ProtectedCapsuleClearancePreflight(*row)
        except (TypeError, ValueError) as error:
            raise CapsuleClearancePreflightError(
                "preflight record malformed"
            ) from error
        if (
            result.installation_id != installation_id
            or type(result.transaction_id) is not str
            or _TX.fullmatch(result.transaction_id) is None
            or type(result.successor_generation) is not int
            or not 1 <= result.successor_generation <= 2**53 - 1
            or type(result.witness_revision) is not int
            or not 1 <= result.witness_revision <= 2**53 - 1
            or any(
                type(getattr(result, f.name)) is not str
                or _SHA.fullmatch(getattr(result, f.name)) is None
                for f in fields(result)
                if f.name.endswith("_sha256")
            )
            or result.status != _STATUS
            or result.authority != _AUTH
        ):
            raise CapsuleClearancePreflightError("preflight row corrupt")
        return result

    def prepare_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        convergence: ProtectedLocalConvergenceRecord,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
        independently_read_capsule: IndependentCapsuleReader,
        pinned_capsule_identity_sha256: str,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedCapsuleClearancePreflight:
        """Record readiness for *future review*, never invoke capsule deletion.

        An existing row, even after a lost SQLite COMMIT ACK, is not rearmed.
        All independent readers, physical locks and custody MUST be OS-protected.
        """
        try:
            request = self._convergence._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise CapsuleClearancePreflightError(
                "noncanonical capsule clearance basis"
            ) from error
        if (
            not _exact_convergence(convergence, request, reservation, intent, claim)
            or type(pinned_capsule_identity_sha256) is not str
            or _SHA.fullmatch(pinned_capsule_identity_sha256) is None
            or not callable(independently_read_capsule)
        ):
            raise CapsuleClearancePreflightError(
                "invalid non-authorizing clearance inputs"
            )
        try:
            self._convergence._prepare_runtime(
                request,
                reservation,
                service_context=service_context,
                independently_read_evidence=independently_read_evidence,
                independently_read_local_receipt=independently_read_local_receipt,
                independently_confirm_quiescence=independently_confirm_quiescence,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                operation="prepare_capsule_clearance_once",
            )
        except LocalConvergenceError as error:
            raise CapsuleClearancePreflightError(
                "independent capsule clearance authorization/inputs refused"
            ) from error
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._convergence._read_under_service_lock(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    marker,
                    claim,
                    service_context=service_context,
                )
                persisted = self._convergence.observe(
                    request.installation_id, service_context=service_context
                )
                if type(persisted) is not type(convergence) or persisted != convergence:
                    raise CapsuleClearancePreflightError(
                        "protected convergence absent or changed"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_capsule_clearance_preflight_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise CapsuleClearancePreflightError(
                        "capsule preflight already recorded; no retry or rearm"
                    )
                try:
                    first_capsule = independently_read_capsule(request, service_context)
                except Exception as error:
                    raise CapsuleClearancePreflightError(
                        "independent capsule byte inspection unavailable"
                    ) from error
                if not _exact_capsule(
                    first_capsule,
                    request,
                    reservation,
                    pinned_capsule_identity_sha256,
                ):
                    raise CapsuleClearancePreflightError(
                        "capsule bytes, custody or protected identity changed"
                    )
                first_quiet, state, observed_sha = self._convergence._sample(
                    request,
                    reservation,
                    intent,
                    claim,
                    service_context=service_context,
                    independently_read_evidence=independently_read_evidence,
                    independently_read_local_receipt=independently_read_local_receipt,
                    independently_confirm_quiescence=independently_confirm_quiescence,
                )
                if state != _SUCCESSOR or observed_sha != request.successor_sha256:
                    raise CapsuleClearancePreflightError(
                        "successor no longer present; retain recovery capsule"
                    )
                self._convergence._dispatch._prewrite._signed(
                    request, reservation, witness_transport, pinned_public_key, now
                )
                try:
                    second_capsule = independently_read_capsule(
                        request, service_context
                    )
                except Exception as error:
                    raise CapsuleClearancePreflightError(
                        "independent final capsule read unavailable"
                    ) from error
                second_quiet, second_state, second_sha = self._convergence._sample(
                    request,
                    reservation,
                    intent,
                    claim,
                    service_context=service_context,
                    independently_read_evidence=independently_read_evidence,
                    independently_read_local_receipt=independently_read_local_receipt,
                    independently_confirm_quiescence=independently_confirm_quiescence,
                )
                if (
                    second_capsule != first_capsule
                    or not _exact_capsule(
                        second_capsule,
                        request,
                        reservation,
                        pinned_capsule_identity_sha256,
                    )
                    or first_quiet != second_quiet
                    or second_state != _SUCCESSOR
                    or second_sha != observed_sha
                    or not _quiescent(second_quiet, request, claim)
                    or _sha(
                        bytes.fromhex(second_quiet.writer_fence_sha256)
                        + bytes.fromhex(second_quiet.termination_evidence_sha256)
                    )
                    != convergence.independently_fenced_evidence_sha256
                ):
                    raise CapsuleClearancePreflightError(
                        "fresh capsule/receipt/fence state drifted; no clearance"
                    )
                result = ProtectedCapsuleClearancePreflight(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _convergence_hash(convergence),
                    reservation.recovery_capsule_sha256,
                    pinned_capsule_identity_sha256,
                    intent.target_identity_sha256,
                    convergence.independently_fenced_evidence_sha256,
                )
                self._db.execute(
                    "INSERT INTO plan_capsule_clearance_preflight_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.convergence_record_sha256,
                        result.recovery_capsule_sha256,
                        result.capsule_identity_sha256,
                        result.target_identity_sha256,
                        result.independent_fence_sha256,
                        result.status,
                    ),
                )
                self._db.execute("COMMIT")
                return result
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except CapsuleClearancePreflightError:
            raise
        except (
            sqlite3.Error,
            LocalConvergenceError,
            LocalPrewriteUncertaintyError,
        ) as error:
            raise CapsuleClearancePreflightError(
                "preflight transaction uncertain; read-only review required"
            ) from error


__all__ = (
    "CapsuleClearancePreflightError",
    "IndependentlyHeldCapsule",
    "IndependentCapsuleReader",
    "ProtectedCapsuleClearancePreflight",
    "ProtectedCapsuleClearancePreflightLedger",
)
