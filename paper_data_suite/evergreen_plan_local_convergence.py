"""Issue #49 Slice 84: protected post-dispatch inspection and convergence.

Never redispatch a local receipt writer after a Slice-83 dispatch claim. Independently
fence and classify local bytes after an uncertain outcome; only an exact successor,
with repeated fresh no-inflight/physical observations and a signed witness head,
may be recorded once in the protected service database. This is NOT installation
activation, pending capsule clearance, slot switching, rollback, or launch.

Independence, OS writer fencing, caller identity, durable filesystem provenance
and anti-replay are deployment obligations, NOT properties of Python callbacks.
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
    LocalDeploymentIntentError,
    ProtectedLocalDeploymentIntent,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    IndependentLocalReceiptReadback,
    IndependentLocalReceiptReader,
    LocalPrewriteUncertaintyError,
    ProtectedLocalPrewriteUncertainty,
    _readback_matches,
)
from paper_data_suite.evergreen_plan_local_receipt_dispatch import (
    LocalReceiptDispatchError,
    ProtectedLocalReceiptDispatchClaim,
    ProtectedLocalReceiptDispatcher,
    _exact_marker,
    _marker_hash,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedPlanReceiptError,
    ProtectedServiceReceiptRecord,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    PlanPublicationPreclaimError,
    ProtectedPublicationPreclaim,
    _fresh_basis_matches,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_DISPATCH_STATUS: Final = "LOCAL_RECEIPT_DISPATCH_CLAIMED_WRITE_OUTCOME_UNCERTAIN"
_DISPATCH_AUTH: Final = "NO_REDISPATCH_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_STATUS: Final = "LOCAL_RECEIPT_CONVERGENCE_RECORDED_CAPSULE_RETAINED"
_AUTHORITY: Final = "NO_RETRY_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS_AUTHORITY"
_PREDECESSOR: Final = "PREDECESSOR_VISIBLE_NO_RETRY_AUTHORITY"
_SUCCESSOR: Final = "SUCCESSOR_VISIBLE_CONVERGENCE_NOT_YET_AUTHORIZED"
_MISSING: Final = "ACTIVE_RECEIPT_MISSING_MANUAL_RECOVERY_REQUIRED"
_UNKNOWN: Final = "UNKNOWN_ACTIVE_RECEIPT_QUARANTINE_REQUIRED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_local_convergence_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    dispatch_claim_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    independently_fenced_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LOCAL_RECEIPT_CONVERGENCE_RECORDED_CAPSULE_RETAINED'
    )
)
"""


class LocalConvergenceError(ValueError):
    """Refuse untrusted or inconclusive recovery after a one-shot dispatch."""


@dataclass(frozen=True, slots=True)
class IndependentNoInflightEvidence:
    """Service-only observation, never proved by the dataclass itself.

    The independently administered service must know the true OS writer-set,
    retain an exclusive lock, and ensure an in-flight write cannot start later.
    Any uncertain writer ownership or outstanding operation must refuse.
    """

    installation_id: str
    transaction_id: str
    dispatch_claim_sha256: str
    target_identity_sha256: str
    writer_fence_sha256: str
    termination_evidence_sha256: str
    all_prior_writer_operations_terminated: bool
    exclusive_os_fence_held: bool
    no_unaccounted_writer_in_flight: bool
    local_target_durability_independently_checked: bool
    candidate_physical_bytes_independently_reaudited: bool


class IndependentNoInflightReader(Protocol):
    """Independently provisioned service operator, not a client supplied oracle."""

    def __call__(
        self, request: WitnessCommitRequest, context: object, /
    ) -> IndependentNoInflightEvidence: ...


@dataclass(frozen=True, slots=True)
class PostDispatchRecoveryObservation:
    """Ephemeral read-only classification; no publication or recovery authority."""

    installation_id: str
    transaction_id: str
    observed_receipt_sha256: str | None
    dispatch_claim_sha256: str
    witness_revision: int
    status: str
    authority: str = _AUTHORITY


