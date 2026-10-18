"""Issue #49: reverify both sides of a proposed software update.

The previous receipt, slot pointer, and update journal are locally replaceable.
Their agreement does NOT attest historical activation, persistent root trust or
permission to launch. This is a read-only, time-of-check observation and must
be repeated inside a future protected activation transaction.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_previous_install import (
    PreviousInstallationError,
    verify_previous_slot_record,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    load_update_intent,
)


class PriorUpdateError(ValueError):
    """A proposed update has insufficient or inconsistent prior-byte evidence."""


@dataclass(frozen=True, slots=True)
class ProposedCandidateEvidence:
    """Untrusted signed-envelope INPUT BYTES, not a verified candidate object."""

    prepared_record: bytes
    registry_envelope: bytes
    lock_envelope: bytes
    native_envelope: bytes


@dataclass(frozen=True, slots=True)
class ClaimedPriorEvidence:
    """Locally held prior observation and fresh signed-envelope input bytes."""

    observation_record: bytes
    wheelhouse: Path
    prepared_record: bytes
    registry_envelope: bytes
    lock_envelope: bytes
    native_envelope: bytes


@dataclass(frozen=True, slots=True)
class ObservedUpdateContinuity:
    """Both sides match their current signed bytes; NOT an active receipt."""

    candidate_transaction_id: str
    journal_revision: int
    prior_transaction_id: str
    prior_generation: int
    prior_record_sha256: str
    candidate_stage_relative_path: str
    prior_stage_relative_path: str
    candidate_wheelhouse_relative_path: str
    prior_wheelhouse_relative_path: str


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _separate(a: Path, b: Path) -> bool:
    """Neither directory may contain the other; both must survive rollback."""
    return a != b and a not in b.parents and b not in a.parents


def verify_prior_bound_candidate(
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
) -> ObservedUpdateContinuity:
    """Freshly check BOTH installations before an activation-intent request.

    No mutations, subprocesses, imports, package installs, activation or journal
    writes occur. A prior record hash copied into a local journal is a binding,
    NOT an independently protected continuity counter or active-state proof.
    This check is not atomic with later updates; a future controlled writer
    MUST repeat it while holding its update/selection coordination locks.
    """
    if not isinstance(candidate, ProposedCandidateEvidence) or not isinstance(
        prior, ClaimedPriorEvidence
    ):
        raise PriorUpdateError("both raw candidate and prior evidence are required")
    if not isinstance(trust, TrustedKeyring):
        raise PriorUpdateError("an independently provisioned keyring is required")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise PriorUpdateError("an aware validation time is required")
    if type(expected_revision) is not int or expected_revision < 1:
        raise PriorUpdateError("an exact positive journal revision is required")
    try:
        root = _safe_root(software_root, classroom_workspace)
        journal = load_update_intent(
            root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
        )
        if journal is None or journal.revision != expected_revision:
            raise PriorUpdateError("update journal is absent or stale")
        if journal.phase is not UpdatePhase.CANDIDATE_VERIFIED:
            raise PriorUpdateError("only an unarmed verified candidate is eligible")
        expected_hash = journal.expected_previous_receipt_sha256
        if expected_hash is None:
            raise PriorUpdateError("update journal has no previous receipt binding")
        for raw, fingerprint in (
            (candidate.prepared_record, journal.prepared_sha256),
            (candidate.registry_envelope, journal.registry_envelope_sha256),
            (candidate.lock_envelope, journal.lock_envelope_sha256),
            (candidate.native_envelope, journal.native_envelope_sha256),
        ):
            if type(raw) is not bytes or _digest(raw) != fingerprint:
                raise PriorUpdateError("candidate evidence differs from journal")
        stage = root / journal.stage_relative_path
        wheels = root / journal.wheelhouse_relative_path
        if (
            _relative_child(root, stage) != journal.stage_relative_path
            or _relative_child(root, wheels) != journal.wheelhouse_relative_path
        ):
            raise PriorUpdateError("candidate software directory has moved")
        if _digest(prior.observation_record) != expected_hash:
            raise PriorUpdateError("prior record does not match journal binding")
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
            expected_record_sha256=expected_hash,
            layout=layout,
        )
        observed = verify_signed_staged_native_evidence(
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
        previous_stage = root / previous.observation.stage_relative_path
        previous_wheels = root / previous.observation.wheelhouse_relative_path
        if observed.transaction_id != transaction_id or observed.stage_root != stage:
            raise PriorUpdateError("candidate transaction identity differs")
        if previous.observation.transaction_id == transaction_id:
            raise PriorUpdateError("prior and candidate transaction IDs coincide")
        roots = (stage, wheels, previous_stage, previous_wheels)
        if not all(
            _separate(first, second)
            for index, first in enumerate(roots)
            for second in roots[index + 1 :]
        ):
            raise PriorUpdateError("prior/candidate directories overlap")
        if journal.recorded_at > now:
            raise PriorUpdateError("candidate journal timestamp is in the future")
        return ObservedUpdateContinuity(
            transaction_id,
            journal.revision,
            previous.observation.transaction_id,
            previous.observation.selection_generation,
            previous.record_sha256,
            journal.stage_relative_path,
            previous.observation.stage_relative_path,
            journal.wheelhouse_relative_path,
            previous.observation.wheelhouse_relative_path,
        )
    except (
        UpdateJournalError,
        PreviousInstallationError,
        NativeEvidenceError,
    ) as error:
        raise PriorUpdateError("signed prior/update preflight failed") from error


__all__ = (
    "ClaimedPriorEvidence",
    "ObservedUpdateContinuity",
    "PriorUpdateError",
    "ProposedCandidateEvidence",
    "verify_prior_bound_candidate",
)
