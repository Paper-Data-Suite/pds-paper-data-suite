"""Issue #49 Slice 48: non-authorizing successor-recovery handoff correlation.

Only compare typed observations from earlier slices. Every value can be forged
by a caller: this has no authority to switch a slot, trust a service, clear a
recovery capsule, commit a receipt, or launch classroom software.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_forward_byte_requalification import (
    ObservedForwardSuccessorBytes,
)
from paper_data_suite.evergreen_recovery_convergence import (
    RecoveryConvergenceFinding,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)


class ForwardRecoveryHandoffError(ValueError):
    """The candidate handoff cannot safely describe a witnessed successor."""


@dataclass(frozen=True, slots=True)
class ForwardRecoveryHandoff:
    """Operator-oriented correlation, NOT a signed or protected certificate."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_receipt_sha256: str
    generation: int
    witness_revision: int
    stage_relative_path: str
    wheelhouse_relative_path: str
    pip_inventory_sha256: str
    native_payload_sha256: str
    status: str = "FORWARD_HANDOFF_REQUIRES_PROTECTED_ACTIVATION_RECONCILIATION"
    authority: str = "NO_LAUNCH_ROLLBACK_RECEIPT_OR_SWITCH_AUTHORITY"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def prepare_forward_recovery_handoff(
    request: WitnessCommitRequest,
    *,
    convergence: RecoveryConvergenceFinding,
    requalified: ObservedForwardSuccessorBytes,
    service: WitnessWriterQuiescenceState,
) -> ForwardRecoveryHandoff:
    """Correlate exact successor identities; do not *approve* a transition.

    The service observation must originate from a truly isolated coordinator;
    the requalification must be freshly obtained from real trusted audits.
    This function cannot prove either provenance or sampling freshness. An
    independently protected physical coordinator MUST repeat its own checks.
    """
    if (
        not isinstance(request, WitnessCommitRequest)
        or not isinstance(convergence, RecoveryConvergenceFinding)
        or not isinstance(requalified, ObservedForwardSuccessorBytes)
        or not isinstance(service, WitnessWriterQuiescenceState)
    ):
        raise ForwardRecoveryHandoffError("expected typed forward-recovery inputs")
    try:
        request_sha = _sha(serialize_witness_commit_request(request))
        predecessor = parse_untrusted_active_receipt(request.previous_receipt_bytes)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    except (WitnessCommitProtocolError, ActiveReceiptError, ValueError) as error:
        raise ForwardRecoveryHandoffError(
            "invalid canonical successor request"
        ) from error

    next_revision = request.expected_witness_revision + 1
    if (
        convergence.finding != "MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED"
        or convergence.authority != "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
        or service.status
        != "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
        or service.authority != "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
        or requalified.status
        != "POST_CAS_SIGNED_BYTES_OBSERVED_FORWARD_RECOVERY_STILL_REQUIRED"
        or requalified.authority != "NO_LAUNCH_ROLLBACK_OR_RECEIPT_COMMIT_AUTHORITY"
        or convergence.installation_id != request.installation_id
        or service.installation_id != request.installation_id
        or convergence.transaction_id != successor.transaction_id
        or requalified.transaction_id != successor.transaction_id
        or convergence.request_sha256 != request_sha
        or service.request_sha256 != request_sha
        or convergence.predecessor_sha256 != request.predecessor_sha256
        or convergence.successor_sha256 != request.successor_sha256
        or requalified.successor_receipt_sha256 != request.successor_sha256
        or convergence.observed_witness_revision != next_revision
        or service.signed_revision != next_revision
        or requalified.witness_revision != next_revision
        or service.signed_head_sha256 != request.successor_sha256
        or convergence.observed_generation != successor.generation
        or requalified.generation != successor.generation
        or successor.generation != predecessor.generation + 1
        or requalified.stage_relative_path != successor.stage_relative_path
        or requalified.pip_inventory_sha256 != successor.pip_inventory_sha256
        or requalified.native_payload_sha256 != successor.native_payload_sha256
    ):
        raise ForwardRecoveryHandoffError(
            "service, witness, proposal or installed-byte claims disagree"
        )

    # Even a fully matching in-memory report is NOT durable authenticated
    # evidence, and it cannot be replayed into a production launcher.
    return ForwardRecoveryHandoff(
        installation_id=request.installation_id,
        transaction_id=successor.transaction_id,
        request_sha256=request_sha,
        successor_receipt_sha256=request.successor_sha256,
        generation=successor.generation,
        witness_revision=next_revision,
        stage_relative_path=successor.stage_relative_path,
        wheelhouse_relative_path=successor.wheelhouse_relative_path,
        pip_inventory_sha256=successor.pip_inventory_sha256,
        native_payload_sha256=successor.native_payload_sha256,
    )


__all__ = (
    "ForwardRecoveryHandoff",
    "ForwardRecoveryHandoffError",
    "prepare_forward_recovery_handoff",
)
