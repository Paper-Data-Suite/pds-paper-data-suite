"""Issue #49 Slice 87: one-shot protected capsule deletion dispatch.

A service-side claim is durably committed BEFORE an independently administered
capsule deleter is called. Deletion may be uncertain even after a callback
returns. Neither an absent nor a remaining capsule permits a second dispatch,
launch, rollback, slot switching or receipt writes. No privileged filesystem
implementation is supplied by this Python protocol.
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
from paper_data_suite.evergreen_plan_capsule_clearance_preflight import (
    IndependentCapsuleReader,
    ProtectedCapsuleClearancePreflight,
    _exact_capsule,
)
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    CapsulePredeleteUncertaintyError,
    ProtectedCapsulePredeleteUncertainty,
    ProtectedCapsulePredeleteUncertaintyLedger,
    _exact_preflight,
    _preflight_hash,
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

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_STATUS: Final = "CAPSULE_DELETE_DISPATCH_CLAIMED_OUTCOME_UNCERTAIN"
_AUTH: Final = "NO_REDELETE_RETRY_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY"
_ARMED: Final = "CAPSULE_PREDELETE_UNCERTAINTY_ARMED_NO_DELETE_DISPATCH"
_ARMED_AUTH: Final = "NO_DELETE_RETRY_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_SUCCESSOR: Final = "SUCCESSOR_VISIBLE_CONVERGENCE_NOT_YET_AUTHORIZED"
_POST_ABSENT: Final = "CAPSULE_ABSENT_POSTDELETE_RECONCILIATION_REQUIRED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_capsule_delete_dispatch_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    predelete_marker_sha256 TEXT NOT NULL,
    clearance_preflight_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    capsule_identity_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    independent_fence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'CAPSULE_DELETE_DISPATCH_CLAIMED_OUTCOME_UNCERTAIN'
    )
)
"""


class CapsuleDeleteDispatchError(ValueError):
    """Refuse unverified or repeated deletion and ambiguous post-delete state."""


