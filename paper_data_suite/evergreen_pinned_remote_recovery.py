"""Issue #49 Slice 56: pinned HTTPS to fresh read-only recovery correlation.

One independently provisioned service fetch feeds existing fresh witness and
physical-byte inspectors. No software activation, CAS, rollback, receipt write,
cleanup or classroom access is authorized by an observation object.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_fresh_attested_recovery import (
    FreshAttestedRecoveryError,
    FreshAttestedRecoveryObservation,
    inspect_fresh_attested_forward_recovery,
)
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_recovery_observation_https import (
    ProvisionedRecoveryObservationHttpsClient,
    RecoveryObservationHttpsError,
    SignedRecoveryServiceExchange,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    RecoveryServiceAttestationError,
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    serialize_witness_commit_request,
)


class PinnedRemoteRecoveryError(ValueError):
    """Network-to-read-only recovery evidence could not be correlated."""


@dataclass(frozen=True, slots=True)
class PinnedRemoteRecoveryObservation:
    """Inert diagnostic correlation; freely forgeable, never a clearance."""

    fresh_observation: FreshAttestedRecoveryObservation
    service_envelope_sha256: str
    status: str = "PINNED_REMOTE_FORWARD_RECOVERY_REVIEW_ONLY"
    authority: str = "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_OR_CLEANUP_AUTHORITY"


def inspect_pinned_remote_forward_recovery(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    request: WitnessCommitRequest,
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
) -> PinnedRemoteRecoveryObservation:
    """Fetch ONCE then reverify and run full Slice-52 fresh read-only checks.

    The provisioned client owns its random challenge and TLS/signature pins;
    its returned dataclass is NOT trusted. The service and OS controls must
    actually be independent; this Python function cannot establish them.
    The caller's clock must be trustworthy and supplied immediately before
    calling. Neither a 30-second budget nor repeated sampled heads constitutes
    global writer isolation or authorizes local receipt/pointer mutation.
    """
    if (
        not isinstance(service_client, ProvisionedRecoveryObservationHttpsClient)
        or not isinstance(request, WitnessCommitRequest)
        or type(transaction_id) is not str
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(candidate, ProposedCandidateEvidence)
        or not isinstance(trust, TrustedKeyring)
        or type(pinned_witness_public_key) is not bytes
        or len(pinned_witness_public_key) != 32
        or not callable(witness_transport)
        or type(candidate_module_envelopes) is not dict
    ):
        raise PinnedRemoteRecoveryError("invalid remote recovery prerequisites")
    try:
        serialize_witness_commit_request(request)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    except (WitnessCommitProtocolError, ActiveReceiptError, ValueError) as error:
        raise PinnedRemoteRecoveryError(
            "invalid canonical witness successor"
        ) from error
    if transaction_id != successor.transaction_id:
        raise PinnedRemoteRecoveryError("successor transaction mismatch before network")

    started = time.monotonic()
    try:
        # A service response is always fetched through the opt-in, TLS-pinned
        # client; no raw envelope or caller-generated challenge input exists.
        exchange = service_client.fetch(request, now=now)
        if (
            not isinstance(exchange, SignedRecoveryServiceExchange)
            or type(exchange.challenge) is not bytes
            or type(exchange.signed_envelope) is not bytes
            or exchange.status != "SIGNED_SERVICE_EXCHANGE_READ_ONLY"
            or exchange.authority
            != "NO_LAUNCH_ROLLBACK_RECEIPT_OR_ACTIVATION_AUTHORITY"
        ):
            raise PinnedRemoteRecoveryError("untrusted service exchange object")
        # The returned 'verified' field is forgeable: authenticate the actual
        # envelope with the client's independent pin and exact fresh challenge.
        verified = verify_service_recovery_attestation(
            exchange.signed_envelope,
            request=request,
            challenge=exchange.challenge,
            pinned_service_public_key=service_client.pinned_service_public_key,
            now=now,
        )
        if exchange.verified != verified:
            raise PinnedRemoteRecoveryError(
                "exchange verification does not match bytes"
            )
        if time.monotonic() - started > 30.0:
            raise PinnedRemoteRecoveryError("remote observation elapsed budget")
        observed = inspect_fresh_attested_forward_recovery(
            software_root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
            request=request,
            signed_service_envelope=exchange.signed_envelope,
            challenge=exchange.challenge,
            pinned_service_public_key=service_client.pinned_service_public_key,
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
        envelope_sha = hashlib.sha256(exchange.signed_envelope).hexdigest()
        if (
            observed.attested_handoff.service_envelope_sha256 != envelope_sha
            or observed.attested_handoff.service_observation != verified
            or observed.attested_handoff.forward_handoff.transaction_id
            != successor.transaction_id
            or observed.attested_handoff.forward_handoff.successor_receipt_sha256
            != request.successor_sha256
            or observed.authority
            != "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_OR_CLEANUP_AUTHORITY"
            or time.monotonic() - started > 30.0
        ):
            raise PinnedRemoteRecoveryError(
                "stale or conflicting final recovery evidence"
            )
        return PinnedRemoteRecoveryObservation(observed, envelope_sha)
    except (
        RecoveryObservationHttpsError,
        RecoveryServiceAttestationError,
        FreshAttestedRecoveryError,
    ) as error:
        raise PinnedRemoteRecoveryError(
            "pinned network, witness or physical recovery checks refused"
        ) from error


__all__ = (
    "PinnedRemoteRecoveryError",
    "PinnedRemoteRecoveryObservation",
    "inspect_pinned_remote_forward_recovery",
)
