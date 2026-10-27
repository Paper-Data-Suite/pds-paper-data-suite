"""Issue #49 Slice 76: plan-bound pinned, read-only successor recovery.

A Slice-75 stopped-writer finding is a mutable local object, NOT a bearer grant.
Re-parse the exact Slice-73 request, correlate the inert plan selection, then
use the established Slice-56 pinned remote service + signed witness + physical
byte requalification path. No activation, receipt publication, capsule deletion,
CAS dispatch, launcher execution, workspace mutation or rollback is permitted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_pinned_remote_recovery import (
    PinnedRemoteRecoveryError,
    PinnedRemoteRecoveryObservation,
    inspect_pinned_remote_forward_recovery,
)
from paper_data_suite.evergreen_plan_inert_selection import PlanPendingInertSelection
from paper_data_suite.evergreen_plan_service_admission import (
    PlanSuccessorServiceAdmission,
)
from paper_data_suite.evergreen_plan_service_dispatch import (
    PlanSuccessorServiceDispatchError,
    PlanSuccessorServiceSignedRecovery,
    _exact_admitted_request,
)
from paper_data_suite.evergreen_plan_successor_draft import PlanSuccessorDraftReview
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_recovery_observation_https import (
    ProvisionedRecoveryObservationHttpsClient,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    serialize_witness_commit_request,
)

_SERVICE_STATUS: Final = "SIGNED_SUCCESSOR_REQUIRES_PROTECTED_FORWARD_RECOVERY"
_FENCE: Final = "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"
_WRITER: Final = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
_NO_AUTH: Final = "NO_RETRY_ROLLBACK_ACTIVATION_RECEIPT_PUBLICATION_OR_LAUNCH"
_SELECTED: Final = "INERT_PLAN_SELECTION_PENDING_PROTECTED_RECONCILIATION"
_SELECTED_AUTH: Final = "NO_EXECUTION_RECEIPT_CAS_LAUNCH_OR_ROLLBACK_AUTHORITY"
_REMOTE_STATUS: Final = "PINNED_REMOTE_FORWARD_RECOVERY_REVIEW_ONLY"
_REMOTE_AUTH: Final = "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_OR_CLEANUP_AUTHORITY"
_FORWARD_STATUS: Final = "FORWARD_HANDOFF_REQUIRES_PROTECTED_ACTIVATION_RECONCILIATION"
_FORWARD_AUTH: Final = "NO_LAUNCH_ROLLBACK_RECEIPT_OR_SWITCH_AUTHORITY"


class PlanForwardRecoveryError(ValueError):
    """Signed service, selected plan or installed successor cannot be correlated."""


@dataclass(frozen=True, slots=True)
class PlanForwardRecoveryReview:
    """Transient recovery *inspection*, never an authorization or receipt."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    stage_relative_path: str
    wheelhouse_relative_path: str
    pip_inventory_sha256: str
    native_payload_sha256: str
    signed_service_envelope_sha256: str
    status: str = "PLAN_SUCCESSOR_BYTES_REVIEWED_FORWARD_FINALIZATION_STILL_REQUIRED"
    authority: str = "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_CLEANUP_OR_CAS_AUTHORITY"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect_plan_bound_forward_recovery(
    review: PlanSuccessorDraftReview,
    admission: PlanSuccessorServiceAdmission,
    signed_recovery: PlanSuccessorServiceSignedRecovery,
    selected: PlanPendingInertSelection,
    software_root: Path,
    *,
    classroom_workspace: Path,
    service_client: ProvisionedRecoveryObservationHttpsClient,
    witness_transport: CheckpointWitnessTransport,
    pinned_witness_public_key: bytes,
    candidate: ProposedCandidateEvidence,
    candidate_module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    native_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> PlanForwardRecoveryReview:
    """Compare exact plan to *fresh* pinned service/witness and installed bytes.

    Service and trust anchors must be independently provisioned. This accepts
    no caller-authored service envelope or challenge. Slice-56 performs one
    pinned mTLS query, verifies the service signature, and re-audits candidate
    packages/native metadata around fresh signed witness readbacks. Cooperative
    locks do not ensure protection against a hostile same-user process.

    A successful result is useful only for *review*; this function intentionally
    exposes no path to active receipt writes, pointer transitions, or launch.
    """
    try:
        request, _, prior_generation = _exact_admitted_request(review, admission)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
        digest = _sha(serialize_witness_commit_request(request))
    except (
        PlanSuccessorServiceDispatchError,
        ActiveReceiptError,
        WitnessCommitProtocolError,
    ) as error:
        raise PlanForwardRecoveryError(
            "noncanonical or mismatched plan request"
        ) from error
    if (
        not isinstance(signed_recovery, PlanSuccessorServiceSignedRecovery)
        or type(signed_recovery.installation_id) is not str
        or type(signed_recovery.transaction_id) is not str
        or type(signed_recovery.request_sha256) is not str
        or type(signed_recovery.witness_revision) is not int
        or type(signed_recovery.signed_receipt_sha256) is not str
        or signed_recovery.installation_id != request.installation_id
        or signed_recovery.transaction_id != review.transaction_id
        or signed_recovery.request_sha256 != digest
        or signed_recovery.witness_revision != request.expected_witness_revision + 1
        or signed_recovery.signed_receipt_sha256 != request.successor_sha256
        or signed_recovery.fence_status != _FENCE
        or signed_recovery.writer_status != _WRITER
        or signed_recovery.status != _SERVICE_STATUS
        or signed_recovery.authority != _NO_AUTH
    ):
        raise PlanForwardRecoveryError(
            "Slice 75 recovery did not observe signed successor"
        )
    if (
        not isinstance(selected, PlanPendingInertSelection)
        or type(selected.journal_revision) is not int
        or type(selected.predecessor_generation) is not int
        or type(selected.selected_generation) is not int
        or type(selected.witness_revision) is not int
        or selected.transaction_id != review.transaction_id
        or selected.journal_revision != review.journal_revision
        or selected.predecessor_generation != prior_generation
        or selected.selected_generation != successor.generation
        or selected.witness_revision > request.expected_witness_revision
        or selected.witness_revision < 1
        or selected.predecessor_receipt_sha256 != request.predecessor_sha256
        or selected.candidate_stage_relative_path != successor.stage_relative_path
        or selected.status != _SELECTED
        or selected.authority != _SELECTED_AUTH
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(service_client, ProvisionedRecoveryObservationHttpsClient)
        or not callable(witness_transport)
        or type(pinned_witness_public_key) is not bytes
        or len(pinned_witness_public_key) != 32
        or not isinstance(candidate, ProposedCandidateEvidence)
        or type(candidate_module_envelopes) is not dict
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise PlanForwardRecoveryError(
            "inert selected plan or recovery configuration differs"
        )
    # Every assertion above is only an inexpensive *early refusal*. Real
    # authority belongs to the independently pinned service and wheel verifiers.
    try:
        remote = inspect_pinned_remote_forward_recovery(
            software_root,
            classroom_workspace=classroom_workspace,
            transaction_id=review.transaction_id,
            request=request,
            service_client=service_client,
            witness_transport=witness_transport,
            pinned_witness_public_key=pinned_witness_public_key,
            candidate=candidate,
            candidate_module_envelopes=candidate_module_envelopes,
            trust=trust,
            now=now,
            registry_checkpoint=registry_checkpoint,
            lock_checkpoint=lock_checkpoint,
            native_checkpoint=native_checkpoint,
            layout=layout,
        )
    except PinnedRemoteRecoveryError as error:
        raise PlanForwardRecoveryError(
            "pinned service or fresh signed installed-byte recovery refused"
        ) from error
    # Even the returned typed object is an inert value. Check it against the
    # canonical request and pre-existing plan, not the caller's claims alone.
    if not isinstance(remote, PinnedRemoteRecoveryObservation):
        raise PlanForwardRecoveryError("remote recovery returned no typed observation")
    handoff = remote.fresh_observation.attested_handoff.forward_handoff
    service = remote.fresh_observation.attested_handoff.service_observation
    envelope_hash = remote.fresh_observation.attested_handoff.service_envelope_sha256
    if (
        remote.status != _REMOTE_STATUS
        or remote.authority != _REMOTE_AUTH
        or remote.service_envelope_sha256 != envelope_hash
        or service.installation_id != request.installation_id
        or service.transaction_id != successor.transaction_id
        or service.request_sha256 != digest
        or service.successor_sha256 != request.successor_sha256
        or service.witness_revision != request.expected_witness_revision + 1
        or service.successor_generation != successor.generation
        or handoff.installation_id != request.installation_id
        or handoff.transaction_id != review.transaction_id
        or handoff.request_sha256 != digest
        or handoff.successor_receipt_sha256 != request.successor_sha256
        or handoff.generation != successor.generation
        or handoff.witness_revision != service.witness_revision
        or handoff.stage_relative_path != selected.candidate_stage_relative_path
        or handoff.wheelhouse_relative_path != successor.wheelhouse_relative_path
        or handoff.pip_inventory_sha256 != successor.pip_inventory_sha256
        or handoff.native_payload_sha256 != successor.native_payload_sha256
        or handoff.status != _FORWARD_STATUS
        or handoff.authority != _FORWARD_AUTH
        or remote.fresh_observation.status
        != "FRESH_ATTESTED_FORWARD_REVIEW_ONLY_RECOVERY_STILL_PENDING"
        or remote.fresh_observation.authority != _REMOTE_AUTH
        or remote.fresh_observation.signed_local_reads != 2
        or remote.fresh_observation.signed_requalification_reads != 1
    ):
        raise PlanForwardRecoveryError("fresh successor handoff diverges from plan")
    return PlanForwardRecoveryReview(
        request.installation_id,
        review.transaction_id,
        digest,
        request.successor_sha256,
        successor.generation,
        service.witness_revision,
        handoff.stage_relative_path,
        handoff.wheelhouse_relative_path,
        handoff.pip_inventory_sha256,
        handoff.native_payload_sha256,
        envelope_hash,
    )


__all__ = (
    "PlanForwardRecoveryError",
    "PlanForwardRecoveryReview",
    "inspect_plan_bound_forward_recovery",
)
