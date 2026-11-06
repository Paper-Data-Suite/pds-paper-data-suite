"""Issue #49 Slice 86: durable capsule pre-delete uncertainty, no deletion.

A one-shot service-owned marker must exist before any separately implemented
filesystem capsule deletion can be considered. This module never removes any
file, calls a deletion adapter, clears recovery, switches software, or grants
launch/rollback authority. An ACK loss or crash requires read-only inspection:
never automatically rearm, infer deletion from a missing capsule, or retry.

Independent OS custody, service identity, exclusive fencing, and protected
witness key/clock are deployment obligations, not Python dataclass properties.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final

from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_capsule_clearance_preflight import (
    CapsuleClearancePreflightError,
    IndependentCapsuleReader,
    ProtectedCapsuleClearancePreflight,
    ProtectedCapsuleClearancePreflightLedger,
    _convergence_hash,
    _exact_capsule,
)
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationReader,
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_local_convergence import (
    IndependentNoInflightReader,
    LocalConvergenceError,
    ProtectedLocalConvergenceRecord,
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
_PREFLIGHT_STATUS: Final = "CAPSULE_CLEARANCE_PREFLIGHT_RECORDED_NO_DELETE_DISPATCH"
_PREFLIGHT_AUTH: Final = (
    "NO_CAPSULE_DELETE_RETRY_ROLLBACK_SWITCH_LAUNCH_OR_CAS_AUTHORITY"
)
_STATUS: Final = "CAPSULE_PREDELETE_UNCERTAINTY_ARMED_NO_DELETE_DISPATCH"
_AUTHORITY: Final = "NO_DELETE_RETRY_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_SUCCESSOR: Final = "SUCCESSOR_VISIBLE_CONVERGENCE_NOT_YET_AUTHORIZED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_capsule_predelete_uncertainty_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    clearance_preflight_sha256 TEXT NOT NULL,
    convergence_record_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    capsule_identity_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    independent_fence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'CAPSULE_PREDELETE_UNCERTAINTY_ARMED_NO_DELETE_DISPATCH'
    )
)
"""


class CapsulePredeleteUncertaintyError(ValueError):
    """Protected capsule deletion remains uncertain and unauthorized."""


