"""Issue #49: journal-bound publisher, pip-file and native-byte preflight.

Read-only observation with cooperative update locks, never a trusted active
receipt, an activation decision or an execution boundary. A locally editable
journal is not independent authority for software or historical activation.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
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
from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
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
from paper_data_suite.evergreen_update_journal import (
    _lock as _journal_lock,
)
from paper_data_suite.evergreen_update_journal import (
    _paths as _journal_paths,
)
from paper_data_suite.evergreen_update_journal import (
    _read as _read_journal,
)
from paper_data_suite.evergreen_update_journal import (
    _unlock as _journal_unlock,
)


class JournalPipPreflightError(ValueError):
    """Candidate is not eligible for an unarmed, read-only update observation."""


@dataclass(frozen=True, slots=True)
class ObservedJournalPipCandidate:
    """Ephemeral exact-byte observation, never proof of installed authority."""

    transaction_id: str
    journal_revision: int
    stage_relative_path: str
    wheelhouse_relative_path: str
    native_payload_sha256: str
    pip_inventory_sha256: str
    publisher_digests: tuple[tuple[str, str], ...]
    root_console_targets: tuple[tuple[str, str, str], ...]
    external_distributions: tuple[str, ...]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect_journal_bound_publisher_pip_candidate(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    registry_checkpoint: RevisionCheckpoint | None = None,
    lock_checkpoint: RevisionCheckpoint | None = None,
    native_checkpoint: RevisionCheckpoint | None = None,
    layout: str | None = None,
) -> ObservedJournalPipCandidate:
    """Reauthenticate a *candidate_verified* real-pip stage under journal locks.

    The journal must match every exact signed input. The staged software must
    match registered PDS publisher releases, all installed pip files and
    launcher records, and root-signed native executable bytes. Checks repeat
    before return to catch ordinary concurrent drift; this is not an OS-level
    protection from malicious same-user writes or a warrant to run code.
    """
    if (
        type(expected_revision) is not int
        or expected_revision != 1
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or not all(
            type(item) is bytes
            for item in (
                prepared_record,
                registry_envelope,
                lock_envelope,
                evidence_envelope,
            )
        )
        or type(module_envelopes) is not dict
        or any(
            type(key) is not str or type(value) is not bytes
            for key, value in module_envelopes.items()
        )
        or layout not in (None, "windows" if os.name == "nt" else "posix")
    ):
        raise JournalPipPreflightError("invalid journal-bound preflight inputs")
    publisher_inputs = dict(module_envelopes)
    try:
        root = _safe_root(software_root, classroom_workspace)
        _, _, recovery_path = _selection_paths(root, classroom_workspace)
        selection_lock, selection_fd = _selection_lock(root)
    except (UpdateJournalError, ActivationSlotError) as error:
        raise JournalPipPreflightError(
            "software root is unsafe or selection is locked"
        ) from error
    try:
        try:
            journal_path, journal_lock = _journal_paths(root, transaction_id)
            journal_fd = _journal_lock(journal_lock)
        except UpdateJournalError as error:
            raise JournalPipPreflightError("candidate journal is locked") from error
        try:
            if _read_selection(recovery_path) is not None:
                raise JournalPipPreflightError("pending selection recovery")
            original = _read_journal(journal_path)
            if (
                original is None
                or original.transaction_id != transaction_id
                or original.revision != expected_revision
                or original.phase is not UpdatePhase.CANDIDATE_VERIFIED
                or original.recorded_at > now.astimezone(timezone.utc)
            ):
                raise JournalPipPreflightError("exact unarmed journal required")
            if any(
                _sha(raw) != expected
                for raw, expected in (
                    (prepared_record, original.prepared_sha256),
                    (registry_envelope, original.registry_envelope_sha256),
                    (lock_envelope, original.lock_envelope_sha256),
                    (evidence_envelope, original.native_envelope_sha256),
                )
            ):
                raise JournalPipPreflightError("journal evidence hash mismatch")
            stage = root / original.stage_relative_path
            wheels = root / original.wheelhouse_relative_path
            if (
                _relative_child(root, stage) != original.stage_relative_path
                or _relative_child(root, wheels) != original.wheelhouse_relative_path
            ):
                raise JournalPipPreflightError("candidate path changed")

            def observe() -> tuple[ObservedPublisherPipCandidate, str]:
                publisher = audit_publisher_bound_pip_candidate(
                    stage,
                    wheels,
                    prepared_record=prepared_record,
                    registry_envelope=registry_envelope,
                    lock_envelope=lock_envelope,
                    module_envelopes=publisher_inputs,
                    trust=trust,
                    now=now,
                    registry_checkpoint=registry_checkpoint,
                    lock_checkpoint=lock_checkpoint,
                    layout=layout,
                )
                native = verify_signed_staged_native_evidence(
                    stage,
                    wheels,
                    evidence_envelope=evidence_envelope,
                    prepared_record=prepared_record,
                    registry_envelope=registry_envelope,
                    lock_envelope=lock_envelope,
                    trust=trust,
                    now=now,
                    checkpoint=native_checkpoint,
                    layout=layout,
                )
                if (
                    publisher.transaction_id != transaction_id
                    or native.transaction_id != transaction_id
                    or publisher.stage_root != stage
                    or native.stage_root != stage
                    or publisher.wheelhouse != wheels
                    or native.payload_sha256 == ""
                ):
                    raise JournalPipPreflightError(
                        "publisher/native candidate identity mismatch"
                    )
                return publisher, native.payload_sha256

            before = observe()
            after = observe()
            if before != after or publisher_inputs != module_envelopes:
                raise JournalPipPreflightError(
                    "candidate evidence changed during audit"
                )
            if _read_journal(journal_path) != original:
                raise JournalPipPreflightError("candidate journal changed during audit")
            if _read_selection(recovery_path) is not None:
                raise JournalPipPreflightError("candidate recovery began during audit")
            publisher, native_sha = after
            return ObservedJournalPipCandidate(
                transaction_id,
                original.revision,
                original.stage_relative_path,
                original.wheelhouse_relative_path,
                native_sha,
                publisher.pip_inventory_sha256,
                publisher.publisher_digests,
                publisher.root_console_targets,
                publisher.external_distributions,
            )
        finally:
            _journal_unlock(journal_lock, journal_fd)
    except (
        UpdateJournalError,
        ActivationSlotError,
        NativeEvidenceError,
        PublisherPipPreflightError,
    ) as error:
        raise JournalPipPreflightError(
            "journal-bound candidate preflight failed"
        ) from error
    finally:
        os.close(selection_fd)
        selection_lock.unlink(missing_ok=True)


__all__ = (
    "JournalPipPreflightError",
    "ObservedJournalPipCandidate",
    "inspect_journal_bound_publisher_pip_candidate",
)
