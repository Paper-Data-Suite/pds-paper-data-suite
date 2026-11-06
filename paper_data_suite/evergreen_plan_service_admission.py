"""Issue #49 Slice 74: independently operated plan-successor CAS admission.

The input is a local Slice-73 proposal, never an approval credential. An
independently administered service must authenticate its actor, its pinned
predecessor and its physical-deployment/consent approval. This coordinator
reserves exactly one canonical request in the durable CAS fence and then
admits that request to the quiescent-writer gate. It NEVER dispatches CAS.

A failure after reservation leaves the durable record in place for explicit
service reconciliation. No CLI, launch, receipt publication, or local repair.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Protocol

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_plan_successor_draft import (
    PlanSuccessorDraftReview,
)
from paper_data_suite.evergreen_witness_cas_fence import (
    WitnessCasFenceError,
    WitnessCasFenceLedger,
    WitnessCasFenceState,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    IndependentCommitApproval,
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    parse_witness_commit_request,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceError,
    WitnessWriterQuiescenceGate,
    WitnessWriterQuiescenceState,
)

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_PROPOSED: Final = "UNSUBMITTED_SUCCESSOR_PROPOSAL_RECOVERY_CAPSULE_PENDING"
_NO_GRANT: Final = "NO_CAS_APPROVAL_RECEIPT_PUBLICATION_ROLLBACK_OR_LAUNCH"
_ADMITTED: Final = "ADMITTED_NOT_DISPATCHED"
_PREPARED: Final = "PREPARED_NO_DISPATCH"


class PlanSuccessorServiceAdmissionError(ValueError):
    """Service-side plan admission refused; any reservation stays fenced."""


@dataclass(frozen=True, slots=True)
class IndependentServicePredecessor:
    """Expected head from independently protected SERVICE state, not a draft.

    Only the independently provisioned predecessor reader may return one.
    The shape of this record does not authenticate its source by itself.
    """

    installation_id: str
    witness_id: str
    witness_revision: int
    transaction_id: str
    generation: int
    receipt_sha256: str


class IndependentPlanPredecessorReader(Protocol):
    """Fetch an independently pinned predecessor under authenticated context."""

    def __call__(
        self, request: WitnessCommitRequest, service_context: object, /
    ) -> IndependentServicePredecessor: ...


@dataclass(frozen=True, slots=True)
class PlanSuccessorServiceAdmission:
    """Durable, non-dispatching coordinator observation; never launch authority."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    predecessor_sha256: str
    successor_sha256: str
    predecessor_generation: int
    successor_generation: int
    expected_witness_revision: int
    fence_status: str = _PREPARED
    writer_status: str = _ADMITTED
    status: str = "SERVICE_APPROVED_PLAN_SUCCESSOR_ADMITTED_NO_CAS_DISPATCH"
    authority: str = "NO_CAS_DISPATCH_RECEIPT_PUBLICATION_RECOVERY_CLEAR_OR_LAUNCH"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _proposal(
    review: PlanSuccessorDraftReview,
) -> tuple[WitnessCommitRequest, str, str, int, int]:
    """Never treat locally supplied review metadata as independently verified."""
    if (
        not isinstance(review, PlanSuccessorDraftReview)
        or type(review.serialized_request) is not bytes
        or not 1 <= len(review.serialized_request) <= 48 * 1024
        or type(review.transaction_id) is not str
        or _TX.fullmatch(review.transaction_id) is None
        or type(review.installation_id) is not str
        or _TX.fullmatch(review.installation_id) is None
        or type(review.journal_revision) is not int
        or review.journal_revision != 2
        or type(review.predecessor_generation) is not int
        or type(review.proposed_generation) is not int
        or review.predecessor_generation < 1
        or review.proposed_generation != review.predecessor_generation + 1
        or type(review.witness_revision) is not int
        or review.witness_revision < 1
        or any(
            type(value) is not str or _SHA.fullmatch(value) is None
            for value in (
                review.previous_receipt_sha256,
                review.proposed_receipt_sha256,
                review.request_sha256,
            )
        )
        or review.status != _PROPOSED
        or review.authority != _NO_GRANT
        or review.request_sha256 != _sha(review.serialized_request)
    ):
        raise PlanSuccessorServiceAdmissionError(
            "untrusted plan review is not a canonical pending proposal"
        )
    try:
        request = parse_witness_commit_request(review.serialized_request)
        if serialize_witness_commit_request(request) != review.serialized_request:
            raise PlanSuccessorServiceAdmissionError("noncanonical witness request")
        prior = parse_untrusted_active_receipt(request.previous_receipt_bytes)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    except (WitnessCommitProtocolError, ActiveReceiptError) as error:
        raise PlanSuccessorServiceAdmissionError(
            "cannot independently parse canonical predecessor and successor"
        ) from error
    if (
        request.installation_id != review.installation_id
        or request.expected_witness_revision != review.witness_revision
        or prior.generation != review.predecessor_generation
        or successor.generation != review.proposed_generation
        or successor.transaction_id != review.transaction_id
        or request.predecessor_sha256 != review.previous_receipt_sha256
        or request.successor_sha256 != review.proposed_receipt_sha256
        or successor.previous_receipt_sha256 != request.predecessor_sha256
    ):
        raise PlanSuccessorServiceAdmissionError(
            "request bytes disagree with the unsigned plan review"
        )
    return (
        request,
        prior.transaction_id,
        request.predecessor_sha256,
        prior.generation,
        successor.generation,
    )


