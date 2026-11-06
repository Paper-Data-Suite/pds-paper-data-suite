"""Issue #49 Slice 72: select a witnessed plan candidate INERTLY with recovery.

The existing Slice-40 selector owns the only write and reacquires cooperative
selection/journal locks, authenticates a fresh independent witness, rechecks
both signed installations and persists a recovery capsule before the pointer.
No new launch, receipt publication, witness CAS, signing or rollback authority.
A pending capsule BLOCKS use of the ordinary candidate-selection reader.
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
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_activation_intent import (
    PlanWitnessActivationIntent,
)
from paper_data_suite.evergreen_plan_candidate_intent import RecordedPlanCandidateIntent
from paper_data_suite.evergreen_plan_stage_installer import IsolatedPlanStageResult
from paper_data_suite.evergreen_plan_staged_candidate import (
    PlanStagedCandidateError,
    inspect_plan_bound_staged_candidate,
)
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    ProposedCandidateEvidence,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    load_update_intent,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)
from paper_data_suite.evergreen_witness_slot_transition import (
    WitnessSlotTransitionError,
    select_witness_bound_candidate_slot,
)

_CONSENT: Final = "SELECT_WITNESSED_PLAN_INERT_SLOT_PENDING_RECOVERY"
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")


class PlanInertSelectionError(ValueError):
    """An exact plan-bound, witness-protected inert selection was refused."""


@dataclass(frozen=True, slots=True)
class PlanPendingInertSelection:
    """Recovery-pending local pointer observation, NEVER launch authority."""

    transaction_id: str
    journal_revision: int
    predecessor_generation: int
    selected_generation: int
    witness_revision: int
    predecessor_receipt_sha256: str
    candidate_stage_relative_path: str
    status: str = "INERT_PLAN_SELECTION_PENDING_PROTECTED_RECONCILIATION"
    authority: str = "NO_EXECUTION_RECEIPT_CAS_LAUNCH_OR_ROLLBACK_AUTHORITY"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def select_plan_bound_witness_inert_slot(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    installed: IsolatedPlanStageResult,
    recorded: RecordedPlanCandidateIntent,
    armed: PlanWitnessActivationIntent,
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
) -> PlanPendingInertSelection:
    """Reaudit plan then delegate locked reversible pointer change to Slice 40.

    Failure AFTER the existing selector has written a capsule/pointer cannot be
    automatically retried or undone here; explicit witness-aware reconciliation
    must inspect the pending state. All Python observation values are forgeable.
    """
    if (
        type(explicit_consent) is not str
        or explicit_consent != _CONSENT
        or not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(installed, IsolatedPlanStageResult)
        or not isinstance(recorded, RecordedPlanCandidateIntent)
        or not isinstance(armed, PlanWitnessActivationIntent)
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
        or type(registry_envelope) is not bytes
        or type(lock_envelope) is not bytes
        or type(native_envelope) is not bytes
        or type(previous_receipt_bytes) is not bytes
        or not 1 <= len(previous_receipt_bytes) <= 16384
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= 32
        or type(prior_module_envelopes) is not dict
        or not 1 <= len(prior_module_envelopes) <= 32
        or any(
            type(key) is not str or type(envelope) is not bytes
            for mapping in (module_envelopes, prior_module_envelopes)
            for key, envelope in mapping.items()
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
        raise PlanInertSelectionError("invalid explicit inert-selection inputs")

    tx = installed.transaction_id
    if (
        type(tx) is not str
        or _TX.fullmatch(tx) is None
        or recorded.transaction_id != tx
        or armed.transaction_id != tx
        or recorded.journal_revision != 1
        or armed.journal_revision != 2
        or recorded.baseline_transaction_id != witnessed.transaction_id
        or recorded.baseline_witness_revision != witnessed.witness_revision
        or installed.baseline_transaction_id != witnessed.transaction_id
        or installed.baseline_witness_revision != witnessed.witness_revision
        or recorded.pip_inventory_sha256 != installed.pip_inventory_sha256
        or armed.pip_inventory_sha256 != installed.pip_inventory_sha256
        or armed.native_payload_sha256 != recorded.native_payload_sha256
        or armed.prior_generation != witnessed.generation
        or armed.proposed_generation != armed.prior_generation + 1
        or armed.witness_revision < witnessed.witness_revision
        or type(witnessed.receipt_sha256) is not str
        or _SHA.fullmatch(witnessed.receipt_sha256) is None
        or armed.previous_receipt_sha256 != witnessed.receipt_sha256
        or _digest(previous_receipt_bytes) != witnessed.receipt_sha256
    ):
        raise PlanInertSelectionError("armed plan or witnessed predecessor changed")

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
        ):
            raise PlanInertSelectionError("candidate and wheelhouse paths overlap")
        if (
            read_pending_slot_recovery(root, classroom_workspace=classroom_workspace)
            is not None
        ):
            raise PlanInertSelectionError("pending selection needs explicit recovery")
        journal = load_update_intent(
            root, classroom_workspace=classroom_workspace, transaction_id=tx
        )
        if (
            journal is None
            or journal.transaction_id != tx
            or journal.phase is not UpdatePhase.ACTIVATION_INTENT
            or journal.revision != armed.journal_revision
            or journal.stage_relative_path != stage_relative
            or journal.wheelhouse_relative_path != wheels_relative
            or journal.prepared_sha256 != _digest(installed.prepared_record)
            or journal.registry_envelope_sha256 != _digest(registry_envelope)
            or journal.lock_envelope_sha256 != _digest(lock_envelope)
            or journal.native_envelope_sha256 != _digest(native_envelope)
            or journal.expected_previous_receipt_sha256
            != _digest(prior.observation_record)
        ):
            raise PlanInertSelectionError("exact witnessed activation intent missing")

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
            or observed.prepared_record_sha256 != _digest(installed.prepared_record)
            or observed.status != "PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
            or observed.authority
            != "NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"
        ):
            raise PlanInertSelectionError("current candidate differs from plan")

        # The existing selector rechecks BOTH installations and the independent
        # witness while holding selection/journal locks. It writes the capsule
        # BEFORE the inert pointer; no alternate, less constrained path exists.
        selected = select_witness_bound_candidate_slot(
            root,
            classroom_workspace=classroom_workspace,
            transaction_id=tx,
            expected_revision=journal.revision,
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
            minimum_witness_revision=armed.witness_revision,
            layout=layout,
        )
        # Post-write reads are checks for operator guidance, NEVER receipts.
        pending = read_pending_slot_recovery(
            root, classroom_workspace=classroom_workspace
        )
        _, pointer_path, _ = _paths(root, classroom_workspace)
        pointer_bytes = _read(pointer_path)
        pointer = _parse_selection(pointer_bytes) if pointer_bytes is not None else None
        saved = load_update_intent(
            root, classroom_workspace=classroom_workspace, transaction_id=tx
        )
        if (
            selected.transaction_id != tx
            or selected.previous_generation != armed.prior_generation
            or selected.selected_generation != armed.proposed_generation
            or selected.witness_revision < armed.witness_revision
            or selected.previous_receipt_sha256 != witnessed.receipt_sha256
            or selected.selected_stage != stage_relative
            or selected.status != "INERT_SELECTION_PENDING_EXPLICIT_RECOVERY"
            or pending is None
            or pending.transaction_id != tx
            or pending.previous_bytes is None
            or pending.candidate_sha256 != _digest(pointer_bytes or b"")
            or pointer is None
            or pointer.transaction_id != tx
            or pointer.stage_relative_path != stage_relative
            or pointer.prepared_sha256 != journal.prepared_sha256
            or pointer.native_envelope_sha256 != journal.native_envelope_sha256
            or pointer.generation != armed.proposed_generation
            or saved != journal
        ):
            raise PlanInertSelectionError(
                "inert selection may have changed; explicit recovery required"
            )
        return PlanPendingInertSelection(
            tx,
            journal.revision,
            selected.previous_generation,
            selected.selected_generation,
            selected.witness_revision,
            selected.previous_receipt_sha256,
            stage_relative,
        )
    except (
        UpdateJournalError,
        ActivationSlotError,
        PlanStagedCandidateError,
        WitnessSlotTransitionError,
        OSError,
    ) as error:
        raise PlanInertSelectionError(
            "signed plan or witness-gated inert selection refused"
        ) from error


__all__ = (
    "PlanInertSelectionError",
    "PlanPendingInertSelection",
    "select_plan_bound_witness_inert_slot",
)
