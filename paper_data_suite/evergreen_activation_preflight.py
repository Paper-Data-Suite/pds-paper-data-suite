"""Issue #49 Slice 38: witness-bound, read-only update activation preflight.

Connect a fresh signed prior-head query to locally observed update and selection
records. This is a non-atomic preview, NOT installation authority. In particular,
caller-provided candidate observations cannot replace fresh publisher/pip/native
audits under an eventual privileged activation lock. No filesystem mutations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    UntrustedSlotSelection,
    read_candidate_selection,
)
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    UntrustedActiveReceipt,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    CheckpointWitnessTransport,
    query_checkpoint_witness,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)
from paper_data_suite.evergreen_prior_update import ProposedCandidateEvidence
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    load_update_intent,
)


class ActivationPreflightError(ValueError):
    """The proposed transition does not match signed predecessor evidence."""


@dataclass(frozen=True, slots=True)
class WitnessBoundUpdatePreflight:
    """Evidence for review only, never a trusted activation or launch token."""

    transaction_id: str
    candidate_stage: str
    prior_stage: str
    candidate_pip_inventory_sha256: str
    previous_receipt_sha256: str
    previous_generation: int
    proposed_generation: int
    witness_revision: int
    witnessed_expires_at: datetime
    status: str = "PRECHECK_ONLY_NOT_AUTHORIZED"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _snapshot(
    software_root: Path,
    classroom_workspace: Path,
    transaction_id: str,
) -> tuple[UntrustedUpdateJournal, UntrustedSlotSelection]:
    journal = load_update_intent(
        software_root,
        classroom_workspace=classroom_workspace,
        transaction_id=transaction_id,
    )
    selection = read_candidate_selection(
        software_root, classroom_workspace=classroom_workspace
    )
    if journal is None or selection is None:
        raise ActivationPreflightError("missing update intent or prior selection")
    if journal.phase is not UpdatePhase.CANDIDATE_VERIFIED or journal.revision != 1:
        raise ActivationPreflightError("update is already armed or no longer verified")
    return journal, selection


def _bound_candidate(
    journal: UntrustedUpdateJournal,
    candidate: ObservedJournalPipCandidate,
    inputs: ProposedCandidateEvidence,
    previous_observation_record: bytes,
) -> None:
    if (
        journal.transaction_id != candidate.transaction_id
        or journal.revision != candidate.journal_revision
        or journal.stage_relative_path != candidate.stage_relative_path
        or journal.wheelhouse_relative_path != candidate.wheelhouse_relative_path
        or journal.expected_previous_receipt_sha256 is None
        or journal.expected_previous_receipt_sha256 != _sha(previous_observation_record)
        or any(
            _sha(raw) != expected
            for raw, expected in (
                (inputs.prepared_record, journal.prepared_sha256),
                (inputs.registry_envelope, journal.registry_envelope_sha256),
                (inputs.lock_envelope, journal.lock_envelope_sha256),
                (inputs.native_envelope, journal.native_envelope_sha256),
            )
        )
    ):
        raise ActivationPreflightError("candidate and update intent differ")


def _bound_prior(
    receipt: UntrustedActiveReceipt,
    selected: UntrustedSlotSelection,
) -> None:
    if (
        selected.transaction_id != receipt.transaction_id
        or selected.stage_relative_path != receipt.stage_relative_path
        or selected.prepared_sha256 != receipt.prepared_sha256
        or selected.native_envelope_sha256 != receipt.native_envelope_sha256
        or selected.generation != receipt.generation
    ):
        raise ActivationPreflightError(
            "selected prior slot differs from witnessed receipt"
        )


def inspect_witness_bound_update_preflight(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    candidate: ObservedJournalPipCandidate,
    candidate_inputs: ProposedCandidateEvidence,
    previous_observation_record: bytes,
    previous_receipt_bytes: bytes,
    witness_transport: CheckpointWitnessTransport,
    installation_id: str,
    pinned_public_key: bytes,
    expected_witness_id: str,
    now: datetime,
    minimum_witness_revision: int | None = None,
) -> WitnessBoundUpdatePreflight:
    """Query independent prior head and compare exact local transition claims.

    Requires operator-provisioned witness transport and public key. Reads local
    intent/selection before and after the remote query, failing closed on drift.
    The witness authenticates the PRIOR head, not the proposed candidate.
    Caller MUST independently reverify the candidate and protected deployment;
    neither can be certified by this preview or a supplied Python dataclass.
    """
    if (
        not isinstance(candidate, ObservedJournalPipCandidate)
        or not isinstance(candidate_inputs, ProposedCandidateEvidence)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or type(previous_observation_record) is not bytes
        or not 1 <= len(previous_observation_record) <= 16384
        or type(previous_receipt_bytes) is not bytes
        or any(
            type(raw) is not bytes
            for raw in (
                candidate_inputs.prepared_record,
                candidate_inputs.registry_envelope,
                candidate_inputs.lock_envelope,
                candidate_inputs.native_envelope,
            )
        )
    ):
        raise ActivationPreflightError("invalid bounded activation preflight inputs")
    try:
        root = _safe_root(software_root, classroom_workspace)
        journal, selected = _snapshot(root, classroom_workspace, transaction_id)
        prior = parse_untrusted_active_receipt(previous_receipt_bytes)
        _bound_prior(prior, selected)
        _bound_candidate(
            journal, candidate, candidate_inputs, previous_observation_record
        )
        if (
            journal.recorded_at > now.astimezone(timezone.utc)
            or prior.recorded_at > now.astimezone(timezone.utc)
            or candidate.transaction_id == prior.transaction_id
            or prior.generation >= 2**53 - 1
        ):
            raise ActivationPreflightError("inconsistent predecessor or update time")
        paths = (
            root / prior.stage_relative_path,
            root / prior.wheelhouse_relative_path,
            root / candidate.stage_relative_path,
            root / candidate.wheelhouse_relative_path,
        )
        for path in paths:
            _relative_child(root, path)
        if any(
            left == right or left in right.parents or right in left.parents
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        ):
            raise ActivationPreflightError(
                "prior and candidate software directories overlap"
            )
        observed = query_checkpoint_witness(
            witness_transport,
            installation_id=installation_id,
            receipt_bytes=previous_receipt_bytes,
            pinned_public_key=pinned_public_key,
            expected_witness_id=expected_witness_id,
            now=now,
            minimum_witness_revision=minimum_witness_revision,
        )
        if (
            observed.receipt.receipt != prior
            or observed.receipt.digest != _sha(previous_receipt_bytes)
            or observed.signed_expires_at < now.astimezone(timezone.utc)
        ):
            raise ActivationPreflightError(
                "witness did not authenticate exact prior head"
            )
        if _snapshot(root, classroom_workspace, transaction_id) != (journal, selected):
            raise ActivationPreflightError(
                "update or selection changed during witness query"
            )
        return WitnessBoundUpdatePreflight(
            transaction_id=candidate.transaction_id,
            candidate_stage=candidate.stage_relative_path,
            prior_stage=prior.stage_relative_path,
            candidate_pip_inventory_sha256=candidate.pip_inventory_sha256,
            previous_receipt_sha256=observed.receipt.digest,
            previous_generation=prior.generation,
            proposed_generation=prior.generation + 1,
            witness_revision=observed.witness_revision,
            witnessed_expires_at=observed.signed_expires_at,
        )
    except (
        UpdateJournalError,
        ActivationSlotError,
        ActiveReceiptError,
        CheckpointWitnessError,
    ) as error:
        raise ActivationPreflightError(
            "witness-bound update preflight rejected"
        ) from error


__all__ = (
    "ActivationPreflightError",
    "WitnessBoundUpdatePreflight",
    "inspect_witness_bound_update_preflight",
)
