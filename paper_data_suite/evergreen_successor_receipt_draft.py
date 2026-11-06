"""Issue #49 Slice 41: witness-bound successor receipt DRAFT, not activation.

After Slice 40's inert selection, a pending recovery capsule must remain.
This module reauthenticates both software slots and a fresh externally signed
predecessor head under cooperating locks, then constructs canonical successor
receipt bytes in memory ONLY. It never commits a witness head, clears recovery,
marks activation successful, writes a receipt, or changes production launching.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    UntrustedSlotSelection,
    _parse_recovery,
    _parse_selection,
    _selection_bytes,
)
from paper_data_suite.evergreen_activation_slots import _lock as _selection_lock
from paper_data_suite.evergreen_activation_slots import _paths as _selection_paths
from paper_data_suite.evergreen_activation_slots import _read as _read_selection
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_checkpoint_witness import (
    CheckpointWitnessError,
    CheckpointWitnessTransport,
    query_checkpoint_witness,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_previous_install import (
    PreviousInstallationError,
    VerifiedPreviousSlotBytes,
    verify_previous_slot_record,
)
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    ProposedCandidateEvidence,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    ObservedPublisherPipCandidate,
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
)
from paper_data_suite.evergreen_update_journal import _lock as _journal_lock
from paper_data_suite.evergreen_update_journal import _paths as _journal_paths
from paper_data_suite.evergreen_update_journal import _read as _read_journal
from paper_data_suite.evergreen_update_journal import _unlock as _journal_unlock


class SuccessorReceiptDraftError(ValueError):
    """No coherent, witness-bound receipt proposal can be prepared."""


@dataclass(frozen=True, slots=True)
class WitnessBoundSuccessorDraft:
    """In-memory successor proposal, neither a CAS grant nor launch authority."""

    transaction_id: str
    previous_generation: int
    proposed_generation: int
    previous_receipt_sha256: str
    expected_witness_revision: int
    proposed_receipt_sha256: str
    receipt_bytes: bytes
    status: str = "DRAFT_ONLY_CHECKPOINT_NOT_COMMITTED_RECOVERY_STILL_PENDING"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _separate(first: Path, second: Path) -> bool:
    return (
        first != second and first not in second.parents and second not in first.parents
    )


def _modules(value: object) -> bool:
    return (
        type(value) is dict
        and 1 <= len(value) <= 32
        and all(
            type(k) is str and type(v) is bytes and 1 <= len(v) <= 128 * 1024
            for k, v in value.items()
        )
    )


def draft_witness_bound_successor_receipt(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    candidate: ProposedCandidateEvidence,
    candidate_module_envelopes: dict[str, bytes],
    prior: ClaimedPriorEvidence,
    prior_module_envelopes: dict[str, bytes],
    previous_receipt_bytes: bytes,
    witness_transport: CheckpointWitnessTransport,
    installation_id: str,
    pinned_public_key: bytes,
    expected_witness_id: str,
    trust: TrustedKeyring,
    now: datetime,
    minimum_witness_revision: int | None = None,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    native_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> WitnessBoundSuccessorDraft:
    """Read-only, double-audited successor receipt proposal for operator review.

    The pending recovery capsule is REQUIRED; it must be exact for the selected
    candidate and previous witnessed receipt. Signing/write authority remains
    solely with a future independently operated witness commit protocol. A
    draft must NEVER be submitted to MonotonicCheckpointStore.commit_receipt
    merely because this local function succeeded; its CAS is insufficient to
    certify physical installation or authorize production launch.
    """
    if (
        type(expected_revision) is not int
        or expected_revision != 2
        or not isinstance(candidate, ProposedCandidateEvidence)
        or not isinstance(prior, ClaimedPriorEvidence)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.astimezone(timezone.utc).microsecond != 0
        or not _modules(candidate_module_envelopes)
        or not _modules(prior_module_envelopes)
        or type(previous_receipt_bytes) is not bytes
        or not 1 <= len(previous_receipt_bytes) <= 16384
        or type(prior.observation_record) is not bytes
        or not 1 <= len(prior.observation_record) <= 8192
        or not isinstance(prior.wheelhouse, Path)
        or not callable(witness_transport)
        or type(pinned_public_key) is not bytes
        or len(pinned_public_key) != 32
        or layout not in (None, "windows" if os.name == "nt" else "posix")
        or any(
            type(item) is not bytes or not 1 <= len(item) <= 128 * 1024
            for item in (
                candidate.prepared_record,
                candidate.registry_envelope,
                candidate.lock_envelope,
                candidate.native_envelope,
                prior.prepared_record,
                prior.registry_envelope,
                prior.lock_envelope,
                prior.native_envelope,
            )
        )
    ):
        raise SuccessorReceiptDraftError("invalid bounded successor inputs")
    candidate_modules = dict(candidate_module_envelopes)
    prior_modules = dict(prior_module_envelopes)
    instant = now.astimezone(timezone.utc)
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, selection_path, recovery_path = _selection_paths(root, classroom_workspace)
        selection_lock_path, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise SuccessorReceiptDraftError("unsafe or locked selection root") from error
    try:
        try:
            journal_path, journal_lock_path = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock_path)
        except UpdateJournalError as error:
            raise SuccessorReceiptDraftError("transaction journal is locked") from error
        try:
            selection_bytes = _read_selection(selection_path)
            capsule_bytes = _read_selection(recovery_path)
            if selection_bytes is None or capsule_bytes is None:
                raise SuccessorReceiptDraftError(
                    "selected candidate and pending recovery capsule are required"
                )
            selected = _parse_selection(selection_bytes)
            capsule = _parse_recovery(capsule_bytes)
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or journal.revision != expected_revision
                or journal.phase is not UpdatePhase.ACTIVATION_INTENT
                or journal.recorded_at > instant
                or journal.expected_previous_receipt_sha256
                != _sha(prior.observation_record)
            ):
                raise SuccessorReceiptDraftError(
                    "exact pending activation intent required"
                )
            receipt = parse_untrusted_active_receipt(previous_receipt_bytes)
            if (
                capsule.transaction_id != transaction_id
                or capsule.previous_bytes is None
                or capsule.previous_sha256 != _sha(capsule.previous_bytes)
                or capsule.candidate_sha256 != _sha(selection_bytes)
                or receipt.generation >= 2**53 - 1
                or receipt.recorded_at > journal.recorded_at
            ):
                raise SuccessorReceiptDraftError(
                    "pending recovery/receipt continuity differs"
                )
            old = _parse_selection(capsule.previous_bytes)
            expected_selected = UntrustedSlotSelection(
                transaction_id,
                journal.stage_relative_path,
                journal.prepared_sha256,
                journal.native_envelope_sha256,
                receipt.generation + 1,
            )
            if (
                selected != expected_selected
                or selection_bytes != _selection_bytes(expected_selected)
                or old.transaction_id != receipt.transaction_id
                or old.transaction_id == transaction_id
                or old.stage_relative_path != receipt.stage_relative_path
                or old.prepared_sha256 != receipt.prepared_sha256
                or old.native_envelope_sha256 != receipt.native_envelope_sha256
                or old.generation != receipt.generation
                or receipt.prepared_sha256 != _sha(prior.prepared_record)
                or receipt.registry_sha256 != _sha(prior.registry_envelope)
                or receipt.lock_sha256 != _sha(prior.lock_envelope)
                or receipt.native_envelope_sha256 != _sha(prior.native_envelope)
                or any(
                    _sha(raw) != expected
                    for raw, expected in (
                        (candidate.prepared_record, journal.prepared_sha256),
                        (candidate.registry_envelope, journal.registry_envelope_sha256),
                        (candidate.lock_envelope, journal.lock_envelope_sha256),
                        (candidate.native_envelope, journal.native_envelope_sha256),
                    )
                )
            ):
                raise SuccessorReceiptDraftError(
                    "selected successor or source digest mismatch"
                )
            candidate_stage = root / journal.stage_relative_path
            candidate_wheels = root / journal.wheelhouse_relative_path
            old_stage = root / receipt.stage_relative_path
            old_wheels = root / receipt.wheelhouse_relative_path
            roots = (candidate_stage, candidate_wheels, old_stage, old_wheels)
            for directory in roots:
                _relative_child(root, directory)
            if (
                not all(
                    _separate(a, b) for i, a in enumerate(roots) for b in roots[i + 1 :]
                )
                or _relative_child(root, prior.wheelhouse)
                != receipt.wheelhouse_relative_path
            ):
                raise SuccessorReceiptDraftError(
                    "software stage paths overlap or differ"
                )

            def inspect() -> tuple[
                VerifiedPreviousSlotBytes,
                ObservedPublisherPipCandidate,
                ObservedPublisherPipCandidate,
                VerifiedNativeEvidence,
            ]:
                prev = verify_previous_slot_record(
                    prior.observation_record,
                    root,
                    classroom_workspace=classroom_workspace,
                    wheelhouse=prior.wheelhouse,
                    prepared_record=prior.prepared_record,
                    registry_envelope=prior.registry_envelope,
                    lock_envelope=prior.lock_envelope,
                    evidence_envelope=prior.native_envelope,
                    trust=trust,
                    now=now,
                    expected_record_sha256=journal.expected_previous_receipt_sha256,
                    layout=layout,
                )
                before = audit_publisher_bound_pip_candidate(
                    old_stage,
                    old_wheels,
                    prepared_record=prior.prepared_record,
                    registry_envelope=prior.registry_envelope,
                    lock_envelope=prior.lock_envelope,
                    module_envelopes=prior_modules,
                    trust=trust,
                    now=now,
                    registry_checkpoint=registry_checkpoint,
                    lock_checkpoint=lock_checkpoint,
                    layout=layout,
                )
                after = audit_publisher_bound_pip_candidate(
                    candidate_stage,
                    candidate_wheels,
                    prepared_record=candidate.prepared_record,
                    registry_envelope=candidate.registry_envelope,
                    lock_envelope=candidate.lock_envelope,
                    module_envelopes=candidate_modules,
                    trust=trust,
                    now=now,
                    registry_checkpoint=registry_checkpoint,
                    lock_checkpoint=lock_checkpoint,
                    layout=layout,
                )
                native = verify_signed_staged_native_evidence(
                    candidate_stage,
                    candidate_wheels,
                    prepared_record=candidate.prepared_record,
                    registry_envelope=candidate.registry_envelope,
                    lock_envelope=candidate.lock_envelope,
                    evidence_envelope=candidate.native_envelope,
                    trust=trust,
                    now=now,
                    checkpoint=native_checkpoint,
                    layout=layout,
                )
                observation = prev.observation
                if (
                    prev.record_sha256 != journal.expected_previous_receipt_sha256
                    or observation.transaction_id != receipt.transaction_id
                    or observation.stage_relative_path != receipt.stage_relative_path
                    or observation.wheelhouse_relative_path
                    != receipt.wheelhouse_relative_path
                    or observation.selection_generation != receipt.generation
                    or observation.native_payload_sha256
                    != receipt.native_payload_sha256
                    or before.transaction_id != receipt.transaction_id
                    or before.stage_root != old_stage
                    or before.wheelhouse != old_wheels
                    or before.pip_inventory_sha256 != receipt.pip_inventory_sha256
                    or before.publisher_digests != receipt.publisher_digests
                    or before.root_console_targets != receipt.root_console_targets
                    or before.external_distributions != receipt.external_distributions
                    or after.transaction_id != transaction_id
                    or after.stage_root != candidate_stage
                    or after.wheelhouse != candidate_wheels
                    or native.transaction_id != transaction_id
                    or native.stage_root != candidate_stage
                    or not native.payload_sha256
                ):
                    raise SuccessorReceiptDraftError(
                        "signed installed-byte evidence differs"
                    )
                return prev, before, after, native

            first = inspect()
            started = time.monotonic()
            witnessed = query_checkpoint_witness(
                witness_transport,
                installation_id=installation_id,
                receipt_bytes=previous_receipt_bytes,
                pinned_public_key=pinned_public_key,
                expected_witness_id=expected_witness_id,
                now=now,
                minimum_witness_revision=minimum_witness_revision,
            )
            if (
                witnessed.receipt.receipt != receipt
                or witnessed.receipt.digest != _sha(previous_receipt_bytes)
                or witnessed.signed_expires_at < instant
            ):
                raise SuccessorReceiptDraftError(
                    "witness head disagrees with predecessor"
                )
            second = inspect()
            if first != second:
                raise SuccessorReceiptDraftError(
                    "installed bytes drifted across witness read"
                )
            if (
                time.monotonic() - started
                > (witnessed.signed_expires_at - instant).total_seconds()
            ):
                raise SuccessorReceiptDraftError(
                    "witness expired during candidate audit"
                )
            if (
                candidate_modules != candidate_module_envelopes
                or prior_modules != prior_module_envelopes
                or _read_selection(selection_path) != selection_bytes
                or _read_selection(recovery_path) != capsule_bytes
                or _read_journal(journal_path) != journal
            ):
                raise SuccessorReceiptDraftError(
                    "coordinated state changed during audit"
                )
            new_candidate = ObservedJournalPipCandidate(
                transaction_id,
                journal.revision,
                journal.stage_relative_path,
                journal.wheelhouse_relative_path,
                second[3].payload_sha256,
                second[2].pip_inventory_sha256,
                second[2].publisher_digests,
                second[2].root_console_targets,
                second[2].external_distributions,
            )
            proposal = make_untrusted_active_receipt(
                new_candidate,
                prepared_record=candidate.prepared_record,
                registry_envelope=candidate.registry_envelope,
                lock_envelope=candidate.lock_envelope,
                native_envelope=candidate.native_envelope,
                generation=receipt.generation + 1,
                recorded_at=now,
                previous=ExternallyPinnedReceiptHead(
                    receipt.generation, witnessed.receipt.digest
                ),
            )
            parsed = parse_untrusted_active_receipt(proposal)
            if (
                parsed.previous_receipt_sha256 != witnessed.receipt.digest
                or parsed.transaction_id != transaction_id
                or parsed.stage_relative_path != selected.stage_relative_path
                or parsed.generation != selected.generation
                or parsed.pip_inventory_sha256 != new_candidate.pip_inventory_sha256
                or parsed.native_payload_sha256 != new_candidate.native_payload_sha256
            ):
                raise SuccessorReceiptDraftError(
                    "draft does not bind selected candidate"
                )
            return WitnessBoundSuccessorDraft(
                transaction_id,
                receipt.generation,
                parsed.generation,
                witnessed.receipt.digest,
                witnessed.witness_revision,
                _sha(proposal),
                proposal,
            )
        finally:
            _journal_unlock(journal_lock_path, journal_fd)
    except (
        UpdateJournalError,
        ActivationSlotError,
        ActiveReceiptError,
        PreviousInstallationError,
        PublisherPipPreflightError,
        NativeEvidenceError,
        CheckpointWitnessError,
    ) as error:
        raise SuccessorReceiptDraftError(
            "witness-bound receipt draft rejected"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock_path.unlink(missing_ok=True)


__all__ = (
    "SuccessorReceiptDraftError",
    "WitnessBoundSuccessorDraft",
    "draft_witness_bound_successor_receipt",
)
