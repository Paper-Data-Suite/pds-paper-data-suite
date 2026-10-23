"""Issue #49 Slice 52: read-only fresh recovery orchestration, never activation.

Verify independently signed service context *before* observing locally. Reuse
actual Slice-43 local signed-head checks and Slice-47 signed-byte reaudits,
then repeat local readback to expose drift. The service deployment, local
filesystem isolation, trust roots and clock must be independently controlled.
No local receipt mutation, rollback, launch, CAS write, or cleanup.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_attested_forward_handoff import (
    AttestedForwardHandoff,
    AttestedForwardHandoffError,
    inspect_attested_forward_handoff,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_forward_byte_requalification import (
    ForwardByteRequalificationError,
    requalify_witnessed_successor_bytes,
)
from paper_data_suite.evergreen_local_receipt_recovery import (
    LocalReceiptRecoveryError,
    inspect_pending_forward_recovery,
)
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_recovery_convergence import (
    RecoveryConvergenceError,
    compare_recovery_convergence,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    RecoveryServiceAttestationError,
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)


class FreshAttestedRecoveryError(ValueError):
    """Cannot safely assemble fresh read-only recovery evidence."""


@dataclass(frozen=True, slots=True)
class FreshAttestedRecoveryObservation:
    """Ephemeral evidence correlation, NEVER an authorizing token or receipt."""

    attested_handoff: AttestedForwardHandoff
    signed_local_reads: int = 2
    signed_requalification_reads: int = 1
    status: str = "FRESH_ATTESTED_FORWARD_REVIEW_ONLY_RECOVERY_STILL_PENDING"
    authority: str = "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_OR_CLEANUP_AUTHORITY"


def inspect_fresh_attested_forward_recovery(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    request: WitnessCommitRequest,
    signed_service_envelope: bytes,
    challenge: bytes,
    pinned_service_public_key: bytes,
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
) -> FreshAttestedRecoveryObservation:
    """Reconstruct observations using the existing signed-head/byte inspectors.

    The supplied request and candidate evidence are untrusted until checked
    against the durable local proposal and independently signed wheel/native
    material. Caller must own the challenge and trusted public keys. This
    method does not authenticate physical service administration or guarantee
    isolation against a hostile local process. All outputs remain inert.
    """
    start = time.monotonic()
    try:
        # Refuse an invalid service envelope BEFORE probing local files or
        # invoking any witness transport or package/native file auditors.
        verified = verify_service_recovery_attestation(
            signed_service_envelope,
            request=request,
            challenge=challenge,
            pinned_service_public_key=pinned_service_public_key,
            now=now,
        )
        if verified.transaction_id != transaction_id:
            raise FreshAttestedRecoveryError(
                "service attestation names a different transaction"
            )
        service = WitnessWriterQuiescenceState(
            verified.installation_id,
            verified.request_sha256,
            "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
            verified.witness_revision,
            verified.successor_sha256,
        )
        initial = inspect_pending_forward_recovery(
            software_root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
            witness_transport=witness_transport,
            pinned_public_key=pinned_witness_public_key,
            now=now,
        )
        convergence = compare_recovery_convergence(
            request, service=service, local=initial
        )
        if convergence.finding != ("MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED"):
            raise FreshAttestedRecoveryError("signed local successor is not confirmed")
        requalified = requalify_witnessed_successor_bytes(
            software_root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
            convergence=convergence,
            candidate=candidate,
            candidate_module_envelopes=candidate_module_envelopes,
            trust=trust,
            witness_transport=witness_transport,
            pinned_public_key=pinned_witness_public_key,
            now=now,
            registry_checkpoint=registry_checkpoint,
            lock_checkpoint=lock_checkpoint,
            native_checkpoint=native_checkpoint,
            layout=layout,
        )
        # Repeat the existing locked local-proposal and signed-head read after
        # the physical audits. It is not atomic with those earlier reads.
        final = inspect_pending_forward_recovery(
            software_root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
            witness_transport=witness_transport,
            pinned_public_key=pinned_witness_public_key,
            now=now,
        )
        if initial != final:
            raise FreshAttestedRecoveryError("local signed head changed during audit")
        handoff = inspect_attested_forward_handoff(
            request,
            signed_service_envelope=signed_service_envelope,
            challenge=challenge,
            pinned_service_public_key=pinned_service_public_key,
            now=now,
            local=final,
            requalified=requalified,
        )
        # A supplied validation clock cannot prove wall-clock freshness after
        # processing; an elapsed budget prevents indefinite reuse in one call.
        if time.monotonic() - start > 30.0:
            raise FreshAttestedRecoveryError("recovery observation elapsed budget")
        return FreshAttestedRecoveryObservation(handoff)
    except (
        RecoveryServiceAttestationError,
        LocalReceiptRecoveryError,
        RecoveryConvergenceError,
        ForwardByteRequalificationError,
        AttestedForwardHandoffError,
    ) as error:
        raise FreshAttestedRecoveryError(
            "independent service, local witness or candidate evidence refused"
        ) from error


__all__ = (
    "FreshAttestedRecoveryError",
    "FreshAttestedRecoveryObservation",
    "inspect_fresh_attested_forward_recovery",
)