def _service_predecessor(
    request: WitnessCommitRequest,
    *,
    prior_transaction_id: str,
    previous_sha256: str,
    previous_generation: int,
    service_context: object,
    independently_read_predecessor: IndependentPlanPredecessorReader,
) -> None:
    """Validate the service's OWN pinned expectation against exact request."""
    try:
        expected = independently_read_predecessor(request, service_context)
    except Exception as error:
        raise PlanSuccessorServiceAdmissionError(
            "independent predecessor expectation unavailable"
        ) from error
    if (
        not isinstance(expected, IndependentServicePredecessor)
        or type(expected.installation_id) is not str
        or type(expected.witness_id) is not str
        or type(expected.witness_revision) is not int
        or type(expected.transaction_id) is not str
        or type(expected.generation) is not int
        or type(expected.receipt_sha256) is not str
        or expected.installation_id != request.installation_id
        or expected.witness_id != request.witness_id
        or expected.witness_revision != request.expected_witness_revision
        or expected.transaction_id != prior_transaction_id
        or expected.generation != previous_generation
        or expected.receipt_sha256 != previous_sha256
    ):
        raise PlanSuccessorServiceAdmissionError(
            "service-pinned predecessor does not match the proposed transition"
        )


def _approved(
    request: WitnessCommitRequest,
    *,
    service_context: object,
    independently_approve: IndependentCommitApproval,
) -> None:
    """Operator/physical-install approval must originate outside local Suite."""
    try:
        approved = independently_approve(request, service_context)
    except Exception as error:
        raise PlanSuccessorServiceAdmissionError(
            "independent plan activation approval unavailable"
        ) from error
    if approved is not True:
        raise PlanSuccessorServiceAdmissionError(
            "independent plan activation approval refused"
        )


def _assert_fence(
    current: WitnessCasFenceState | None,
    reserved: WitnessCasFenceState,
    request: WitnessCommitRequest,
) -> None:
    if (
        current != reserved
        or reserved.status != _PREPARED
        or reserved.installation_id != request.installation_id
        or reserved.request_sha256 != _sha(serialize_witness_commit_request(request))
        or reserved.predecessor_sha256 != request.predecessor_sha256
        or reserved.successor_sha256 != request.successor_sha256
        or reserved.expected_witness_revision != request.expected_witness_revision
        or reserved.witnessed_revision is not None
        or reserved.witnessed_receipt_sha256 is not None
        or reserved.authority != "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
    ):
        raise PlanSuccessorServiceAdmissionError(
            "durable CAS reservation disagrees; manual service reconciliation"
        )


