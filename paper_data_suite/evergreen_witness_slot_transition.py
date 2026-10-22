"""Issue #49 Slice 40: witness-aware, reversible *inert* slot selection.

The pending recovery capsule precedes any selection change. Neither the
selection nor the journal is a production launch pointer or an active receipt.
Restoring the old inert selection is possible only before any successor
proposal exists; no candidate is executed. Locks are cooperative only.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    PendingSlotRecovery,
    UntrustedSlotSelection,
    _atomic,
    _parse_recovery,
    _parse_selection,
    _recovery_bytes,
    _selection_bytes,
)
from paper_data_suite.evergreen_activation_slots import _lock as _selection_lock
from paper_data_suite.evergreen_activation_slots import _paths as _selection_paths
from paper_data_suite.evergreen_activation_slots import _read as _read_selection
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
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
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    VerifiedNativeEvidence,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_offline_commit_interlock import (
    OfflineCommitInterlockError,
    refuse_if_local_successor_proposal_exists,
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
    _atomic_save,
    _relative_child,
    _safe_root,
)
from paper_data_suite.evergreen_update_journal import _lock as _journal_lock
from paper_data_suite.evergreen_update_journal import _paths as _journal_paths
from paper_data_suite.evergreen_update_journal import _read as _read_journal
from paper_data_suite.evergreen_update_journal import _unlock as _journal_unlock


class WitnessSlotTransitionError(ValueError):
    """The inert selection or its offline recovery was refused."""


@dataclass(frozen=True, slots=True)
class PendingWitnessSelection:
    """An inert pointer switch requiring reconciliation; never launch authority."""

    transaction_id: str
    previous_generation: int
    selected_generation: int
    witness_revision: int
    previous_receipt_sha256: str
    selected_stage: str
    status: str = "INERT_SELECTION_PENDING_EXPLICIT_RECOVERY"


@dataclass(frozen=True, slots=True)
class WitnessSlotRecovery:
    """Restored local pointer only; authenticated installation not established."""

    transaction_id: str
    restored_generation: int
    journal_revision: int
    status: str = "OLD_INERT_POINTER_RESTORED_FULL_RECOVERY_REQUIRED"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _separate(a: Path, b: Path) -> bool:
    return a != b and a not in b.parents and b not in a.parents


def _bounded_modules(value: object) -> bool:
    return (
        type(value) is dict
        and 1 <= len(value) <= 32
        and all(
            type(key) is str and type(raw) is bytes and 1 <= len(raw) <= 128 * 1024
            for key, raw in value.items()
        )
    )


def select_witness_bound_candidate_slot(
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
) -> PendingWitnessSelection:
    """Select a rev-2 armed candidate *inertly*, with exact offline rollback.

    Acquires selection then journal lock; audits both signed/pip/native slots
    on either side of a fresh signed witness read. Writes a recovery capsule
    BEFORE atomically replacing the untrusted selection pointer. The journal
    remains ACTIVATION_INTENT and the witness remains on the prior head.
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
        or not _bounded_modules(candidate_module_envelopes)
        or not _bounded_modules(prior_module_envelopes)
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
            type(raw) is not bytes or not 1 <= len(raw) <= 128 * 1024
            for raw in (
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
        raise WitnessSlotTransitionError("invalid bounded selection inputs")
    candidate_modules = dict(candidate_module_envelopes)
    prior_modules = dict(prior_module_envelopes)
    instant = now.astimezone(timezone.utc)
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, selection_path, recovery_path = _selection_paths(root, classroom_workspace)
        selection_lock_path, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise WitnessSlotTransitionError("unsafe or locked selection root") from error
    try:
        try:
            journal_path, journal_lock_path = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock_path)
        except UpdateJournalError as error:
            raise WitnessSlotTransitionError("transaction journal is locked") from error
        try:
            if _read_selection(recovery_path) is not None:
                raise WitnessSlotTransitionError("prior recovery capsule is unresolved")
            old_bytes = _read_selection(selection_path)
            if old_bytes is None:
                raise WitnessSlotTransitionError("previous selection must exist")
            old_selection = _parse_selection(old_bytes)
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or journal.phase is not UpdatePhase.ACTIVATION_INTENT
                or journal.revision != expected_revision
                or journal.recorded_at > instant
                or journal.expected_previous_receipt_sha256
                != _sha(prior.observation_record)
            ):
                raise WitnessSlotTransitionError("exact armed journal is required")
            if any(
                _sha(raw) != expected
                for raw, expected in (
                    (candidate.prepared_record, journal.prepared_sha256),
                    (candidate.registry_envelope, journal.registry_envelope_sha256),
                    (candidate.lock_envelope, journal.lock_envelope_sha256),
                    (candidate.native_envelope, journal.native_envelope_sha256),
                )
            ):
                raise WitnessSlotTransitionError("armed candidate evidence changed")
            receipt = parse_untrusted_active_receipt(previous_receipt_bytes)
            if (
                receipt.transaction_id != old_selection.transaction_id
                or receipt.transaction_id == transaction_id
                or receipt.stage_relative_path != old_selection.stage_relative_path
                or receipt.prepared_sha256 != old_selection.prepared_sha256
                or receipt.native_envelope_sha256
                != old_selection.native_envelope_sha256
                or receipt.generation != old_selection.generation
                or receipt.generation >= 2**53 - 1
                or receipt.recorded_at > journal.recorded_at
                or receipt.prepared_sha256 != _sha(prior.prepared_record)
                or receipt.registry_sha256 != _sha(prior.registry_envelope)
                or receipt.lock_sha256 != _sha(prior.lock_envelope)
                or receipt.native_envelope_sha256 != _sha(prior.native_envelope)
            ):
                raise WitnessSlotTransitionError(
                    "signed predecessor receipt/selection mismatch"
                )
            candidate_stage = root / journal.stage_relative_path
            candidate_wheels = root / journal.wheelhouse_relative_path
            old_stage = root / receipt.stage_relative_path
            old_wheels = root / receipt.wheelhouse_relative_path
            physical = (candidate_stage, candidate_wheels, old_stage, old_wheels)
            for directory in physical:
                _relative_child(root, directory)
            if (
                not all(
                    _separate(a, b)
                    for index, a in enumerate(physical)
                    for b in physical[index + 1 :]
                )
                or _relative_child(root, prior.wheelhouse)
                != receipt.wheelhouse_relative_path
            ):
                raise WitnessSlotTransitionError("stage paths overlap or differ")

            def observe() -> tuple[
                VerifiedPreviousSlotBytes,
                ObservedPublisherPipCandidate,
                ObservedPublisherPipCandidate,
                VerifiedNativeEvidence,
            ]:
                checked_prior = verify_previous_slot_record(
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
                old_pip = audit_publisher_bound_pip_candidate(
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
                new_pip = audit_publisher_bound_pip_candidate(
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
                new_native = verify_signed_staged_native_evidence(
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
                observed_old = checked_prior.observation
                if (
                    checked_prior.record_sha256
                    != journal.expected_previous_receipt_sha256
                    or observed_old.transaction_id != receipt.transaction_id
                    or observed_old.stage_relative_path != receipt.stage_relative_path
                    or observed_old.wheelhouse_relative_path
                    != receipt.wheelhouse_relative_path
                    or observed_old.selection_generation != receipt.generation
                    or observed_old.native_payload_sha256
                    != receipt.native_payload_sha256
                    or old_pip.transaction_id != receipt.transaction_id
                    or old_pip.stage_root != old_stage
                    or old_pip.wheelhouse != old_wheels
                    or old_pip.pip_inventory_sha256 != receipt.pip_inventory_sha256
                    or old_pip.publisher_digests != receipt.publisher_digests
                    or old_pip.root_console_targets != receipt.root_console_targets
                    or old_pip.external_distributions != receipt.external_distributions
                    or new_pip.transaction_id != transaction_id
                    or new_pip.stage_root != candidate_stage
                    or new_pip.wheelhouse != candidate_wheels
                    or new_native.transaction_id != transaction_id
                    or new_native.stage_root != candidate_stage
                    or not new_native.payload_sha256
                ):
                    raise WitnessSlotTransitionError("signed byte inventory differs")
                return checked_prior, old_pip, new_pip, new_native

            first = observe()
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
                raise WitnessSlotTransitionError("witness predecessor mismatch")
            second = observe()
            if first != second:
                raise WitnessSlotTransitionError(
                    "installed bytes drifted during witness"
                )
            if (
                time.monotonic() - started
                > (witnessed.signed_expires_at - instant).total_seconds()
            ):
                raise WitnessSlotTransitionError("witness expired before pointer write")
            if (
                candidate_modules != candidate_module_envelopes
                or prior_modules != prior_module_envelopes
                or _read_selection(selection_path) != old_bytes
                or _read_selection(recovery_path) is not None
                or _read_journal(journal_path) != journal
            ):
                raise WitnessSlotTransitionError("coordinated state changed")
            selected = UntrustedSlotSelection(
                transaction_id,
                journal.stage_relative_path,
                journal.prepared_sha256,
                journal.native_envelope_sha256,
                receipt.generation + 1,
            )
            selected_bytes = _selection_bytes(selected)
            capsule = PendingSlotRecovery(
                transaction_id,
                old_bytes,
                _sha(selected_bytes),
                _sha(old_bytes),
            )
            # Crash boundary 1: pending recovery must outlive selection change.
            _atomic(recovery_path, _recovery_bytes(capsule))
            # Crash boundary 2: leaving capsule in place blocks normal reads.
            _atomic(selection_path, selected_bytes)
            return PendingWitnessSelection(
                transaction_id,
                receipt.generation,
                selected.generation,
                witnessed.witness_revision,
                witnessed.receipt.digest,
                journal.stage_relative_path,
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
        raise WitnessSlotTransitionError(
            "witness-gated inert selection rejected"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock_path.unlink(missing_ok=True)


def reconcile_witness_bound_selection_offline(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    now: datetime,
) -> WitnessSlotRecovery:
    """Restore *only* the old inert pointer; preserve journal recovery history.

    Does not contact the witness, run code, touch installation directories, or
    certify the previous slot. Idempotent across a crash after pointer restore
    or after the journal RECOVERY_REQUIRED revision-3 write. A missing capsule,
    alien pointer, or mismatched armed journal requires operator intervention.
    """
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.astimezone(timezone.utc).microsecond != 0
    ):
        raise WitnessSlotTransitionError("aware whole-second recovery clock required")
    instant = now.astimezone(timezone.utc)
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, selection_path, recovery_path = _selection_paths(root, classroom_workspace)
        selection_lock_path, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise WitnessSlotTransitionError("unsafe or locked recovery root") from error
    try:
        try:
            journal_path, journal_lock_path = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock_path)
        except UpdateJournalError as error:
            raise WitnessSlotTransitionError("recovery journal locked") from error
        try:
            capsule_bytes = _read_selection(recovery_path)
            if capsule_bytes is None:
                raise WitnessSlotTransitionError("no pending recovery capsule")
            capsule = _parse_recovery(capsule_bytes)
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or capsule.transaction_id != transaction_id
                or journal.phase
                not in (UpdatePhase.ACTIVATION_INTENT, UpdatePhase.RECOVERY_REQUIRED)
                or (
                    journal.phase is UpdatePhase.ACTIVATION_INTENT
                    and journal.revision != 2
                )
                or (
                    journal.phase is UpdatePhase.RECOVERY_REQUIRED
                    and journal.revision != 3
                )
                or journal.recorded_at > instant
                or capsule.previous_bytes is None
            ):
                raise WitnessSlotTransitionError("ambiguous recovery journal/capsule")
            try:
                refuse_if_local_successor_proposal_exists(root, transaction_id)
            except OfflineCommitInterlockError as error:
                raise WitnessSlotTransitionError(
                    "offline restore blocked: possible witness commit"
                ) from error
            old = _parse_selection(capsule.previous_bytes)
            new = UntrustedSlotSelection(
                transaction_id,
                journal.stage_relative_path,
                journal.prepared_sha256,
                journal.native_envelope_sha256,
                old.generation + 1,
            )
            if (
                old.generation >= 2**53 - 1
                or old.transaction_id == transaction_id
                or _sha(_selection_bytes(new)) != capsule.candidate_sha256
                or _sha(capsule.previous_bytes) != capsule.previous_sha256
            ):
                raise WitnessSlotTransitionError("recovery preimage or digest differs")
            current = _read_selection(selection_path)
            if current is None or _sha(current) not in (
                capsule.previous_sha256,
                capsule.candidate_sha256,
            ):
                raise WitnessSlotTransitionError(
                    "ambiguous selection requires operator"
                )
            # Crash boundary 3: the capsule remains until both operations finish.
            if current != capsule.previous_bytes:
                _atomic(selection_path, capsule.previous_bytes)
            if journal.phase is UpdatePhase.ACTIVATION_INTENT:
                journal = replace(
                    journal,
                    revision=3,
                    phase=UpdatePhase.RECOVERY_REQUIRED,
                    recorded_at=instant,
                )
                _atomic_save(journal_path, journal)
            # Fail closed on changes before clearing the only rollback capsule.
            if (
                _read_selection(recovery_path) != capsule_bytes
                or _read_selection(selection_path) != capsule.previous_bytes
            ):
                raise WitnessSlotTransitionError(
                    "recovery files changed; preserve capsule for operator"
                )
            # Crash boundary 4: retry works after the journal revision-3 write.
            try:
                recovery_path.unlink()
            except OSError as error:
                raise WitnessSlotTransitionError(
                    "recovery capsule cleanup failed; retry required"
                ) from error
            return WitnessSlotRecovery(transaction_id, old.generation, journal.revision)
        finally:
            _journal_unlock(journal_lock_path, journal_fd)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise WitnessSlotTransitionError(
            "offline selection recovery rejected"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock_path.unlink(missing_ok=True)


__all__ = (
    "PendingWitnessSelection",
    "WitnessSlotRecovery",
    "WitnessSlotTransitionError",
    "reconcile_witness_bound_selection_offline",
    "select_witness_bound_candidate_slot",
)
