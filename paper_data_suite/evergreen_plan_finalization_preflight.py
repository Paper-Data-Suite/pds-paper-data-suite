"""Issue #49 Slice 77: non-authorizing, lock-coordinated finalization preflight.

Re-runs the authenticated Slice-76 verification, then checks the exact durable
local proposal, inert selection, recovery capsule and signed successor head
under cooperating selection/journal locks. Neither these locks nor an in-memory
report confer independently protected filesystem mutation or launch authority.
No active receipt, pointer, journal, CAS, package or capsule is mutated.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_activation_slots import ActivationSlotError
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_local_receipt_recovery import (
    LocalReceiptRecoveryError,
    _ordinary_read,
    _parse,
    _release,
    _snapshot,
    _with_locks,
)
from paper_data_suite.evergreen_plan_forward_recovery import (
    PlanForwardRecoveryError,
    PlanForwardRecoveryReview,
    inspect_plan_bound_forward_recovery,
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
from paper_data_suite.evergreen_update_journal import UpdateJournalError
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    inspect_uncertain_witness_commit,
    serialize_witness_commit_request,
)

_REVIEW_STATUS: Final = (
    "PLAN_SUCCESSOR_BYTES_REVIEWED_FORWARD_FINALIZATION_STILL_REQUIRED"
)
_REVIEW_AUTHORITY: Final = "NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_CLEANUP_OR_CAS_AUTHORITY"
_SIGNED_STATUS: Final = "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED"
_PREPARED_STATUS: Final = (
    "LOCAL_FINALIZATION_PREFLIGHT_REVIEW_ONLY_RECOVERY_CAPSULE_REQUIRED"
)
_NO_AUTHORITY: Final = (
    "NO_RECEIPT_WRITE_CAPSULE_CLEANUP_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY"
)
_MAX_DURATION: Final = 30.0


class PlanFinalizationPreflightError(ValueError):
    """Finalization evidence is absent, changed, or not independently verified."""


@dataclass(frozen=True, slots=True)
class PlanFinalizationPreflight:
    """Ephemeral read-only correlation; NEVER a finalization or launch token."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    generation: int
    witness_revision: int
    proposal_sha256: str
    selection_sha256: str
    recovery_capsule_sha256: str
    journal_sha256: str
    service_envelope_sha256: str
    status: str = _PREPARED_STATUS
    authority: str = _NO_AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect_plan_finalization_preflight(
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
) -> PlanFinalizationPreflight:
    """Revalidate remote signer and physical bytes, then read locked local state.

    The two phases are NOT an atomic protected installation transaction. An
    external, privileged finalizer would have to repeat all checks under its
    own service/OS isolation before writing any active receipt or clearing the
    recovery capsule. Never use this return value as an authorization token.
    """
    started = time.monotonic()
    try:
        request, _, _ = _exact_admitted_request(review, admission)
        successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
        canonical = serialize_witness_commit_request(request)
    except (
        PlanSuccessorServiceDispatchError,
        ActiveReceiptError,
        WitnessCommitProtocolError,
    ) as error:
        raise PlanFinalizationPreflightError(
            "invalid canonical plan proposal"
        ) from error
    if (
        type(pinned_witness_public_key) is not bytes
        or len(pinned_witness_public_key) != 32
        or not callable(witness_transport)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
    ):
        raise PlanFinalizationPreflightError("invalid independent recovery inputs")
    try:
        fresh = inspect_plan_bound_forward_recovery(
            review,
            admission,
            signed_recovery,
            selected,
            software_root,
            classroom_workspace=classroom_workspace,
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
    except PlanForwardRecoveryError as error:
        raise PlanFinalizationPreflightError(
            "independent service, witness or installed-byte review unavailable"
        ) from error
    request_sha = _sha(canonical)
    if (
        not isinstance(fresh, PlanForwardRecoveryReview)
        or fresh.installation_id != request.installation_id
        or fresh.transaction_id != review.transaction_id
        or fresh.request_sha256 != request_sha
        or fresh.successor_sha256 != request.successor_sha256
        or fresh.successor_generation != successor.generation
        or fresh.witness_revision != request.expected_witness_revision + 1
        or fresh.stage_relative_path != successor.stage_relative_path
        or fresh.wheelhouse_relative_path != successor.wheelhouse_relative_path
        or fresh.pip_inventory_sha256 != successor.pip_inventory_sha256
        or fresh.native_payload_sha256 != successor.native_payload_sha256
        or type(fresh.signed_service_envelope_sha256) is not str
        or len(fresh.signed_service_envelope_sha256) != 64
        or any(
            c not in "0123456789abcdef" for c in fresh.signed_service_envelope_sha256
        )
        or fresh.status != _REVIEW_STATUS
        or fresh.authority != _REVIEW_AUTHORITY
        or time.monotonic() - started > _MAX_DURATION
    ):
        raise PlanFinalizationPreflightError(
            "refreshed successor evidence conflicts with exact plan"
        )
    try:
        root, sl, sf, jl, jf, path = _with_locks(
            software_root, classroom_workspace, review.transaction_id
        )
    except (ActivationSlotError, UpdateJournalError, OSError) as error:
        raise PlanFinalizationPreflightError(
            "local selection/journal cannot be locked for finalization inspection"
        ) from error
    try:
        raw = _ordinary_read(path)
        if raw is None:
            raise PlanFinalizationPreflightError(
                "durable successor proposal absent; preserve recovery state"
            )
        stored, _ = _parse(raw)
        if (
            stored.transaction_id != review.transaction_id
            or stored.request != request
            or serialize_witness_commit_request(stored.request) != canonical
            or stored.expected_witness_revision != request.expected_witness_revision
        ):
            raise PlanFinalizationPreflightError("durable proposal disagrees with plan")
        snapshot = _snapshot(root, classroom_workspace, review.transaction_id, request)
        if snapshot != stored:
            raise PlanFinalizationPreflightError(
                "journal, inert pointer or capsule drifted from durable proposal"
            )
        signed = inspect_uncertain_witness_commit(
            request,
            witness_transport=witness_transport,
            pinned_public_key=pinned_witness_public_key,
            now=now,
            minimum_witness_revision=request.expected_witness_revision + 1,
        )
        if (
            signed.status != _SIGNED_STATUS
            or signed.receipt_sha256 != request.successor_sha256
            or signed.witness_revision != fresh.witness_revision
            or signed.generation != successor.generation
            or _ordinary_read(path) != raw
            or _snapshot(root, classroom_workspace, review.transaction_id, request)
            != snapshot
            or time.monotonic() - started > _MAX_DURATION
        ):
            raise PlanFinalizationPreflightError(
                "fresh signed successor or local recovery state changed"
            )
        return PlanFinalizationPreflight(
            request.installation_id,
            review.transaction_id,
            request_sha,
            request.successor_sha256,
            successor.generation,
            signed.witness_revision,
            _sha(raw),
            snapshot.selection_sha256,
            snapshot.recovery_sha256,
            snapshot.journal_sha256,
            fresh.signed_service_envelope_sha256,
        )
    except (
        LocalReceiptRecoveryError,
        ActivationSlotError,
        UpdateJournalError,
        WitnessCommitProtocolError,
        ActiveReceiptError,
    ) as error:
        raise PlanFinalizationPreflightError(
            "guarded local pending recovery or signed witness check refused"
        ) from error
    finally:
        _release(sl, sf, jl, jf)


__all__ = (
    "PlanFinalizationPreflight",
    "PlanFinalizationPreflightError",
    "inspect_plan_finalization_preflight",
)
