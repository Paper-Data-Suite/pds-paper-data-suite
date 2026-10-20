"""Issue #49 Slice 39: witness-gated, crash-recoverable activation INTENT.

This is NOT an activator. It acquires cooperating selection/journal locks,
authenticates the externally pinned predecessor, repeats independent signed
byte and pip-file checks on BOTH installations, and persists only the inert
ACTIVATION_INTENT journal transition. It neither changes selection nor grants
launch permission; interrupted intent requires explicit recovery.
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
    _parse_selection,
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


class WitnessActivationIntentError(ValueError):
    """A guarded activation intent could not be safely and atomically armed."""


@dataclass(frozen=True, slots=True)
class ArmedWitnessActivationIntent:
    """Durable journal state, NOT an authorized or activated installation."""

    transaction_id: str
    journal_revision: int
    previous_generation: int
    proposed_generation: int
    previous_receipt_sha256: str
    witness_revision: int
    candidate_pip_inventory_sha256: str
    status: str = "ACTIVATION_INTENT_ONLY_RECOVERY_REQUIRED"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _separate(first: Path, second: Path) -> bool:
    return (
        first != second and first not in second.parents and second not in first.parents
    )


def _envelopes(value: object) -> bool:
    return (
        type(value) is dict
        and 1 <= len(value) <= 32
        and all(
            type(k) is str and type(v) is bytes and 1 <= len(v) <= 128 * 1024
            for k, v in value.items()
        )
    )


def arm_witness_bound_activation_intent(
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
) -> ArmedWitnessActivationIntent:
    """Arm EXACTLY one durable marker after fresh, locked, two-sided checks.

    The signed external witness authenticates the *previous* receipt head;
    the staged candidate independently needs publisher, pip and native proof.
    Local locks are cooperative, not protection against hostile same-user
    filesystem writers. No switch, receipt commit, rollback or execution here.
    """
    if (
        type(expected_revision) is not int
        or expected_revision != 1
        or not isinstance(candidate, ProposedCandidateEvidence)
        or not isinstance(prior, ClaimedPriorEvidence)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.astimezone(timezone.utc).microsecond != 0
        or not _envelopes(candidate_module_envelopes)
        or not _envelopes(prior_module_envelopes)
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
        raise WitnessActivationIntentError("invalid bounded intent inputs")
    # Caller dicts are mutable. Capture exact envelope contents up front.
    candidate_modules = dict(candidate_module_envelopes)
    prior_modules = dict(prior_module_envelopes)
    current_time = now.astimezone(timezone.utc)
    selection_path: Path
    recovery_path: Path
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, selection_path, recovery_path = _selection_paths(root, classroom_workspace)
        selection_lock_path, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise WitnessActivationIntentError("unsafe or locked selection root") from error
    try:
        try:
            journal_path, journal_lock_path = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock_path)
        except UpdateJournalError as error:
            raise WitnessActivationIntentError(
                "transaction journal is locked"
            ) from error
        try:
            if _read_selection(recovery_path) is not None:
                raise WitnessActivationIntentError("pending selection recovery")
            old_pointer_bytes = _read_selection(selection_path)
            if old_pointer_bytes is None:
                raise WitnessActivationIntentError("missing previously selected slot")
            selected = _parse_selection(old_pointer_bytes)
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or journal.revision != expected_revision
                or journal.phase is not UpdatePhase.CANDIDATE_VERIFIED
                or journal.recorded_at > current_time
                or journal.expected_previous_receipt_sha256
                != _digest(prior.observation_record)
            ):
                raise WitnessActivationIntentError("journal is stale, armed or unbound")
            if any(
                _digest(raw) != expected
                for raw, expected in (
                    (candidate.prepared_record, journal.prepared_sha256),
                    (candidate.registry_envelope, journal.registry_envelope_sha256),
                    (candidate.lock_envelope, journal.lock_envelope_sha256),
                    (candidate.native_envelope, journal.native_envelope_sha256),
                )
            ):
                raise WitnessActivationIntentError(
                    "candidate differs from unarmed journal"
                )
            receipt = parse_untrusted_active_receipt(previous_receipt_bytes)
            if (
                receipt.transaction_id != selected.transaction_id
                or receipt.transaction_id == transaction_id
                or receipt.stage_relative_path != selected.stage_relative_path
                or receipt.prepared_sha256 != selected.prepared_sha256
                or receipt.native_envelope_sha256 != selected.native_envelope_sha256
                or receipt.generation != selected.generation
                or receipt.recorded_at > current_time
                or receipt.generation >= 2**53 - 1
                or receipt.prepared_sha256 != _digest(prior.prepared_record)
                or receipt.registry_sha256 != _digest(prior.registry_envelope)
                or receipt.lock_sha256 != _digest(prior.lock_envelope)
                or receipt.native_envelope_sha256 != _digest(prior.native_envelope)
            ):
                raise WitnessActivationIntentError(
                    "receipt and selected predecessor disagree"
                )
            candidate_stage = root / journal.stage_relative_path
            candidate_wheels = root / journal.wheelhouse_relative_path
            prior_stage = root / receipt.stage_relative_path
            prior_wheels = root / receipt.wheelhouse_relative_path
            paths = (candidate_stage, candidate_wheels, prior_stage, prior_wheels)
            for p in paths:
                _relative_child(root, p)
            if (
                not all(
                    _separate(a, b)
                    for index, a in enumerate(paths)
                    for b in paths[index + 1 :]
                )
                or _relative_child(root, prior.wheelhouse)
                != receipt.wheelhouse_relative_path
            ):
                raise WitnessActivationIntentError(
                    "overlapping or mismatched software directories"
                )

            def observe_both() -> tuple[
                VerifiedPreviousSlotBytes,
                ObservedPublisherPipCandidate,
                ObservedPublisherPipCandidate,
                VerifiedNativeEvidence,
            ]:
                verified_prior = verify_previous_slot_record(
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
                    prior_stage,
                    prior_wheels,
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
                observation = verified_prior.observation
                if (
                    verified_prior.record_sha256
                    != journal.expected_previous_receipt_sha256
                    or observation.transaction_id != receipt.transaction_id
                    or observation.stage_relative_path != receipt.stage_relative_path
                    or observation.wheelhouse_relative_path
                    != receipt.wheelhouse_relative_path
                    or observation.selection_generation != receipt.generation
                    or observation.native_payload_sha256
                    != receipt.native_payload_sha256
                    or old_pip.transaction_id != receipt.transaction_id
                    or old_pip.stage_root != prior_stage
                    or old_pip.wheelhouse != prior_wheels
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
                    raise WitnessActivationIntentError(
                        "fresh signed byte inventory disagrees"
                    )
                return verified_prior, old_pip, new_pip, new_native

            first = observe_both()
            # Remote head read while BOTH cooperating locks remain held.
            witness_start = time.monotonic()
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
                or witnessed.receipt.digest != _digest(previous_receipt_bytes)
                or witnessed.signed_expires_at < current_time
            ):
                raise WitnessActivationIntentError(
                    "external witness rejected predecessor"
                )
            # Repeat the *real* publisher, pip and native audits after the query.
            second = observe_both()
            if first != second:
                raise WitnessActivationIntentError(
                    "software changed across witness read"
                )
            if (
                time.monotonic() - witness_start
                > (witnessed.signed_expires_at - current_time).total_seconds()
            ):
                raise WitnessActivationIntentError(
                    "witness expired during signed-byte audit"
                )
            if (
                candidate_modules != candidate_module_envelopes
                or prior_modules != prior_module_envelopes
                or _read_selection(selection_path) != old_pointer_bytes
                or _read_selection(recovery_path) is not None
                or _read_journal(journal_path) != journal
            ):
                raise WitnessActivationIntentError(
                    "software coordination state changed"
                )
            # Sole intended persistent mutation: atomic journal-intent replace.
            armed = replace(
                journal,
                revision=journal.revision + 1,
                phase=UpdatePhase.ACTIVATION_INTENT,
                recorded_at=current_time,
            )
            _atomic_save(journal_path, armed)
            return ArmedWitnessActivationIntent(
                transaction_id,
                armed.revision,
                receipt.generation,
                receipt.generation + 1,
                witnessed.receipt.digest,
                witnessed.witness_revision,
                second[2].pip_inventory_sha256,
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
        raise WitnessActivationIntentError(
            "guarded activation intent rejected"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock_path.unlink(missing_ok=True)


__all__ = (
    "ArmedWitnessActivationIntent",
    "WitnessActivationIntentError",
    "arm_witness_bound_activation_intent",
)
