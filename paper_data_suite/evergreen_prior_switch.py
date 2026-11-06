"""Issue #49: two-sided, rollback-capable selection of an armed candidate.

Only an inert software selection pointer is changed. A previous slot must be
reverified against independent signed evidence before its exact pointer bytes
are preserved for rollback. Local journals, pointers and observations remain
editable and cannot confer installation history or production launch rights.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    PendingSlotRecovery,
    UntrustedSlotSelection,
    _atomic,
    _parse_selection,
    _recovery_bytes,
    _selection_bytes,
)
from paper_data_suite.evergreen_activation_slots import (
    _lock as _selection_lock,
)
from paper_data_suite.evergreen_activation_slots import (
    _paths as _selection_paths,
)
from paper_data_suite.evergreen_activation_slots import (
    _read as _read_selection,
)
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_previous_install import (
    PreviousInstallationError,
    verify_previous_slot_record,
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
    _unlock,
)
from paper_data_suite.evergreen_update_journal import (
    _lock as _journal_lock,
)
from paper_data_suite.evergreen_update_journal import (
    _paths as _journal_paths,
)
from paper_data_suite.evergreen_update_journal import (
    _read as _read_journal,
)


class PriorSwitchError(ValueError):
    """A prior-bound candidate selection cannot safely be attempted."""


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _separate(first: Path, second: Path) -> bool:
    return (
        first != second and first not in second.parents and second not in first.parents
    )


def switch_armed_prior_bound_selection(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    candidate: ProposedCandidateEvidence,
    prior: ClaimedPriorEvidence,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None = None,
) -> UntrustedSlotSelection:
    """Recheck both physical slots under cooperating locks; select reversibly.

    The journal must already be in ``activation_intent`` from Slice 15.
    This writes only a recovery capsule followed by an inert pointer; neither
    file is an active receipt. The physical previous installation is retained.
    An interrupted switch MUST use ``restore_previous_selection`` from Slice 12.
    """
    if (
        type(expected_revision) is not int
        or expected_revision < 2
        or not isinstance(candidate, ProposedCandidateEvidence)
        or not isinstance(prior, ClaimedPriorEvidence)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        raise PriorSwitchError("invalid prior-bound switch evidence or revision")
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, selection_path, recovery_path = _selection_paths(root, classroom_workspace)
        lock_path, selection_fd = _selection_lock(root)
    except (ActivationSlotError, UpdateJournalError) as error:
        raise PriorSwitchError("unsafe or locked software selection root") from error
    try:
        try:
            journal_path, journal_lock_path = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock_path)
        except UpdateJournalError as error:
            raise PriorSwitchError("transaction already locked or invalid") from error
        try:
            if _read_selection(recovery_path) is not None:
                raise PriorSwitchError("unreconciled recovery blocks a second switch")
            journal = _read_journal(journal_path)
            if (
                journal is None
                or journal.transaction_id != transaction_id
                or journal.revision != expected_revision
                or journal.phase is not UpdatePhase.ACTIVATION_INTENT
            ):
                raise PriorSwitchError("exact armed journal revision is required")
            if (
                journal.expected_previous_receipt_sha256 is None
                or journal.recorded_at > now.astimezone(timezone.utc)
            ):
                raise PriorSwitchError("missing prior binding or invalid switch time")
            for raw, expected in (
                (candidate.prepared_record, journal.prepared_sha256),
                (candidate.registry_envelope, journal.registry_envelope_sha256),
                (candidate.lock_envelope, journal.lock_envelope_sha256),
                (candidate.native_envelope, journal.native_envelope_sha256),
                (prior.observation_record, journal.expected_previous_receipt_sha256),
            ):
                if type(raw) is not bytes or _digest(raw) != expected:
                    raise PriorSwitchError("source evidence differs from armed journal")
            old_bytes = _read_selection(selection_path)
            if old_bytes is None:
                raise PriorSwitchError("an existing selected slot is required")
            old = _parse_selection(old_bytes)
            stage = root / journal.stage_relative_path
            wheels = root / journal.wheelhouse_relative_path
            _relative_child(root, stage)
            _relative_child(root, wheels)
            previous = verify_previous_slot_record(
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
            signed = verify_signed_staged_native_evidence(
                stage,
                wheels,
                prepared_record=candidate.prepared_record,
                registry_envelope=candidate.registry_envelope,
                lock_envelope=candidate.lock_envelope,
                evidence_envelope=candidate.native_envelope,
                trust=trust,
                now=now,
                layout=layout,
            )
            if (
                signed.transaction_id != transaction_id
                or signed.stage_root != stage
                or previous.observation.transaction_id != old.transaction_id
                or previous.observation.stage_relative_path != old.stage_relative_path
                or previous.observation.selection_generation != old.generation
                or old.transaction_id == transaction_id
            ):
                raise PriorSwitchError("previous or candidate identity differs")
            prior_stage = root / previous.observation.stage_relative_path
            prior_wheels = root / previous.observation.wheelhouse_relative_path
            paths = (stage, wheels, prior_stage, prior_wheels)
            if not all(
                _separate(left, right)
                for index, left in enumerate(paths)
                for right in paths[index + 1 :]
            ):
                raise PriorSwitchError("software directories overlap")
            if old.generation >= 2**53 - 1:
                raise PriorSwitchError("candidate generation exhausted")
            selected = UntrustedSlotSelection(
                transaction_id,
                journal.stage_relative_path,
                journal.prepared_sha256,
                journal.native_envelope_sha256,
                old.generation + 1,
            )
            new_bytes = _selection_bytes(selected)
            recovery = PendingSlotRecovery(
                transaction_id,
                old_bytes,
                _digest(new_bytes),
                _digest(old_bytes),
            )
            # Any failure after this write requires explicit recovery, never
            # promotion or automatic cleanup of either software directory.
            _atomic(recovery_path, _recovery_bytes(recovery))
            _atomic(selection_path, new_bytes)
            return selected
        finally:
            _unlock(journal_lock_path, journal_fd)
    except (
        ActivationSlotError,
        UpdateJournalError,
        PreviousInstallationError,
        NativeEvidenceError,
    ) as error:
        raise PriorSwitchError(
            "two-sided signed selection verification failed"
        ) from error
    finally:
        os.close(selection_fd)
        lock_path.unlink(missing_ok=True)


__all__ = ("PriorSwitchError", "switch_armed_prior_bound_selection")