@dataclass(frozen=True, slots=True)
class ProtectedCapsulePredeleteUncertainty:
    """Append-once pre-deletion marker; NO filesystem or launch capability."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    clearance_preflight_sha256: str
    convergence_record_sha256: str
    recovery_capsule_sha256: str
    capsule_identity_sha256: str
    target_identity_sha256: str
    independent_fence_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _preflight_hash(item: ProtectedCapsuleClearancePreflight) -> str:
    """Bind all original preflight metadata, including its negative authority."""
    return _sha(
        json.dumps(
            {f.name: getattr(item, f.name) for f in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_preflight(
    preflight: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    convergence: ProtectedLocalConvergenceRecord,
) -> bool:
    if not isinstance(preflight, ProtectedCapsuleClearancePreflight):
        return False
    for f in fields(preflight):
        value = getattr(preflight, f.name)
        expected = (
            int if f.name in ("successor_generation", "witness_revision") else str
        )
        if type(value) is not expected:
            return False
        if f.name.endswith("_sha256") and (
            not isinstance(value, str) or _SHA.fullmatch(value) is None
        ):
            return False
    return (
        preflight.status == _PREFLIGHT_STATUS
        and preflight.authority == _PREFLIGHT_AUTH
        and preflight.installation_id == request.installation_id
        and preflight.transaction_id == reservation.transaction_id
        and preflight.request_sha256 == reservation.request_sha256
        and preflight.successor_sha256 == request.successor_sha256
        and preflight.successor_generation == reservation.successor_generation
        and preflight.witness_revision == reservation.witness_revision
        and preflight.convergence_record_sha256 == _convergence_hash(convergence)
        and preflight.recovery_capsule_sha256 == reservation.recovery_capsule_sha256
        and preflight.target_identity_sha256 == intent.target_identity_sha256
        and preflight.independent_fence_sha256
        == convergence.independently_fenced_evidence_sha256
    )


class ProtectedCapsulePredeleteUncertaintyLedger:
    """Same protected service SQLite as the finalization/clearance chain."""

    def __init__(self, clearance: ProtectedCapsuleClearancePreflightLedger) -> None:
        if (
            not isinstance(clearance, ProtectedCapsuleClearancePreflightLedger)
            or not isinstance(clearance._db, sqlite3.Connection)
            or clearance._db is not clearance._convergence._db
            or clearance._db is not clearance._convergence._dispatch._db
            or clearance._db.in_transaction
        ):
            raise CapsulePredeleteUncertaintyError(
                "exact protected clearance database required"
            )
        self._clearance = clearance
        self._db = clearance._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise CapsulePredeleteUncertaintyError(
                "cannot provision protected predelete table"
            ) from error

    def _authorize(self, install: str, operation: str, context: object) -> None:
        try:
            self._clearance._authorize(install, operation, context)
        except CapsuleClearancePreflightError as error:
            raise CapsulePredeleteUncertaintyError(
                "independent predelete authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedCapsulePredeleteUncertainty | None:
        """Read-only diagnostic; never permits another arm or a deletion."""
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise CapsulePredeleteUncertaintyError("invalid installation identity")
        self._authorize(installation_id, "observe_capsule_predelete", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_capsule_predelete_uncertainty_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise CapsulePredeleteUncertaintyError(
                "predelete row unavailable"
            ) from error
        if row is None:
            return None
        try:
            result = ProtectedCapsulePredeleteUncertainty(*row)
        except (TypeError, ValueError) as error:
            raise CapsulePredeleteUncertaintyError("predelete row malformed") from error
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
            or result.authority != _AUTHORITY
        ):
            raise CapsulePredeleteUncertaintyError("durable predelete row corrupt")
        return result

    def arm_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        convergence: ProtectedLocalConvergenceRecord,
        clearance_preflight: ProtectedCapsuleClearancePreflight,
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
    ) -> ProtectedCapsulePredeleteUncertainty:
        """Commit one uncertainty marker; invoke NO delete or filesystem writer.

        The marker must not be rearmed even when acknowledgment is lost.
        Real protected service operators must keep cross-resource OS fences
        while performing both physical reads and until COMMIT completes.
        """
        try:
            request = self._clearance._convergence._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise CapsulePredeleteUncertaintyError(
                "noncanonical protected capsule predelete basis"
            ) from error
        if (
            not _exact_preflight(
                clearance_preflight, request, reservation, intent, convergence
            )
            or type(pinned_capsule_identity_sha256) is not str
            or _SHA.fullmatch(pinned_capsule_identity_sha256) is None
            or clearance_preflight.capsule_identity_sha256
            != pinned_capsule_identity_sha256
            or not callable(independently_read_capsule)
        ):
            raise CapsulePredeleteUncertaintyError(
                "invalid non-authorizing capsule clearance preflight"
            )
        try:
            self._clearance._convergence._prepare_runtime(
                request,
                reservation,
                service_context=service_context,
                independently_read_evidence=independently_read_evidence,
                independently_read_local_receipt=independently_read_local_receipt,
                independently_confirm_quiescence=independently_confirm_quiescence,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                operation="arm_capsule_predelete_once",
            )
        except LocalConvergenceError as error:
            raise CapsulePredeleteUncertaintyError(
                "independent predelete authorization or inputs refused"
            ) from error
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._clearance._convergence._read_under_service_lock(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    marker,
                    claim,
                    service_context=service_context,
                )
                actual_convergence = self._clearance._convergence.observe(
                    request.installation_id, service_context=service_context
                )
                actual_preflight = self._clearance.observe(
                    request.installation_id, service_context=service_context
                )
                if (
                    type(actual_convergence) is not type(convergence)
                    or actual_convergence != convergence
                    or type(actual_preflight) is not type(clearance_preflight)
                    or actual_preflight != clearance_preflight
                ):
                    raise CapsulePredeleteUncertaintyError(
                        "protected convergence or clearance preflight drifted"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_capsule_predelete_uncertainty_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise CapsulePredeleteUncertaintyError(
                        "capsule predelete already armed; no replay or retry"
                    )
                try:
                    first_capsule = independently_read_capsule(request, service_context)
                except Exception as error:
                    raise CapsulePredeleteUncertaintyError(
                        "independent initial capsule inspection unavailable"
                    ) from error
                if not _exact_capsule(
                    first_capsule,
                    request,
                    reservation,
                    pinned_capsule_identity_sha256,
                ):
                    raise CapsulePredeleteUncertaintyError(
                        "capsule bytes, identity or protected custody changed"
                    )
                first_quiet, first_state, first_sha = (
                    self._clearance._convergence._sample(
                        request,
                        reservation,
                        intent,
                        claim,
                        service_context=service_context,
                        independently_read_evidence=independently_read_evidence,
                        independently_read_local_receipt=(
                            independently_read_local_receipt
                        ),
                        independently_confirm_quiescence=(
                            independently_confirm_quiescence
                        ),
                    )
                )
                if first_state != _SUCCESSOR or first_sha != request.successor_sha256:
                    raise CapsulePredeleteUncertaintyError(
                        "successor receipt not independently stable"
                    )
                self._clearance._convergence._dispatch._prewrite._signed(
                    request, reservation, witness_transport, pinned_public_key, now
                )
                try:
                    second_capsule = independently_read_capsule(
                        request, service_context
                    )
                except Exception as error:
                    raise CapsulePredeleteUncertaintyError(
                        "independent final capsule inspection unavailable"
                    ) from error
                second_quiet, second_state, second_sha = (
                    self._clearance._convergence._sample(
                        request,
                        reservation,
                        intent,
                        claim,
                        service_context=service_context,
                        independently_read_evidence=independently_read_evidence,
                        independently_read_local_receipt=(
                            independently_read_local_receipt
                        ),
                        independently_confirm_quiescence=(
                            independently_confirm_quiescence
                        ),
                    )
                )
                if (
                    first_capsule != second_capsule
                    or not _exact_capsule(
                        second_capsule,
                        request,
                        reservation,
                        pinned_capsule_identity_sha256,
                    )
                    or first_quiet != second_quiet
                    or not _quiescent(second_quiet, request, claim)
                    or second_state != _SUCCESSOR
                    or second_sha != first_sha
                    or _sha(
                        bytes.fromhex(second_quiet.writer_fence_sha256)
                        + bytes.fromhex(second_quiet.termination_evidence_sha256)
                    )
                    != clearance_preflight.independent_fence_sha256
                ):
                    raise CapsulePredeleteUncertaintyError(
                        "capsule, receipt, witness or no-inflight fence drifted"
                    )
                result = ProtectedCapsulePredeleteUncertainty(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _preflight_hash(clearance_preflight),
                    _convergence_hash(convergence),
                    reservation.recovery_capsule_sha256,
                    pinned_capsule_identity_sha256,
                    intent.target_identity_sha256,
                    clearance_preflight.independent_fence_sha256,
                )
                self._db.execute(
                    "INSERT INTO plan_capsule_predelete_uncertainty_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.clearance_preflight_sha256,
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
        except CapsulePredeleteUncertaintyError:
            raise
        except (
            sqlite3.Error,
            CapsuleClearancePreflightError,
            LocalConvergenceError,
            LocalPrewriteUncertaintyError,
        ) as error:
            raise CapsulePredeleteUncertaintyError(
                "predelete transaction uncertain; read-only reconciliation required"
            ) from error


__all__ = (
    "CapsulePredeleteUncertaintyError",
    "ProtectedCapsulePredeleteUncertainty",
    "ProtectedCapsulePredeleteUncertaintyLedger",
)
