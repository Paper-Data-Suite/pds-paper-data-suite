"""Issue #49 Slice 73: plan-bound IN-MEMORY successor commit request.

Reuses the existing locked predecessor/candidate/witness receipt draft verifier;
its result and commit request are local proposals and NEVER independent service
approval. No CAS dispatch, receipt publication, selection change or launch.
The pending recovery capsule remains mandatory throughout.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    _parse_selection,
    _paths,
    _read,
    read_pending_slot_recovery,
)
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_activation_intent import (
    PlanWitnessActivationIntent,
)
from paper_data_suite.evergreen_plan_candidate_intent import RecordedPlanCandidateIntent
from paper_data_suite.evergreen_plan_inert_selection import PlanPendingInertSelection
from paper_data_suite.evergreen_plan_stage_installer import IsolatedPlanStageResult
from paper_data_suite.evergreen_plan_staged_candidate import (
    PlanStagedCandidateError,
    inspect_plan_bound_staged_candidate,
)
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    ProposedCandidateEvidence,
)
from paper_data_suite.evergreen_successor_receipt_draft import (
    SuccessorReceiptDraftError,
    draft_witness_bound_successor_receipt,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    load_update_intent,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    make_witness_commit_request,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_CONSENT: Final = "DRAFT_PLAN_WITNESS_SUCCESSOR_FOR_INDEPENDENT_REVIEW"
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")


class PlanSuccessorDraftError(ValueError):
    """Plan, pending selection, or independently witnessed draft disagrees."""


@dataclass(frozen=True, slots=True)
class PlanSuccessorDraftReview:
    """Unsigned service-bound request; NEVER a CAS or launch credential."""

    transaction_id: str
    installation_id: str
    journal_revision: int
    predecessor_generation: int
    proposed_generation: int
    witness_revision: int
    previous_receipt_sha256: str
    proposed_receipt_sha256: str
    request_sha256: str
    serialized_request: bytes
    status: str = "UNSUBMITTED_SUCCESSOR_PROPOSAL_RECOVERY_CAPSULE_PENDING"
    authority: str = "NO_CAS_APPROVAL_RECEIPT_PUBLICATION_ROLLBACK_OR_LAUNCH"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def draft_plan_bound_successor_commit_request(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    installed: IsolatedPlanStageResult,
    recorded: RecordedPlanCandidateIntent,
    armed: PlanWitnessActivationIntent,
    selected: PlanPendingInertSelection,
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    native_envelope: bytes,
    prior: ClaimedPriorEvidence,
    prior_module_envelopes: dict[str, bytes],
    previous_receipt_bytes: bytes,
    witness_transport: CheckpointWitnessTransport,
    installation_id: str,
    pinned_public_key: bytes,
    expected_witness_id: str,
    trust: TrustedKeyring,
    now: datetime,
    explicit_consent: str,
    layout: str | None = None,
) -> PlanSuccessorDraftReview:
    """Re-audit, draft under cooperating locks, then verify local continuity.

    No writes are permitted here. Draft creation is not a witness commit grant.
    The externally operated writer must independently authenticate identities,
    bytes, permissions, and a durable CAS fence before considering a commit.
    """
    if (
        type(explicit_consent) is not str
        or explicit_consent != _CONSENT
        or not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(installed, IsolatedPlanStageResult)
        or not isinstance(recorded, RecordedPlanCandidateIntent)
        or not isinstance(armed, PlanWitnessActivationIntent)
        or not isinstance(selected, PlanPendingInertSelection)
        or not isinstance(prior, ClaimedPriorEvidence)
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.astimezone(timezone.utc).microsecond != 0
        or type(requested_targets) is not dict
        or any(
            type(v) is not bytes
            for v in (
                registry_envelope,
                lock_envelope,
                native_envelope,
                previous_receipt_bytes,
            )
        )
        or not 1 <= len(previous_receipt_bytes) <= 16384
        or any(
            type(mapping) is not dict
            or not 1 <= len(mapping) <= 32
            or any(
                type(k) is not str or type(v) is not bytes for k, v in mapping.items()
            )
            for mapping in (module_envelopes, prior_module_envelopes)
        )
        or type(pinned_public_key) is not bytes
        or len(pinned_public_key) != 32
        or not callable(witness_transport)
        or type(installation_id) is not str
        or _TX.fullmatch(installation_id) is None
        or type(expected_witness_id) is not str
        or not expected_witness_id
        or layout not in (None, "windows", "posix")
    ):
        raise PlanSuccessorDraftError("invalid plan successor review inputs")

    tx = installed.transaction_id
    if (
        type(tx) is not str
        or _TX.fullmatch(tx) is None
        or any(item.transaction_id != tx for item in (recorded, armed, selected))
        or recorded.journal_revision != 1
        or armed.journal_revision != 2
        or selected.journal_revision != 2
        or recorded.baseline_transaction_id != witnessed.transaction_id
        or recorded.baseline_witness_revision != witnessed.witness_revision
        or installed.baseline_transaction_id != witnessed.transaction_id
        or installed.baseline_witness_revision != witnessed.witness_revision
        or recorded.pip_inventory_sha256 != installed.pip_inventory_sha256
        or armed.pip_inventory_sha256 != installed.pip_inventory_sha256
        or armed.native_payload_sha256 != recorded.native_payload_sha256
        or armed.prior_generation != witnessed.generation
        or selected.predecessor_generation != witnessed.generation
        or armed.proposed_generation != selected.selected_generation
        or selected.selected_generation != witnessed.generation + 1
        or armed.witness_revision > selected.witness_revision
        or selected.predecessor_receipt_sha256 != witnessed.receipt_sha256
        or armed.previous_receipt_sha256 != witnessed.receipt_sha256
        or _sha(previous_receipt_bytes) != witnessed.receipt_sha256
        or selected.candidate_stage_relative_path == ""
    ):
        raise PlanSuccessorDraftError("selected successor disagrees with armed plan")
    try:
        root = _safe_root(software_root, classroom_workspace)
        stage = installed.stage_root.absolute()
        wheels = wheelhouse.absolute()
        stage_relative = _relative_child(root, stage)
        wheels_relative = _relative_child(root, wheels)
        if (
            stage != root / "candidate-builds" / tx
            or stage == wheels
            or stage in wheels.parents
            or wheels in stage.parents
            or selected.candidate_stage_relative_path != stage_relative
        ):
            raise PlanSuccessorDraftError("selected stage path does not match plan")
        journal = load_update_intent(
            root, classroom_workspace=classroom_workspace, transaction_id=tx
        )
        pending = read_pending_slot_recovery(
            root, classroom_workspace=classroom_workspace
        )
        _, pointer_path, _ = _paths(root, classroom_workspace)
        pointer_raw = _read(pointer_path)
        pointer = _parse_selection(pointer_raw) if pointer_raw is not None else None
        if (
            journal is None
            or journal.transaction_id != tx
            or journal.phase is not UpdatePhase.ACTIVATION_INTENT
            or journal.revision != 2
            or journal.stage_relative_path != stage_relative
            or journal.wheelhouse_relative_path != wheels_relative
            or journal.prepared_sha256 != _sha(installed.prepared_record)
            or journal.registry_envelope_sha256 != _sha(registry_envelope)
            or journal.lock_envelope_sha256 != _sha(lock_envelope)
            or journal.native_envelope_sha256 != _sha(native_envelope)
            or journal.expected_previous_receipt_sha256
            != _sha(prior.observation_record)
            or pending is None
            or pending.transaction_id != tx
            or pending.previous_bytes is None
            or pending.previous_sha256 != _sha(pending.previous_bytes)
            or pointer is None
            or pointer_raw is None
            or pending.candidate_sha256 != _sha(pointer_raw)
            or pointer.transaction_id != tx
            or pointer.generation != selected.selected_generation
            or pointer.stage_relative_path != stage_relative
            or pointer.prepared_sha256 != journal.prepared_sha256
            or pointer.native_envelope_sha256 != journal.native_envelope_sha256
        ):
            raise PlanSuccessorDraftError("exact recovery-pending selection missing")
        observed = inspect_plan_bound_staged_candidate(
            snapshot,
            witnessed,
            root,
            classroom_workspace=classroom_workspace,
            stage_root=stage,
            wheelhouse=wheels,
            prepared_record=installed.prepared_record,
            requested_targets=requested_targets,
            python_minor=python_minor,
            platform_tag=platform_tag,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            native_envelope=native_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
        if (
            observed.transaction_id != tx
            or observed.baseline_transaction_id != witnessed.transaction_id
            or observed.baseline_witness_revision != witnessed.witness_revision
            or observed.registry_payload_sha256 != snapshot.registry.payload_sha256
            or observed.signed_lock_payload_sha256
            != installed.signed_lock_payload_sha256
            or observed.pip_inventory_sha256 != installed.pip_inventory_sha256
            or observed.native_payload_sha256 != recorded.native_payload_sha256
            or observed.prepared_record_sha256 != _sha(installed.prepared_record)
            or observed.status != "PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
            or observed.authority
            != "NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"
        ):
            raise PlanSuccessorDraftError("candidate no longer matches signed plan")
        draft = draft_witness_bound_successor_receipt(
            root,
            classroom_workspace=classroom_workspace,
            transaction_id=tx,
            expected_revision=2,
            candidate=ProposedCandidateEvidence(
                installed.prepared_record,
                registry_envelope,
                lock_envelope,
                native_envelope,
            ),
            candidate_module_envelopes=dict(module_envelopes),
            prior=prior,
            prior_module_envelopes=dict(prior_module_envelopes),
            previous_receipt_bytes=previous_receipt_bytes,
            witness_transport=witness_transport,
            installation_id=installation_id,
            pinned_public_key=pinned_public_key,
            expected_witness_id=expected_witness_id,
            trust=trust,
            now=now,
            minimum_witness_revision=selected.witness_revision,
            layout=layout,
        )
        if (
            draft.transaction_id != tx
            or draft.previous_generation != selected.predecessor_generation
            or draft.proposed_generation != selected.selected_generation
            or draft.previous_receipt_sha256 != witnessed.receipt_sha256
            or draft.expected_witness_revision < selected.witness_revision
            or draft.proposed_receipt_sha256 != _sha(draft.receipt_bytes)
            or draft.status
            != "DRAFT_ONLY_CHECKPOINT_NOT_COMMITTED_RECOVERY_STILL_PENDING"
        ):
            raise PlanSuccessorDraftError("witnessed draft differs from selected plan")
        receipt = parse_untrusted_active_receipt(draft.receipt_bytes)
        if (
            receipt.transaction_id != tx
            or receipt.generation != selected.selected_generation
            or receipt.stage_relative_path != stage_relative
            or receipt.wheelhouse_relative_path != wheels_relative
            or receipt.prepared_sha256 != journal.prepared_sha256
            or receipt.registry_sha256 != journal.registry_envelope_sha256
            or receipt.lock_sha256 != journal.lock_envelope_sha256
            or receipt.native_envelope_sha256 != journal.native_envelope_sha256
            or receipt.native_payload_sha256 != recorded.native_payload_sha256
            or receipt.pip_inventory_sha256 != installed.pip_inventory_sha256
            or receipt.previous_receipt_sha256 != witnessed.receipt_sha256
        ):
            raise PlanSuccessorDraftError("proposed receipt differs from audited stage")
        request = make_witness_commit_request(
            draft,
            installation_id=installation_id,
            witness_id=expected_witness_id,
            previous_receipt_bytes=previous_receipt_bytes,
        )
        payload = serialize_witness_commit_request(request)
        if (
            request.installation_id != installation_id
            or request.witness_id != expected_witness_id
            or request.expected_witness_revision != draft.expected_witness_revision
            or request.predecessor_sha256 != witnessed.receipt_sha256
            or request.successor_sha256 != draft.proposed_receipt_sha256
            or not 1 <= len(payload) <= 48 * 1024
            or load_update_intent(
                root, classroom_workspace=classroom_workspace, transaction_id=tx
            )
            != journal
            or read_pending_slot_recovery(root, classroom_workspace=classroom_workspace)
            != pending
            or _read(pointer_path) != pointer_raw
        ):
            raise PlanSuccessorDraftError("draft handoff drifted; recovery required")
        return PlanSuccessorDraftReview(
            tx,
            installation_id,
            2,
            selected.predecessor_generation,
            selected.selected_generation,
            draft.expected_witness_revision,
            draft.previous_receipt_sha256,
            draft.proposed_receipt_sha256,
            _sha(payload),
            payload,
        )
    except (
        UpdateJournalError,
        ActivationSlotError,
        PlanStagedCandidateError,
        SuccessorReceiptDraftError,
        ActiveReceiptError,
        WitnessCommitProtocolError,
        OSError,
    ) as error:
        raise PlanSuccessorDraftError("plan-bound successor review refused") from error


__all__ = (
    "PlanSuccessorDraftError",
    "PlanSuccessorDraftReview",
    "draft_plan_bound_successor_commit_request",
)
