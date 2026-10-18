"""Issue #49: arm a prior-bound update journal under cooperative writer locks.

This records ONLY intent. The prior observation and journal are same-user
editable and do not establish historical activation, authorization to launch,
or protected installed-state continuity. The live launcher is untouched.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
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
from paper_data_suite.evergreen_prior_update import (
    ClaimedPriorEvidence,
    PriorUpdateError,
    ProposedCandidateEvidence,
    verify_prior_bound_candidate,
)
from paper_data_suite.evergreen_update_journal import (
    UntrustedUpdateJournal,
    UpdateJournalError,
    UpdatePhase,
    _atomic_save,
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


class PriorArmingError(ValueError):
    """Prior-bound activation intent could not be safely recorded."""


def arm_prior_bound_update_intent(
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
) -> UntrustedUpdateJournal:
    """Recheck both signed software installations, then atomically arm journal.

    Serialized against cooperating candidate-selection and transaction writers.
    Never switches slots, executes binaries, installs packages or marks an
    installation active. Even a successfully armed journal is locally editable.
    A future switch must reverify prior continuity and enforce its own guards.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise PriorArmingError("timezone-aware activation clock required")
    if type(expected_revision) is not int or expected_revision < 1:
        raise PriorArmingError("exact positive journal revision required")
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, _, pending_path = _selection_paths(root, classroom_workspace)
        lock_path, selection_fd = _selection_lock(root)
    except (ActivationSlotError, UpdateJournalError) as error:
        raise PriorArmingError(
            "software root or selection lock is unavailable"
        ) from error
    try:
        journal_path, journal_lock_path = _journal_paths(root, transaction_id)
        journal_fd = _journal_lock(journal_lock_path)
        try:
            if _read_selection(pending_path) is not None:
                raise PriorArmingError("unreconciled slot selection blocks activation")
            existing = _read_journal(journal_path)
            if existing is None or existing.revision != expected_revision:
                raise PriorArmingError("missing or stale journal revision")
            if existing.phase is not UpdatePhase.CANDIDATE_VERIFIED:
                raise PriorArmingError("journal is no longer an unarmed candidate")
            if now.astimezone(timezone.utc) < existing.recorded_at:
                raise PriorArmingError("activation clock predates journal")
            observed = verify_prior_bound_candidate(
                root,
                classroom_workspace=classroom_workspace,
                transaction_id=transaction_id,
                expected_revision=expected_revision,
                candidate=candidate,
                prior=prior,
                trust=trust,
                now=now,
                layout=layout,
            )
            if (
                observed.candidate_transaction_id != existing.transaction_id
                or observed.journal_revision != existing.revision
                or observed.prior_record_sha256
                != existing.expected_previous_receipt_sha256
            ):
                raise PriorArmingError("prior-bound verification identity mismatch")
            armed = replace(
                existing,
                revision=existing.revision + 1,
                phase=UpdatePhase.ACTIVATION_INTENT,
                recorded_at=now.astimezone(timezone.utc).replace(microsecond=0),
            )
            _atomic_save(journal_path, armed)
            return armed
        finally:
            _unlock(journal_lock_path, journal_fd)
    except (ActivationSlotError, UpdateJournalError, PriorUpdateError) as error:
        raise PriorArmingError(
            "prior-bound update could not be safely armed"
        ) from error
    finally:
        os.close(selection_fd)
        lock_path.unlink(missing_ok=True)


__all__ = ("PriorArmingError", "arm_prior_bound_update_intent")