class IndependentCapsuleFileDeleter(Protocol):
    """Privileged independent service operation, NOT a caller-owned callback.

    The operating-system service must pin the exact capsule file identity,
    fence all writers and readers, reject reparse points and hard-link attacks,
    recheck exact bytes on the opened handle, durably remove only that file,
    and preserve service-side evidence. Python cannot prove these conditions.
    """

    def __call__(
        self,
        request: WitnessCommitRequest,
        capsule_identity_sha256: str,
        service_context: object,
        /,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class IndependentCapsuleDeleteReadback:
    """Postdelete read without assuming a recovery capsule still exists.

    Values must come from a physically independent service-controlled reader.
    A fabricated instance is NOT proof of filesystem protection or durability.
    """

    installation_id: str
    transaction_id: str
    capsule_identity_sha256: str
    target_identity_sha256: str
    active_receipt_bytes: bytes | None
    capsule_bytes: bytes | None
    proposal_sha256: str
    selection_sha256: str
    journal_sha256: str
    parent_directory_protected: bool
    active_receipt_protected_regular_file: bool
    capsule_absence_independently_confirmed: bool
    exclusive_service_fences_held: bool
    all_delete_operations_terminated: bool
    no_unaccounted_capsule_writer_in_flight: bool
    directory_durability_independently_checked: bool
    candidate_physical_bytes_reaudited: bool


class IndependentCapsuleDeleteReader(Protocol):
    def __call__(
        self,
        request: WitnessCommitRequest,
        context: object,
        /,
    ) -> IndependentCapsuleDeleteReadback: ...


@dataclass(frozen=True, slots=True)
class ProtectedCapsuleDeleteDispatchClaim:
    """Immutable one-shot service record; never a permission for retry."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    predelete_marker_sha256: str
    clearance_preflight_sha256: str
    recovery_capsule_sha256: str
    capsule_identity_sha256: str
    target_identity_sha256: str
    independent_fence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


@dataclass(frozen=True, slots=True)
class ProtectedCapsuleDeleteObservation:
    """Diagnostic only: no launcher readiness, rollback or deletion authority."""

    installation_id: str
    transaction_id: str
    successor_sha256: str
    status: str = _POST_ABSENT
    authority: str = _AUTH


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _marker_hash(value: ProtectedCapsulePredeleteUncertainty) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(value, f.name) for f in fields(value)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_marker(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    convergence: ProtectedLocalConvergenceRecord,
    preflight: ProtectedCapsuleClearancePreflight,
) -> bool:
    if not isinstance(item, ProtectedCapsulePredeleteUncertainty):
        return False
    for f in fields(item):
        value = getattr(item, f.name)
        exp = int if f.name in ("successor_generation", "witness_revision") else str
        if type(value) is not exp:
            return False
        if f.name.endswith("_sha256") and (
            not isinstance(value, str) or _SHA.fullmatch(value) is None
        ):
            return False
    return (
        item.status == _ARMED
        and item.authority == _ARMED_AUTH
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.clearance_preflight_sha256 == _preflight_hash(preflight)
        and item.convergence_record_sha256 == preflight.convergence_record_sha256
        and item.recovery_capsule_sha256 == reservation.recovery_capsule_sha256
        and item.capsule_identity_sha256 == preflight.capsule_identity_sha256
        and item.target_identity_sha256 == intent.target_identity_sha256
        and item.independent_fence_sha256
        == convergence.independently_fenced_evidence_sha256
    )


def _exact_postdelete(
    sample: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    preflight: ProtectedCapsuleClearancePreflight,
) -> bool:
    if not isinstance(sample, IndependentCapsuleDeleteReadback):
        return False
    for f in fields(sample):
        value = getattr(sample, f.name)
        if f.name in ("active_receipt_bytes", "capsule_bytes"):
            if value is not None and (type(value) is not bytes or len(value) > 81920):
                return False
        elif f.name in (
            "parent_directory_protected",
            "active_receipt_protected_regular_file",
            "capsule_absence_independently_confirmed",
            "exclusive_service_fences_held",
            "all_delete_operations_terminated",
            "no_unaccounted_capsule_writer_in_flight",
            "directory_durability_independently_checked",
            "candidate_physical_bytes_reaudited",
        ):
            if type(value) is not bool or value is not True:
                return False
        elif type(value) is not str:
            return False
    return (
        sample.installation_id == request.installation_id
        and sample.transaction_id == reservation.transaction_id
        and sample.capsule_identity_sha256 == preflight.capsule_identity_sha256
        and sample.target_identity_sha256 == intent.target_identity_sha256
        and sample.active_receipt_bytes == request.successor_receipt_bytes
        and sample.capsule_bytes is None
        and sample.proposal_sha256 == intent.proposal_sha256
        and sample.selection_sha256 == intent.selection_sha256
        and sample.journal_sha256 == intent.journal_sha256
    )


class ProtectedCapsuleDeleteDispatcher:
    """One-shot protected claim before exactly one independent delete call."""

    def __init__(self, predelete: ProtectedCapsulePredeleteUncertaintyLedger) -> None:
        if (
            not isinstance(predelete, ProtectedCapsulePredeleteUncertaintyLedger)
            or not isinstance(predelete._db, sqlite3.Connection)
            or predelete._db is not predelete._clearance._db
            or predelete._db is not predelete._clearance._convergence._db
            or predelete._db.in_transaction
        ):
            raise CapsuleDeleteDispatchError(
                "exact protected deletion database required"
            )
        self._predelete = predelete
        self._db = predelete._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise CapsuleDeleteDispatchError(
                "protected delete claim table unavailable"
            ) from error

    def _authorize(self, install: str, operation: str, context: object) -> None:
        try:
            self._predelete._authorize(install, operation, context)
        except CapsulePredeleteUncertaintyError as error:
            raise CapsuleDeleteDispatchError(
                "independent capsule delete authorization refused"
            ) from error

    def observe(
        self,
        installation_id: str,
        *,
        service_context: object,
    ) -> ProtectedCapsuleDeleteDispatchClaim | None:
        """Read-only durable claim inspection, never a redispatch method."""
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise CapsuleDeleteDispatchError("invalid installation identity")
        self._authorize(
            installation_id, "observe_capsule_delete_claim", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_capsule_delete_dispatch_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise CapsuleDeleteDispatchError(
                "protected capsule claim unreadable"
            ) from error
        if row is None:
            return None
        try:
            item = ProtectedCapsuleDeleteDispatchClaim(*row)
        except (TypeError, ValueError) as error:
            raise CapsuleDeleteDispatchError(
                "invalid protected capsule claim"
            ) from error
        if (
            item.installation_id != installation_id
            or type(item.transaction_id) is not str
            or _TX.fullmatch(item.transaction_id) is None
            or type(item.successor_generation) is not int
            or not 1 <= item.successor_generation <= 2**53 - 1
            or type(item.witness_revision) is not int
            or not 1 <= item.witness_revision <= 2**53 - 1
            or any(
                type(getattr(item, f.name)) is not str
                or _SHA.fullmatch(getattr(item, f.name)) is None
                for f in fields(item)
                if f.name.endswith("_sha256")
            )
            or item.status != _STATUS
            or item.authority != _AUTH
        ):
            raise CapsuleDeleteDispatchError("protected capsule claim corrupt")
        return item

    def dispatch_once(
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
        predelete_marker: ProtectedCapsulePredeleteUncertainty,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
        independently_read_capsule: IndependentCapsuleReader,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
        service_owned_delete: IndependentCapsuleFileDeleter,
    ) -> ProtectedCapsuleDeleteObservation:
        """Durably claim once, then delete via protected service exactly once.

        A successful return indicates only independent *sampled* absence.
        A crash or lost ACK may leave either state; NEVER auto-dispatch again.
        """
        convergence_api = self._predelete._clearance._convergence
        try:
            request = convergence_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise CapsuleDeleteDispatchError(
                "noncanonical protected deletion basis"
            ) from error
        if not (
            _exact_preflight(
                clearance_preflight, request, reservation, intent, convergence
            )
            and _exact_marker(
                predelete_marker,
                request,
                reservation,
                intent,
                convergence,
                clearance_preflight,
            )
        ):
            raise CapsuleDeleteDispatchError("noncanonical predelete marker/preflight")
        try:
            convergence_api._prepare_runtime(
                request,
                reservation,
                service_context=service_context,
                independently_read_evidence=independently_read_evidence,
                independently_read_local_receipt=independently_read_local_receipt,
                independently_confirm_quiescence=independently_confirm_quiescence,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                operation="dispatch_capsule_delete_once",
            )
        except LocalConvergenceError as error:
            raise CapsuleDeleteDispatchError(
                "independent delete inputs refused"
            ) from error
        if (
            not callable(independently_read_capsule)
            or not callable(independently_read_postdelete)
            or not callable(service_owned_delete)
        ):
            raise CapsuleDeleteDispatchError(
                "protected service delete adapters missing"
            )
        result = ProtectedCapsuleDeleteDispatchClaim(
            request.installation_id,
            reservation.transaction_id,
            reservation.request_sha256,
            request.successor_sha256,
            reservation.successor_generation,
            reservation.witness_revision,
            _marker_hash(predelete_marker),
            _preflight_hash(clearance_preflight),
            reservation.recovery_capsule_sha256,
            clearance_preflight.capsule_identity_sha256,
            intent.target_identity_sha256,
            clearance_preflight.independent_fence_sha256,
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                convergence_api._read_under_service_lock(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    marker,
                    claim,
                    service_context=service_context,
                )
                actual = (
                    convergence_api.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                )
                if any(
                    type(a) is not type(b) or a != b
                    for a, b in zip(
                        actual, (convergence, clearance_preflight, predelete_marker)
                    )
                ):
                    raise CapsuleDeleteDispatchError(
                        "protected deletion records drifted"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_capsule_delete_dispatch_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise CapsuleDeleteDispatchError(
                        "delete already claimed; no repeat or automatic retry"
                    )
                try:
                    first_capsule = independently_read_capsule(request, service_context)
                    quiet, state, observed = convergence_api._sample(
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
                except Exception as error:
                    raise CapsuleDeleteDispatchError(
                        "independent capsule or receipt "
                        "predelete inspection unavailable"
                    ) from error
                if (
                    not _exact_capsule(
                        first_capsule,
                        request,
                        reservation,
                        clearance_preflight.capsule_identity_sha256,
                    )
                    or state != _SUCCESSOR
                    or observed != request.successor_sha256
                    or not _quiescent(quiet, request, claim)
                    or _sha(
                        bytes.fromhex(quiet.writer_fence_sha256)
                        + bytes.fromhex(quiet.termination_evidence_sha256)
                    )
                    != predelete_marker.independent_fence_sha256
                ):
                    raise CapsuleDeleteDispatchError(
                        "capsule, local receipt or exclusive writer fence changed"
                    )
                convergence_api._dispatch._prewrite._signed(
                    request, reservation, witness_transport, pinned_public_key, now
                )
                try:
                    second_capsule = independently_read_capsule(
                        request, service_context
                    )
                    quiet2, state2, observed2 = convergence_api._sample(
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
                except Exception as error:
                    raise CapsuleDeleteDispatchError(
                        "final predelete physical inspection unavailable"
                    ) from error
                if (
                    second_capsule != first_capsule
                    or not _exact_capsule(
                        second_capsule,
                        request,
                        reservation,
                        clearance_preflight.capsule_identity_sha256,
                    )
                    or quiet2 != quiet
                    or state2 != _SUCCESSOR
                    or observed2 != observed
                ):
                    raise CapsuleDeleteDispatchError(
                        "capsule or physical evidence drifted before deletion"
                    )
                self._db.execute(
                    "INSERT INTO plan_capsule_delete_dispatch_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.predelete_marker_sha256,
                        result.clearance_preflight_sha256,
                        result.recovery_capsule_sha256,
                        result.capsule_identity_sha256,
                        result.target_identity_sha256,
                        result.independent_fence_sha256,
                        result.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except CapsuleDeleteDispatchError:
            raise
        except (
            sqlite3.Error,
            CapsulePredeleteUncertaintyError,
            LocalConvergenceError,
        ) as error:
            raise CapsuleDeleteDispatchError(
                "delete claim COMMIT may be uncertain; inspect only"
            ) from error
        # The durable claim exists BEFORE the one and only external delete call.
        # A failed callback, post-readback, lost ACK, crash, or even a remaining
        # capsule must never trigger another dispatch from this installation.
        try:
            service_owned_delete(
                request, clearance_preflight.capsule_identity_sha256, service_context
            )
        except Exception as error:
            raise CapsuleDeleteDispatchError(
                "capsule deletion outcome uncertain; no redispatch"
            ) from error
        try:
            after = independently_read_postdelete(request, service_context)
            convergence_api._dispatch._prewrite._signed(
                request, reservation, witness_transport, pinned_public_key, now
            )
        except Exception as error:
            raise CapsuleDeleteDispatchError(
                "postdelete verification unavailable; no redispatch"
            ) from error
        if not _exact_postdelete(
            after, request, reservation, intent, clearance_preflight
        ):
            raise CapsuleDeleteDispatchError(
                "postdelete bytes/absence/fence not verified; reconcile without retry"
            )
        return ProtectedCapsuleDeleteObservation(
            request.installation_id,
            reservation.transaction_id,
            request.successor_sha256,
        )


__all__ = (
    "CapsuleDeleteDispatchError",
    "IndependentCapsuleDeleteReadback",
    "IndependentCapsuleDeleteReader",
    "IndependentCapsuleFileDeleter",
    "ProtectedCapsuleDeleteDispatchClaim",
    "ProtectedCapsuleDeleteDispatcher",
    "ProtectedCapsuleDeleteObservation",
)
