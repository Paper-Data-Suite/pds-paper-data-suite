"""Issue #49 Slice 75: service-owned one-shot plan dispatch and signed recovery.

Dispatch is possible ONLY for an already admitted Slice-74 successor and uses
Slice-45 writer gate -> Slice-44 durable attempt fence -> Slice-42 witness CAS.
A successful service return is NOT a signed confirmation or launch authority.
An exception after the writer's preclaim is indeterminate and never retried.

A separate operation closes admission, obtains independently asserted global
writer quiescence, and reads a fresh signed witness head. No rollback, package
mutation, active-receipt publication, HTTP writer or teacher CLI is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final

from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_service_admission import (
    IndependentPlanPredecessorReader,
    PlanSuccessorServiceAdmission,
    PlanSuccessorServiceAdmissionError,
    _approved,
    _proposal,
    _service_predecessor,
)
from paper_data_suite.evergreen_plan_successor_draft import PlanSuccessorDraftReview
from paper_data_suite.evergreen_witness_cas_fence import (
    WitnessCasFenceError,
    WitnessCasFenceLedger,
    WitnessCasFenceState,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    IndependentCommitApproval,
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    inspect_uncertain_witness_commit,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    IndependentWriterSupervisor,
    WitnessWriterQuiescenceError,
    WitnessWriterQuiescenceGate,
    WitnessWriterQuiescenceState,
)

_PREPARED: Final = "PREPARED_NO_DISPATCH"
_ADMITTED: Final = "ADMITTED_NOT_DISPATCHED"
_MAY_SEND: Final = "CAS_MAY_BE_IN_FLIGHT"
_SENT: Final = "CAS_MAY_HAVE_BEEN_DISPATCHED"
_STOPPING_SENT: Final = "STOP_REQUESTED_MAY_BE_IN_FLIGHT"
_STOPPED_PRIOR: Final = "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"
_STOPPED_NEXT: Final = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
_SIGNED_PRIOR: Final = "PRIOR_SIGNED_STILL_UNRESOLVED"
_SIGNED_NEXT: Final = "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"
_NO_AUTHORITY: Final = "NO_RETRY_ROLLBACK_ACTIVATION_RECEIPT_PUBLICATION_OR_LAUNCH"


class PlanSuccessorServiceDispatchError(ValueError):
    """Refused dispatch/reconciliation; preserve durable uncertain state."""


@dataclass(frozen=True, slots=True)
class PlanSuccessorServiceDispatch:
    """A one-time service CAS call returned; NOT authenticated confirmation."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    fence_status: str = _SENT
    writer_status: str = _MAY_SEND
    status: str = "SERVICE_CAS_RETURNED_SIGNED_READBACK_AND_RECOVERY_REQUIRED"
    authority: str = _NO_AUTHORITY