@dataclass(frozen=True, slots=True)
class ProtectedLocalConvergenceRecord:
    """Service-side terminal observation, not a local launch readiness token."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    dispatch_claim_sha256: str
    target_identity_sha256: str
    recovery_capsule_sha256: str
    independently_fenced_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _claim_hash(item: ProtectedLocalReceiptDispatchClaim) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(item, f.name) for f in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _claim_matches(
    claim: ProtectedLocalReceiptDispatchClaim,
    marker: ProtectedLocalPrewriteUncertainty,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    request: WitnessCommitRequest,
) -> bool:
    if not isinstance(claim, ProtectedLocalReceiptDispatchClaim):
        return False
    for f in fields(claim):
        value = getattr(claim, f.name)
        if type(value) is not str:
            return False
        if f.name.endswith("_sha256") and _SHA.fullmatch(value) is None:
            return False
    return (
        claim.status == _DISPATCH_STATUS
        and claim.authority == _DISPATCH_AUTH
        and claim.installation_id == request.installation_id
        and claim.transaction_id == reservation.transaction_id
        and claim.request_sha256 == reservation.request_sha256
        and claim.successor_sha256 == request.successor_sha256
        and claim.predecessor_receipt_sha256 == request.predecessor_sha256
        and claim.target_identity_sha256 == intent.target_identity_sha256
        and claim.prewrite_marker_sha256 == _marker_hash(marker)
        and claim.recovery_capsule_sha256 == intent.recovery_capsule_sha256
    )


def _quiescent(
    evidence: object,
    request: WitnessCommitRequest,
    claim: ProtectedLocalReceiptDispatchClaim,
) -> bool:
    if not isinstance(evidence, IndependentNoInflightEvidence):
        return False
    for f in fields(evidence):
        value = getattr(evidence, f.name)
        if f.name in (
            "all_prior_writer_operations_terminated",
            "exclusive_os_fence_held",
            "no_unaccounted_writer_in_flight",
            "local_target_durability_independently_checked",
            "candidate_physical_bytes_independently_reaudited",
        ):
            if type(value) is not bool or value is not True:
                return False
        elif type(value) is not str:
            return False
    return (
        evidence.installation_id == request.installation_id
        and evidence.transaction_id == claim.transaction_id
        and evidence.dispatch_claim_sha256 == _claim_hash(claim)
        and evidence.target_identity_sha256 == claim.target_identity_sha256
        and _SHA.fullmatch(evidence.writer_fence_sha256) is not None
        and _SHA.fullmatch(evidence.termination_evidence_sha256) is not None
    )


def _classify(
    request: WitnessCommitRequest, physical: IndependentLocalReceiptReadback
) -> tuple[str, str | None]:
    raw = physical.active_receipt_bytes
    if raw is None:
        return _MISSING, None
    if raw == request.successor_receipt_bytes:
        return _SUCCESSOR, request.successor_sha256
    if raw == request.previous_receipt_bytes:
        return _PREDECESSOR, request.predecessor_sha256
    return _UNKNOWN, _sha(raw)


class ProtectedLocalConvergenceCoordinator:
    """Read-only classify or one-shot record, on the same service-owned SQLite."""

    def __init__(self, dispatcher: ProtectedLocalReceiptDispatcher) -> None:
        if (
            not isinstance(dispatcher, ProtectedLocalReceiptDispatcher)
            or not isinstance(dispatcher._db, sqlite3.Connection)
            or dispatcher._db is not dispatcher._prewrite._db
            or dispatcher._db is not dispatcher._prewrite._planner._db
            or dispatcher._db.in_transaction
        ):
            raise LocalConvergenceError("exact protected dispatch database required")
        self._dispatch = dispatcher
        self._db = dispatcher._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LocalConvergenceError("convergence table unavailable") from error

    def _authorize(self, installation_id: str, op: str, context: object) -> None:
        try:
            self._dispatch._authorize(installation_id, op, context)
        except LocalReceiptDispatchError as error:
            raise LocalConvergenceError(
                "independent convergence authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLocalConvergenceRecord | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LocalConvergenceError("invalid installation identity")
        self._authorize(installation_id, "observe_local_convergence", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_local_convergence_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LocalConvergenceError("convergence record unavailable") from error
        if row is None:
            return None
        try:
            result = ProtectedLocalConvergenceRecord(*row)
        except (ValueError, TypeError) as error:
            raise LocalConvergenceError("convergence record malformed") from error
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
            raise LocalConvergenceError("durable convergence record corrupt")
        return result

    def _basis(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
    ) -> WitnessCommitRequest:
        try:
            request = self._dispatch._prewrite._basis(
                request_bytes, reservation, preclaim, record, intent
            )
        except LocalPrewriteUncertaintyError as error:
            raise LocalConvergenceError(
                "noncanonical protected convergence basis"
            ) from error
        if not _exact_marker(
            marker, reservation, record, intent, request
        ) or not _claim_matches(claim, marker, reservation, intent, request):
            raise LocalConvergenceError("invalid or forged dispatch/prewrite basis")
        return request

    def _sample(
        self,
        request: WitnessCommitRequest,
        reservation: ProtectedFinalizationReservation,
        intent: ProtectedLocalDeploymentIntent,
        claim: ProtectedLocalReceiptDispatchClaim,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
    ) -> tuple[IndependentNoInflightEvidence, str, str | None]:
        try:
            evidence = independently_read_evidence(request, service_context)
            quiet = independently_confirm_quiescence(request, service_context)
            physical = independently_read_local_receipt(request, service_context)
        except Exception as error:
            raise LocalConvergenceError(
                "independent writer or physical inspection unavailable"
            ) from error
        if (
            not _fresh_basis_matches(evidence, reservation)
            or not _quiescent(quiet, request, claim)
            or not _readback_matches(physical, request, reservation, intent)
        ):
            raise LocalConvergenceError(
                "writer still in flight, fence/physical bytes or capsule changed"
            )
        assert isinstance(quiet, IndependentNoInflightEvidence)
        assert isinstance(physical, IndependentLocalReceiptReadback)
        status, sha = _classify(request, physical)
        return quiet, status, sha

    def _read_under_service_lock(
        self,
        request: WitnessCommitRequest,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        *,
        service_context: object,
    ) -> None:
        self._dispatch._prewrite._durable_basis(
            request,
            reservation,
            preclaim,
            record,
            intent,
            service_context=service_context,
        )
        actual_marker = self._dispatch._prewrite.observe(
            request.installation_id, service_context=service_context
        )
        actual_claim = self._dispatch.observe(
            request.installation_id, service_context=service_context
        )
        if (
            type(actual_marker) is not type(marker)
            or actual_marker != marker
            or type(actual_claim) is not type(claim)
            or actual_claim != claim
        ):
            raise LocalConvergenceError("protected prewrite or dispatch claim drifted")

    def _prepare_runtime(
        self,
        request: WitnessCommitRequest,
        reservation: ProtectedFinalizationReservation,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
        operation: str,
    ) -> None:
        self._dispatch._prewrite._validate_runtime(
            independently_read_evidence=independently_read_evidence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
        )
        if (
            not callable(independently_read_local_receipt)
            or not callable(independently_confirm_quiescence)
            or self._db.in_transaction
        ):
            raise LocalConvergenceError("protected convergence inputs unavailable")
        self._authorize(request.installation_id, operation, service_context)

    def _run(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
        certify: bool,
    ) -> PostDispatchRecoveryObservation | ProtectedLocalConvergenceRecord:
        request = self._basis(
            request_bytes, reservation, preclaim, record, intent, marker, claim
        )
        self._prepare_runtime(
            request,
            reservation,
            service_context=service_context,
            independently_read_evidence=independently_read_evidence,
            independently_read_local_receipt=independently_read_local_receipt,
            independently_confirm_quiescence=independently_confirm_quiescence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            operation=(
                "certify_local_convergence_once"
                if certify
                else "inspect_post_dispatch_recovery"
            ),
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._read_under_service_lock(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    marker,
                    claim,
                    service_context=service_context,
                )
                if (
                    certify
                    and self._db.execute(
                        "SELECT 1 FROM plan_local_convergence_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LocalConvergenceError(
                        "convergence already certified; no repeat or retry"
                    )
                first, status, observed_sha = self._sample(
                    request,
                    reservation,
                    intent,
                    claim,
                    service_context=service_context,
                    independently_read_evidence=independently_read_evidence,
                    independently_read_local_receipt=independently_read_local_receipt,
                    independently_confirm_quiescence=independently_confirm_quiescence,
                )
                self._dispatch._prewrite._signed(
                    request, reservation, witness_transport, pinned_public_key, now
                )
                if not certify:
                    self._db.execute("ROLLBACK")
                    return PostDispatchRecoveryObservation(
                        request.installation_id,
                        reservation.transaction_id,
                        observed_sha,
                        _claim_hash(claim),
                        reservation.witness_revision,
                        status,
                    )
                if status != _SUCCESSOR:
                    raise LocalConvergenceError(
                        "successor not present; no convergence/retry authority"
                    )
                second, second_status, second_sha = self._sample(
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
                    second != first
                    or second_status != _SUCCESSOR
                    or second_sha != observed_sha
                ):
                    raise LocalConvergenceError(
                        "post-witness writer state or successor readback drifted"
                    )
                result = ProtectedLocalConvergenceRecord(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _claim_hash(claim),
                    intent.target_identity_sha256,
                    intent.recovery_capsule_sha256,
                    _sha(
                        bytes.fromhex(first.writer_fence_sha256)
                        + bytes.fromhex(first.termination_evidence_sha256)
                    ),
                )
                self._db.execute(
                    "INSERT INTO plan_local_convergence_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.dispatch_claim_sha256,
                        result.target_identity_sha256,
                        result.recovery_capsule_sha256,
                        result.independently_fenced_evidence_sha256,
                        result.status,
                    ),
                )
                self._db.execute("COMMIT")
                return result
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LocalConvergenceError:
            raise
        except (
            sqlite3.Error,
            LocalReceiptDispatchError,
            LocalPrewriteUncertaintyError,
            PlanFinalizationFenceError,
            PlanPublicationPreclaimError,
            ProtectedPlanReceiptError,
            LocalDeploymentIntentError,
        ) as error:
            raise LocalConvergenceError(
                "convergence transaction uncertain; read-only inspection required"
            ) from error

    def inspect(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> PostDispatchRecoveryObservation:
        result = self._run(
            request_bytes,
            reservation,
            preclaim,
            record,
            intent,
            marker,
            claim,
            service_context=service_context,
            independently_read_evidence=independently_read_evidence,
            independently_read_local_receipt=independently_read_local_receipt,
            independently_confirm_quiescence=independently_confirm_quiescence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            certify=False,
        )
        assert isinstance(result, PostDispatchRecoveryObservation)
        return result

    def certify_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        independently_confirm_quiescence: IndependentNoInflightReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLocalConvergenceRecord:
        result = self._run(
            request_bytes,
            reservation,
            preclaim,
            record,
            intent,
            marker,
            claim,
            service_context=service_context,
            independently_read_evidence=independently_read_evidence,
            independently_read_local_receipt=independently_read_local_receipt,
            independently_confirm_quiescence=independently_confirm_quiescence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            certify=True,
        )
        assert isinstance(result, ProtectedLocalConvergenceRecord)
        return result


__all__ = (
    "IndependentNoInflightEvidence",
    "IndependentNoInflightReader",
    "LocalConvergenceError",
    "PostDispatchRecoveryObservation",
    "ProtectedLocalConvergenceCoordinator",
    "ProtectedLocalConvergenceRecord",
)
