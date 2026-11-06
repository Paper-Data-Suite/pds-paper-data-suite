"""Issue #49 Slice 71: bind a verified plan to witnessed activation INTENT.

The independently provisioned witness is reread inside the existing locked,
two-sided arming service; this adapter never performs a selection switch, CAS,
receipt commit, rollback, or launch. An armed journal requires explicit recovery
if interrupted. Local Python observations are not independent trust anchors.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
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
from paper_data_suite.evergreen_witness_activation_intent import (
    WitnessActivationIntentError,
    arm_witness_bound_activation_intent,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_CONSENT: Final = "ARM_PLAN_WITNESS_ACTIVATION_INTENT_NO_SWITCH"
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")


class PlanActivationIntentError(ValueError):
    """The plan-bound predecessor/candidate activation request was refused."""


@dataclass(frozen=True, slots=True)
class PlanWitnessActivationIntent:
    """A journal arming result, expressly NOT authority to select or launch."""

    transaction_id: str
    journal_revision: int
    prior_generation: int
    proposed_generation: int
    witness_revision: int
    previous_receipt_sha256: str
    native_payload_sha256: str
    pip_inventory_sha256: str
    status: str = "WITNESSED_PLAN_ACTIVATION_INTENT_RECOVERY_ON_INTERRUPTION"
    authority: str = "NO_SELECTION_CAS_RECEIPT_LAUNCH_OR_ROLLBACK_AUTHORITY"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def arm_plan_bound_witness_activation_intent(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    installed: IsolatedPlanStageResult,
    recorded: RecordedPlanCandidateIntent,
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
) -> PlanWitnessActivationIntent:
    """Transition verified candidate journal to inert ACTIVATION_INTENT exactly once.

    IMPORTANT: the Slice-70 candidate must have been journaled with
    ``previous_receipt_sha256=sha256(prior.observation_record)``. That field is
    a *local observation-record* expectation, not the previous active receipt
    digest; those are separate identities. The existing locked witness armer
    verifies predecessor, publisher/pip/native bytes, and independent remote
    witness *again* before the only write: journal revision 1 -> 2.

    No local result confers switch/CAS/recovery authorization. Failure after
    the existing armer writes leaves ACTIVATION_INTENT needing reconciliation.
    """
    if (
        type(explicit_consent) is not str
        or explicit_consent != _CONSENT
        or not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(installed, IsolatedPlanStageResult)
        or not isinstance(recorded, RecordedPlanCandidateIntent)
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
        raise PlanActivationIntentError("invalid explicit plan activation inputs")

    tx = installed.transaction_id
    if (
        type(tx) is not str
        or _TX.fullmatch(tx) is None
        or recorded.transaction_id != tx
        or recorded.journal_revision != 1
        or recorded.baseline_transaction_id != witnessed.transaction_id
        or recorded.baseline_witness_revision != witnessed.witness_revision
        or recorded.pip_inventory_sha256 != installed.pip_inventory_sha256
        or installed.baseline_transaction_id != witnessed.transaction_id
        or installed.baseline_witness_revision != witnessed.witness_revision
        or not isinstance(recorded.native_payload_sha256, str)
        or _SHA.fullmatch(recorded.native_payload_sha256) is None
        or type(witnessed.receipt_sha256) is not str
        or _SHA.fullmatch(witnessed.receipt_sha256) is None
        or _sha256(previous_receipt_bytes) != witnessed.receipt_sha256
    ):
        raise PlanActivationIntentError(
            "candidate baseline or predecessor receipt changed"
        )

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
            raise PlanActivationIntentError("candidate and wheelhouse paths overlap")
        journal = load_update_intent(
            root, classroom_workspace=classroom_workspace, transaction_id=tx
        )
        prior_observation_sha = _sha256(prior.observation_record)
        if (
            journal is None
            or journal.transaction_id != tx
            or journal.phase is not UpdatePhase.CANDIDATE_VERIFIED
            or journal.revision != recorded.journal_revision
            or journal.stage_relative_path != stage_relative
            or journal.wheelhouse_relative_path != wheels_relative
            or journal.prepared_sha256 != _sha256(installed.prepared_record)
            or journal.registry_envelope_sha256 != _sha256(registry_envelope)
            or journal.lock_envelope_sha256 != _sha256(lock_envelope)
            or journal.native_envelope_sha256 != _sha256(native_envelope)
            or journal.expected_previous_receipt_sha256 != prior_observation_sha
        ):
            raise PlanActivationIntentError(
                "candidate journal lacks exact prior binding"
            )

        # Revalidate the full signed plan and current candidate bytes BEFORE
        # invoking the already-locked witness armer. The armer then repeats the
        # physical verifications with both cooperative locks held.
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
            or observed.pip_inventory_sha256 != recorded.pip_inventory_sha256
            or observed.native_payload_sha256 != recorded.native_payload_sha256
            or observed.prepared_record_sha256 != _sha256(installed.prepared_record)
            or observed.status != "PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
            or observed.authority
            != "NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"
        ):
            raise PlanActivationIntentError(
                "reverified candidate no longer matches plan"
            )

        # This existing operation owns the ONLY state mutation. It acquires
        # selection+journal locks, queries a fresh signed remote predecessor,
        # and rechecks BOTH installed compositions before journaling intent.
        armed = arm_witness_bound_activation_intent(
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
            minimum_witness_revision=witnessed.witness_revision,
            layout=layout,
        )
        # A mismatch here never reverses the journal. Recovery must reconcile.
        saved = load_update_intent(
            root, classroom_workspace=classroom_workspace, transaction_id=tx
        )
        if (
            armed.transaction_id != tx
            or armed.journal_revision != 2
            or armed.previous_receipt_sha256 != witnessed.receipt_sha256
            or armed.candidate_pip_inventory_sha256 != recorded.pip_inventory_sha256
            or armed.witness_revision < witnessed.witness_revision
            or armed.proposed_generation != armed.previous_generation + 1
            or armed.previous_generation != witnessed.generation
            or saved is None
            or saved.transaction_id != tx
            or saved.phase is not UpdatePhase.ACTIVATION_INTENT
            or saved.revision != armed.journal_revision
            or saved.stage_relative_path != stage_relative
            or saved.wheelhouse_relative_path != wheels_relative
            or saved.prepared_sha256 != journal.prepared_sha256
            or saved.native_envelope_sha256 != journal.native_envelope_sha256
            or saved.expected_previous_receipt_sha256 != prior_observation_sha
        ):
            raise PlanActivationIntentError(
                "activation intent may be persisted; manual reconciliation required"
            )
        return PlanWitnessActivationIntent(
            tx,
            armed.journal_revision,
            armed.previous_generation,
            armed.proposed_generation,
            armed.witness_revision,
            armed.previous_receipt_sha256,
            recorded.native_payload_sha256,
            recorded.pip_inventory_sha256,
        )
    except (
        UpdateJournalError,
        PlanStagedCandidateError,
        WitnessActivationIntentError,
        OSError,
    ) as error:
        raise PlanActivationIntentError(
            "signed plan/witness activation intent refused"
        ) from error


__all__ = (
    "PlanActivationIntentError",
    "PlanWitnessActivationIntent",
    "arm_plan_bound_witness_activation_intent",
)