def _assert_gate(
    current: WitnessWriterQuiescenceState | None,
    admitted: WitnessWriterQuiescenceState,
    reserved: WitnessCasFenceState,
) -> None:
    if (
        current != admitted
        or admitted.status != _ADMITTED
        or admitted.installation_id != reserved.installation_id
        or admitted.request_sha256 != reserved.request_sha256
        or admitted.signed_revision is not None
        or admitted.signed_head_sha256 is not None
        or admitted.authority != "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    ):
        raise PlanSuccessorServiceAdmissionError(
            "writer admission readback disagrees; reservation stays fenced"
        )


def admit_plan_successor_to_independent_service(
    review: PlanSuccessorDraftReview,
    *,
    service_context: object,
    independently_read_predecessor: IndependentPlanPredecessorReader,
    independently_approve: IndependentCommitApproval,
    ledger: WitnessCasFenceLedger,
    gate: WitnessWriterQuiescenceGate,
) -> PlanSuccessorServiceAdmission:
    """Approve and durably admit a local proposal WITHOUT invoking witness CAS.

    This adapter MUST run *inside* an independently administered service. Its
    preconfigured predecessor reader, approval provider, service context,
    SQLite ledger, and cooperating gate cannot come from local Suite files or
    client-controlled request fields. Approval must recheck protected software
    identity, genuine pending recovery, operator consent and service identity.

    All real witness writers must share this service's exclusive CAS fence and
    writer gate. Success is PREPARED + ADMITTED only; no launch credential.
    If any step fails after reserve(), do not release or silently retry it.
    """
    if (
        not callable(independently_read_predecessor)
        or not callable(independently_approve)
        or not isinstance(ledger, WitnessCasFenceLedger)
        or not isinstance(gate, WitnessWriterQuiescenceGate)
        or gate._ledger is not ledger
        or gate._db is not ledger._db
    ):
        raise PlanSuccessorServiceAdmissionError(
            "same independently provisioned durable fence and writer gate required"
        )
    request, prior_tx, prior_sha, prior_generation, next_generation = _proposal(review)
    _service_predecessor(
        request,
        prior_transaction_id=prior_tx,
        previous_sha256=prior_sha,
        previous_generation=prior_generation,
        service_context=service_context,
        independently_read_predecessor=independently_read_predecessor,
    )
    _approved(
        request,
        service_context=service_context,
        independently_approve=independently_approve,
    )
    # The first write is the exact durable reservation. Nothing later can
    # authorize a replay, even after an interrupted or failed admission.
    try:
        reserved = ledger.reserve(request, service_context=service_context)
        _assert_fence(
            ledger.observe(request, service_context=service_context),
            reserved,
            request,
        )
        admitted = gate.admit(request, service_context=service_context)
        _assert_fence(
            ledger.observe(request, service_context=service_context),
            reserved,
            request,
        )
        _assert_gate(
            gate.observe(request, service_context=service_context),
            admitted,
            reserved,
        )
    except (WitnessCasFenceError, WitnessWriterQuiescenceError) as error:
        raise PlanSuccessorServiceAdmissionError(
            "service admission failed; any durable reservation stays fenced"
        ) from error
    return PlanSuccessorServiceAdmission(
        request.installation_id,
        review.transaction_id,
        reserved.request_sha256,
        reserved.predecessor_sha256,
        reserved.successor_sha256,
        prior_generation,
        next_generation,
        request.expected_witness_revision,
    )


__all__ = (
    "IndependentPlanPredecessorReader",
    "IndependentServicePredecessor",
    "PlanSuccessorServiceAdmission",
    "PlanSuccessorServiceAdmissionError",
    "admit_plan_successor_to_independent_service",
)