@dataclass(frozen=True, slots=True)
class PlanSuccessorServiceSignedRecovery:
    """Signed checkpoint observation plus service asserted writer shutdown."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    witness_revision: int
    signed_receipt_sha256: str
    fence_status: str
    writer_status: str
    status: str
    authority: str = _NO_AUTHORITY


def _exact_admitted_request(
    review: PlanSuccessorDraftReview,
    admission: PlanSuccessorServiceAdmission,
) -> tuple[WitnessCommitRequest, str, int]:
    """A client-supplied admission dataclass is NEVER an approval token."""
    try:
        request, prior_tx, prior_sha, prior_gen, successor_gen = _proposal(review)
    except PlanSuccessorServiceAdmissionError as error:
        raise PlanSuccessorServiceDispatchError(
            "invalid plan successor proposal"
        ) from error
    expected = PlanSuccessorServiceAdmission(
        request.installation_id,
        review.transaction_id,
        review.request_sha256,
        prior_sha,
        request.successor_sha256,
        prior_gen,
        successor_gen,
        request.expected_witness_revision,
    )
    if (
        not isinstance(admission, PlanSuccessorServiceAdmission)
        or admission != expected
        or any(
            type(getattr(admission, item.name))
            is not type(getattr(expected, item.name))
            for item in fields(PlanSuccessorServiceAdmission)
        )
    ):
        raise PlanSuccessorServiceDispatchError(
            "admission fields disagree with canonical request; no authority inferred"
        )
    return request, prior_tx, prior_gen


def _service_objects(
    ledger: WitnessCasFenceLedger,
    gate: WitnessWriterQuiescenceGate,
) -> None:
    if (
        not isinstance(ledger, WitnessCasFenceLedger)
        or not isinstance(gate, WitnessWriterQuiescenceGate)
        or gate._ledger is not ledger
        or gate._db is not ledger._db
    ):
        raise PlanSuccessorServiceDispatchError(
            "same independently administered ledger and gate required"
        )


def _states(
    request: WitnessCommitRequest,
    *,
    ledger: WitnessCasFenceLedger,
    gate: WitnessWriterQuiescenceGate,
    service_context: object,
) -> tuple[WitnessCasFenceState, WitnessWriterQuiescenceState]:
    try:
        fence = ledger.observe(request, service_context=service_context)
        writer = gate.observe(request, service_context=service_context)
    except (WitnessCasFenceError, WitnessWriterQuiescenceError) as error:
        raise PlanSuccessorServiceDispatchError(
            "independent service admission state unavailable"
        ) from error
    if (
        not isinstance(fence, WitnessCasFenceState)
        or not isinstance(writer, WitnessWriterQuiescenceState)
        or fence.installation_id != request.installation_id
        or writer.installation_id != request.installation_id
        or fence.request_sha256 != writer.request_sha256
        or fence.predecessor_sha256 != request.predecessor_sha256
        or fence.successor_sha256 != request.successor_sha256
        or fence.expected_witness_revision != request.expected_witness_revision
        or writer.authority != "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
        or fence.authority != "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
    ):
        raise PlanSuccessorServiceDispatchError(
            "service state disagrees with exact admitted request"
        )
    return fence, writer


def _readback_inputs(
    *,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
) -> None:
    if (
        not callable(witness_transport)
        or type(pinned_public_key) is not bytes
        or len(pinned_public_key) != 32
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise PlanSuccessorServiceDispatchError(
            "independently provisioned signed witness inputs required"
        )


def dispatch_admitted_plan_successor_once(
    review: PlanSuccessorDraftReview,
    admission: PlanSuccessorServiceAdmission,
    *,
    service_context: object,
    independently_read_predecessor: IndependentPlanPredecessorReader,
    independently_approve: IndependentCommitApproval,
    ledger: WitnessCasFenceLedger,
    gate: WitnessWriterQuiescenceGate,
    store: MonotonicCheckpointStore,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
) -> PlanSuccessorServiceDispatch:
    """One CAS attempt, only after service approval and durable prior admission.

    Must be called by the separately administered service, not a local Suite
    client. The service owns the checkpoint store, protected signing material,
    mTLS identity, exclusive writer, physical acceptance and operator consent.
    A service callback passed from a classroom process is NOT independent.
    """
    _service_objects(ledger, gate)
    request, prior_tx, prior_gen = _exact_admitted_request(review, admission)
    if (
        not callable(independently_read_predecessor)
        or not callable(independently_approve)
        or not isinstance(store, MonotonicCheckpointStore)
    ):
        raise PlanSuccessorServiceDispatchError("independent dispatch inputs missing")
    _readback_inputs(
        witness_transport=witness_transport,
        pinned_public_key=pinned_public_key,
        now=now,
    )
    before_fence, before_writer = _states(
        request, ledger=ledger, gate=gate, service_context=service_context
    )
    if (
        before_fence.status != _PREPARED
        or before_writer.status != _ADMITTED
        or before_fence.witnessed_revision is not None
        or before_fence.witnessed_receipt_sha256 is not None
        or before_writer.signed_revision is not None
        or before_writer.signed_head_sha256 is not None
    ):
        raise PlanSuccessorServiceDispatchError(
            "CAS not precisely prepared and admitted; replay/closure refused"
        )
    try:
        _service_predecessor(
            request,
            prior_transaction_id=prior_tx,
            previous_sha256=request.predecessor_sha256,
            previous_generation=prior_gen,
            service_context=service_context,
            independently_read_predecessor=independently_read_predecessor,
        )
        _approved(
            request,
            service_context=service_context,
            independently_approve=independently_approve,
        )
    except PlanSuccessorServiceAdmissionError as error:
        raise PlanSuccessorServiceDispatchError(
            "renewed service predecessor/deployment approval refused"
        ) from error
    # Once gate.dispatch_once starts, the durable gate marker is committed
    # BEFORE the fence preclaim and BEFORE actual witness CAS. No exception
    # from this boundary authorizes a retry or cleanup.
    try:
        gate.dispatch_once(
            request,
            service_context=service_context,
            store=store,
            independently_approve=independently_approve,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
        )
    except Exception as error:
        raise PlanSuccessorServiceDispatchError(
            "CAS attempt may have been dispatched; no retry, stop writers and reconcile"
        ) from error
    after_fence, after_writer = _states(
        request, ledger=ledger, gate=gate, service_context=service_context
    )
    if after_fence.status != _SENT or after_writer.status != _MAY_SEND:
        raise PlanSuccessorServiceDispatchError(
            "CAS returned but durable status differs; stop writers and reconcile"
        )
    return PlanSuccessorServiceDispatch(
        request.installation_id, review.transaction_id, after_fence.request_sha256
    )


def reconcile_admitted_plan_successor_signed_head(
    review: PlanSuccessorDraftReview,
    admission: PlanSuccessorServiceAdmission,
    *,
    service_context: object,
    ledger: WitnessCasFenceLedger,
    gate: WitnessWriterQuiescenceGate,
    independently_verify_stopped: IndependentWriterSupervisor,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
) -> PlanSuccessorServiceSignedRecovery:
    """Close writer admission, independently stop/join writers, read signed head.

    A signed prior head after stopped-writer certification still does NOT
    authorize rollback. A signed successor requires forward-only recovery.
    Neither case releases the fence, publishes a receipt or permits launch.
    """
    _service_objects(ledger, gate)
    request, _, _ = _exact_admitted_request(review, admission)
    if not callable(independently_verify_stopped):
        raise PlanSuccessorServiceDispatchError("independent writer supervisor missing")
    _readback_inputs(
        witness_transport=witness_transport,
        pinned_public_key=pinned_public_key,
        now=now,
    )
    fence, writer = _states(
        request, ledger=ledger, gate=gate, service_context=service_context
    )
    if fence.status not in (_PREPARED, _SENT, _SIGNED_PRIOR, _SIGNED_NEXT):
        raise PlanSuccessorServiceDispatchError(
            "no valid durable CAS fence for this request"
        )
    if writer.status in (_MAY_SEND, _STOPPING_SENT):
        try:
            stopped = gate.request_stop(request, service_context=service_context)
            if stopped.status != _STOPPING_SENT:
                raise PlanSuccessorServiceDispatchError(
                    "writer stop did not preserve possible-dispatch uncertainty"
                )
            certified = gate.certify_stopped_and_observe(
                request,
                service_context=service_context,
                independently_verify_stopped=independently_verify_stopped,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
            )
        except WitnessWriterQuiescenceError as error:
            raise PlanSuccessorServiceDispatchError(
                "writers not certified stopped or signed head unknown; keep fence"
            ) from error
    elif writer.status in (_STOPPED_PRIOR, _STOPPED_NEXT):
        # Safe read-only continuation after a crash between terminal gate
        # certification and independent ledger signed readback. Reestablish
        # global writer shutdown and verify a NEW signed head; never dispatch.
        try:
            still_stopped = independently_verify_stopped(
                request.installation_id, writer.request_sha256, service_context
            )
        except Exception as error:
            raise PlanSuccessorServiceDispatchError(
                "independent writer shutdown re-verification unavailable"
            ) from error
        if still_stopped is not True:
            raise PlanSuccessorServiceDispatchError(
                "writer may have restarted; no signed reconciliation grant"
            )
        try:
            signed = inspect_uncertain_witness_commit(
                request,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                minimum_witness_revision=request.expected_witness_revision,
            )
        except WitnessCommitProtocolError as error:
            raise PlanSuccessorServiceDispatchError(
                "fresh signed head unavailable; gate remains terminal"
            ) from error
        if (
            signed.witness_revision != writer.signed_revision
            or signed.receipt_sha256 != writer.signed_head_sha256
        ):
            raise PlanSuccessorServiceDispatchError(
                "new signed head conflicts with durable stopped-writer certification"
            )
        certified = writer
    else:
        raise PlanSuccessorServiceDispatchError(
            "no possible CAS dispatch or writer not certified stopped"
        )
    if certified.status == _STOPPED_NEXT:
        expected_status = _SIGNED_NEXT
        status = "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"
        expected_revision = request.expected_witness_revision + 1
        expected_hash = request.successor_sha256
    elif certified.status == _STOPPED_PRIOR:
        expected_status = _SIGNED_PRIOR
        status = "SIGNED_PRIOR_UNRESOLVED_NO_ROLLBACK_GRANT"
        expected_revision = request.expected_witness_revision
        expected_hash = request.predecessor_sha256
    else:
        raise PlanSuccessorServiceDispatchError(
            "unknown certified writer state; preserve durable records"
        )
    if (
        certified.signed_revision != expected_revision
        or certified.signed_head_sha256 != expected_hash
    ):
        raise PlanSuccessorServiceDispatchError(
            "certified signed head disagrees with request; preserve recovery"
        )
    # A gate preclaim can precede the ledger's possible-dispatch marker. In
    # that crash window the ledger stays PREPARED; never invent a dispatch.
    # If fence recorded a possible dispatch, obtain its independent signed
    # observation as well; disagreement fails closed rather than clearing it.
    try:
        observed_fence = ledger.observe(request, service_context=service_context)
        if observed_fence is None:
            raise PlanSuccessorServiceDispatchError("lost durable CAS fence")
        if observed_fence.status != _PREPARED:
            observed_fence = ledger.inspect_signed_head(
                request,
                service_context=service_context,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
            )
    except WitnessCasFenceError as error:
        raise PlanSuccessorServiceDispatchError(
            "service CAS fence signed readback failed; keep uncertain state"
        ) from error
    if (
        observed_fence.status not in (_PREPARED, expected_status)
        or (observed_fence.status == _PREPARED and fence.status != _PREPARED)
        or (
            observed_fence.status == expected_status
            and (
                observed_fence.witnessed_revision != certified.signed_revision
                or observed_fence.witnessed_receipt_sha256
                != certified.signed_head_sha256
            )
        )
    ):
        raise PlanSuccessorServiceDispatchError(
            "signed service gate/fence observations disagree; no recovery grant"
        )
    final_writer = gate.observe(request, service_context=service_context)
    if final_writer != certified:
        raise PlanSuccessorServiceDispatchError(
            "writer certification changed during recovery readback"
        )
    return PlanSuccessorServiceSignedRecovery(
        request.installation_id,
        review.transaction_id,
        admission.request_sha256,
        expected_revision,
        expected_hash,
        observed_fence.status,
        certified.status,
        status,
    )


__all__ = (
    "PlanSuccessorServiceDispatch",
    "PlanSuccessorServiceDispatchError",
    "PlanSuccessorServiceSignedRecovery",
    "dispatch_admitted_plan_successor_once",
    "reconcile_admitted_plan_successor_signed_head",
)
