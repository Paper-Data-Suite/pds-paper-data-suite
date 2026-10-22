"""Issue #49 Slice 46: non-authorizing cross-boundary recovery convergence.

Compare the exact Slice-42 receipt request, Slice-45 service-owned writer gate
observation, and Slice-43 signed local recovery observation. These Python
objects can be forged by the caller: this pure preflight is an operator aid,
NOT an authenticated interchange format or an activation/rollback decision.

No filesystem writes, process execution, network access, witness CAS,
certificate issuance, journal transition, pointer switch, or recovery cleanup.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from paper_data_suite.evergreen_active_receipts import parse_untrusted_active_receipt
from paper_data_suite.evergreen_local_receipt_recovery import ForwardRecoveryObservation
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)


class RecoveryConvergenceError(ValueError):
    """Unrecognized or conflicting local and service recovery claims."""


@dataclass(frozen=True, slots=True)
class RecoveryConvergenceFinding:
    """Operator-facing agreement only, never authority over installed software."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    predecessor_sha256: str
    successor_sha256: str
    observed_witness_revision: int
    observed_generation: int
    finding: str
    next_action: str
    authority: str = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"


# Treat unrecognized future gate/local states as an error, not a safe fallback.
_ADMITTED: Final = "ADMITTED_NOT_DISPATCHED"
_SENT: Final = "CAS_MAY_BE_IN_FLIGHT"
_STOPPING: Final = "STOP_REQUESTED_NO_DISPATCH"
_STOPPING_SENT: Final = "STOP_REQUESTED_MAY_BE_IN_FLIGHT"
_PRIOR: Final = "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"
_NEXT: Final = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
_LOCAL_PRIOR: Final = "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED"
_LOCAL_NEXT: Final = "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
_SERVICE_AUTHORITY: Final = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
_LOCAL_AUTHORITY: Final = "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"
_PENDING: Final = frozenset({_ADMITTED, _SENT, _STOPPING, _STOPPING_SENT})


def compare_recovery_convergence(
    request: WitnessCommitRequest,
    *,
    service: WitnessWriterQuiescenceState,
    local: ForwardRecoveryObservation,
) -> RecoveryConvergenceFinding:
    """Inspect internally consistent observations; NEVER authorize recovery.

    `service` must originate from an independently authenticated service,
    and `local` from fresh signed readback with real byte checks. This
    function CANNOT establish those provenance requirements. It compares
    values only; it is not a substitute for protected coordinator authority.

    A stopped-writer assertion plus two agreeing signed historical heads is
    still NOT a proof of physical deployment, safe offline rollback, or a
    fresh protected authorization. A signed head can change after sampling.
    """
    if (
        not isinstance(request, WitnessCommitRequest)
        or not isinstance(service, WitnessWriterQuiescenceState)
        or not isinstance(local, ForwardRecoveryObservation)
    ):
        raise RecoveryConvergenceError("expected three typed recovery observations")
    try:
        canonical_request = serialize_witness_commit_request(request)
        predecessor = parse_untrusted_active_receipt(request.previous_receipt_bytes)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    except (WitnessCommitProtocolError, ValueError) as error:
        raise RecoveryConvergenceError("invalid bounded successor request") from error
    request_sha = hashlib.sha256(canonical_request).hexdigest()
    if (
        type(service.installation_id) is not str
        or service.installation_id != request.installation_id
        or type(service.request_sha256) is not str
        or service.request_sha256 != request_sha
        or service.authority != _SERVICE_AUTHORITY
        or type(local.transaction_id) is not str
        or local.transaction_id != successor.transaction_id
        or local.authority != _LOCAL_AUTHORITY
        or service.status not in (*_PENDING, _PRIOR, _NEXT)
        or local.status not in (_LOCAL_PRIOR, _LOCAL_NEXT)
        or type(local.witness_revision) is not int
        or type(local.generation) is not int
        or type(local.observed_receipt_sha256) is not str
    ):
        raise RecoveryConvergenceError("request or observation identity mismatch")

    if local.status == _LOCAL_PRIOR:
        expected_revision = request.expected_witness_revision
        expected_generation = predecessor.generation
        expected_digest = request.predecessor_sha256
    else:
        expected_revision = request.expected_witness_revision + 1
        expected_generation = successor.generation
        expected_digest = request.successor_sha256
    if (
        local.witness_revision != expected_revision
        or local.generation != expected_generation
        or local.observed_receipt_sha256 != expected_digest
    ):
        raise RecoveryConvergenceError("local signed-head claim contradicts receipts")

    if service.status in _PENDING:
        if (
            service.signed_revision is not None
            or service.signed_head_sha256 is not None
        ):
            raise RecoveryConvergenceError("unsealed gate claims a signed conclusion")
        return RecoveryConvergenceFinding(
            request.installation_id,
            successor.transaction_id,
            request_sha,
            request.predecessor_sha256,
            request.successor_sha256,
            local.witness_revision,
            local.generation,
            "WRITER_NOT_QUIESCED_HEAD_ONLY_OBSERVED",
            "Preserve unresolved records; independently stop and join CAS writers",
        )

    if (
        type(service.signed_revision) is not int
        or type(service.signed_head_sha256) is not str
        or service.signed_revision != expected_revision
        or service.signed_head_sha256 != expected_digest
    ):
        raise RecoveryConvergenceError("service and local signed heads disagree")
    if service.status == _PRIOR and local.status == _LOCAL_PRIOR:
        return RecoveryConvergenceFinding(
            request.installation_id,
            successor.transaction_id,
            request_sha,
            request.predecessor_sha256,
            request.successor_sha256,
            local.witness_revision,
            local.generation,
            "MATCHED_PRIOR_HEAD_REVIEW_STILL_REQUIRED",
            "Verify protected writer fencing, prior installed bytes, and consent",
        )
    if service.status == _NEXT and local.status == _LOCAL_NEXT:
        return RecoveryConvergenceFinding(
            request.installation_id,
            successor.transaction_id,
            request_sha,
            request.predecessor_sha256,
            request.successor_sha256,
            local.witness_revision,
            local.generation,
            "MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED",
            "Verify protected successor software and reconcile active receipt forward",
        )
    raise RecoveryConvergenceError("service and local head classifications conflict")


__all__ = (
    "RecoveryConvergenceError",
    "RecoveryConvergenceFinding",
    "compare_recovery_convergence",
)
