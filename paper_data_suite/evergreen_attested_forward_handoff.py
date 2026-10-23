"""Issue #49 Slice 51: authenticate service data before recovery correlation.

This is an opt-in READ-ONLY value-comparison adapter. No activation authority
is created by a signature, and local/installed-byte observations remain caller
supplied. The coordinator must independently refresh and protect those facts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from paper_data_suite.evergreen_forward_byte_requalification import (
    ObservedForwardSuccessorBytes,
)
from paper_data_suite.evergreen_forward_recovery_handoff import (
    ForwardRecoveryHandoff,
    ForwardRecoveryHandoffError,
    prepare_forward_recovery_handoff,
)
from paper_data_suite.evergreen_local_receipt_recovery import ForwardRecoveryObservation
from paper_data_suite.evergreen_recovery_convergence import (
    RecoveryConvergenceError,
    compare_recovery_convergence,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    RecoveryServiceAttestationError,
    VerifiedRecoveryServiceAttestation,
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)


class AttestedForwardHandoffError(ValueError):
    """Authenticated observation cannot be safely correlated for review."""


@dataclass(frozen=True, slots=True)
class AttestedForwardHandoff:
    """Operator observation only; instances are forgeable and non-authorizing."""

    service_observation: VerifiedRecoveryServiceAttestation
    forward_handoff: ForwardRecoveryHandoff
    service_envelope_sha256: str
    status: str = "SIGNED_SERVICE_HANDOFF_CORRELATED_REVIEW_ONLY"
    authority: str = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"


def inspect_attested_forward_handoff(
    request: WitnessCommitRequest,
    *,
    signed_service_envelope: bytes,
    challenge: bytes,
    pinned_service_public_key: bytes,
    now: datetime,
    local: ForwardRecoveryObservation,
    requalified: ObservedForwardSuccessorBytes,
) -> AttestedForwardHandoff:
    """Verify independently pinned service signature *before* value comparison.

    Caller must supply a new unpredictable challenge for THIS service query,
    obtain local signed-head observation and real publisher/pip/native audits,
    and independently enforce protected deployment/writer isolation. Neither
    this wrapper nor the resulting object can grant a filesystem operation,
    execute modules, clear recovery, or commit an active receipt. A signature
    cannot prove that a real service supervisor stopped every external writer.
    """
    if (
        type(signed_service_envelope) is not bytes
        or not isinstance(local, ForwardRecoveryObservation)
        or not isinstance(requalified, ObservedForwardSuccessorBytes)
    ):
        raise AttestedForwardHandoffError("invalid recovery observation inputs")
    try:
        service = verify_service_recovery_attestation(
            signed_service_envelope,
            request=request,
            challenge=challenge,
            pinned_service_public_key=pinned_service_public_key,
            now=now,
        )
        # Reconstruct service state ONLY from authenticated fields, never an
        # in-memory caller-provided WitnessWriterQuiescenceState.
        authenticated_state = WitnessWriterQuiescenceState(
            installation_id=service.installation_id,
            request_sha256=service.request_sha256,
            status="SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
            signed_revision=service.witness_revision,
            signed_head_sha256=service.successor_sha256,
        )
        convergence = compare_recovery_convergence(
            request, service=authenticated_state, local=local
        )
        handoff = prepare_forward_recovery_handoff(
            request,
            convergence=convergence,
            requalified=requalified,
            service=authenticated_state,
        )
    except (
        RecoveryServiceAttestationError,
        RecoveryConvergenceError,
        ForwardRecoveryHandoffError,
    ) as error:
        raise AttestedForwardHandoffError(
            "signed service, local head, or installed-byte evidence refused"
        ) from error
    return AttestedForwardHandoff(
        service_observation=service,
        forward_handoff=handoff,
        service_envelope_sha256=hashlib.sha256(signed_service_envelope).hexdigest(),
    )


__all__ = (
    "AttestedForwardHandoff",
    "AttestedForwardHandoffError",
    "inspect_attested_forward_handoff",
)
