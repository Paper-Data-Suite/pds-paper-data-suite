"""Issue #49: crash-conscious *intent* journal for future managed updates.

Only independently reverified, signed staged candidates may enter this
journal. No software installation, execution, active-pointer switch, rollback,
or production launch is performed. Files are locally replaceable and NEVER
constitute an authenticated active-installation receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    parse_unverified_prepared_record,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)

_MAX_JOURNAL: Final = 16 * 1024
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_UTC: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class UpdateJournalError(ValueError):
    """An update journal is inconsistent, unsafe or not properly verified."""


class UpdatePhase(str, Enum):
    """A durable *intent*, not an installed or activated composition."""

    CANDIDATE_VERIFIED = "candidate_verified"
    ACTIVATION_INTENT = "activation_intent"
    RECOVERY_REQUIRED = "recovery_required"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class UntrustedUpdateJournal:
    """Locally persisted hints, never proof that software may be launched."""

    transaction_id: str
    revision: int
    phase: UpdatePhase
    recorded_at: datetime
    stage_relative_path: str
    wheelhouse_relative_path: str
    prepared_sha256: str
    registry_envelope_sha256: str
    lock_envelope_sha256: str
    native_envelope_sha256: str
    expected_previous_receipt_sha256: str | None

    @property
    def recovery_required(self) -> bool:
        return self.phase in (
            UpdatePhase.ACTIVATION_INTENT,
            UpdatePhase.RECOVERY_REQUIRED,
        )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise UpdateJournalError("duplicate update journal JSON field")
        output[key] = value
    return output


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise UpdateJournalError(f"invalid {label}")
    return value


def _time(value: object) -> datetime:
    text = _identifier(value, _UTC, "journal timestamp")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise UpdateJournalError("invalid journal UTC timestamp") from error


def _ordinary_directory(path: Path) -> None:
    try:
        details = path.lstat()
    except OSError as error:
        raise UpdateJournalError("managed software directory does not exist") from error
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or getattr(details, "st_file_attributes", 0) & 0x400
    ):
        raise UpdateJournalError("unsafe managed software directory or reparse point")


def _safe_root(root: Path, classroom_workspace: Path) -> Path:
    if not isinstance(root, Path) or not isinstance(classroom_workspace, Path):
        raise UpdateJournalError("explicit software and classroom roots are required")
    software = Path(os.path.abspath(root))
    classroom = Path(os.path.abspath(classroom_workspace))
    if (
        software == classroom
        or software in classroom.parents
        or classroom in software.parents
    ):
        raise UpdateJournalError(
            "software updates must stay outside classroom workspace"
        )
    for directory in (classroom, *classroom.parents):
        _ordinary_directory(directory)
    for directory in (software, *software.parents):
        _ordinary_directory(directory)
    return software


def _relative_child(root: Path, target: Path) -> str:
    if not isinstance(target, Path):
        raise UpdateJournalError("invalid managed update path")
    path = target.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise UpdateJournalError("managed update path escapes software root") from error
    if not relative.parts:
        raise UpdateJournalError("managed update path must be a child")
    current = root
    for element in relative.parts:
        if element in (".", ".."):
            raise UpdateJournalError("unsafe managed update path")
        current = current / element
        _ordinary_directory(current)
    return relative.as_posix()


def _paths(root: Path, transaction_id: str) -> tuple[Path, Path]:
    tx = _identifier(transaction_id, _TX, "transaction ID")
    folder = root / "transactions"
    _ordinary_directory(folder)
    return folder / f"{tx}.json", folder / f"{tx}.lock"


def _serialize(record: UntrustedUpdateJournal) -> bytes:
    document = {
        "record_type": "pds_evergreen_update_intent",
        "schema_version": 1,
        "transaction_id": record.transaction_id,
        "revision": record.revision,
        "phase": record.phase.value,
        "recorded_at": record.recorded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage_relative_path": record.stage_relative_path,
        "wheelhouse_relative_path": record.wheelhouse_relative_path,
        "prepared_sha256": record.prepared_sha256,
        "registry_envelope_sha256": record.registry_envelope_sha256,
        "lock_envelope_sha256": record.lock_envelope_sha256,
        "native_envelope_sha256": record.native_envelope_sha256,
        "expected_previous_receipt_sha256": record.expected_previous_receipt_sha256,
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > _MAX_JOURNAL:
        raise UpdateJournalError("update journal exceeds size limit")
    return raw


def _parse(raw: bytes) -> UntrustedUpdateJournal:
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_JOURNAL:
        raise UpdateJournalError("invalid update journal byte length")
    try:
        document: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except UpdateJournalError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise UpdateJournalError("malformed update journal JSON") from error
    if not isinstance(document, dict):
        raise UpdateJournalError("update journal must be an object")
    data = cast(dict[str, object], document)
    if data.keys() != {
        "record_type",
        "schema_version",
        "transaction_id",
        "revision",
        "phase",
        "recorded_at",
        "stage_relative_path",
        "wheelhouse_relative_path",
        "prepared_sha256",
        "registry_envelope_sha256",
        "lock_envelope_sha256",
        "native_envelope_sha256",
        "expected_previous_receipt_sha256",
    }:
        raise UpdateJournalError("unknown or missing update journal fields")
    if (
        data["record_type"] != "pds_evergreen_update_intent"
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise UpdateJournalError("unsupported update journal schema")
    revision = data["revision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise UpdateJournalError("invalid update journal revision")
    try:
        phase = UpdatePhase(data["phase"])
    except (ValueError, TypeError) as error:
        raise UpdateJournalError("invalid update journal phase") from error
    previous = data["expected_previous_receipt_sha256"]
    if previous is not None:
        previous = _identifier(previous, _HASH, "previous receipt SHA-256")
    for label in ("stage_relative_path", "wheelhouse_relative_path"):
        value = data[label]
        if (
            type(value) is not str
            or not 1 <= len(value) <= 180
            or "\\" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise UpdateJournalError("invalid staged directory reference")
    record = UntrustedUpdateJournal(
        _identifier(data["transaction_id"], _TX, "transaction ID"),
        revision,
        phase,
        _time(data["recorded_at"]),
        cast(str, data["stage_relative_path"]),
        cast(str, data["wheelhouse_relative_path"]),
        _identifier(data["prepared_sha256"], _HASH, "prepared SHA-256"),
        _identifier(data["registry_envelope_sha256"], _HASH, "registry SHA-256"),
        _identifier(data["lock_envelope_sha256"], _HASH, "lock SHA-256"),
        _identifier(data["native_envelope_sha256"], _HASH, "native SHA-256"),
        previous,
    )
    if _serialize(record) != raw:
        raise UpdateJournalError("update journal must use canonical encoding")
    return record


def _read(path: Path) -> UntrustedUpdateJournal | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_ISLNK(details.st_mode)
            or getattr(details, "st_file_attributes", 0) & 0x400
        ):
            raise UpdateJournalError("update journal is a link or unsafe file")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_JOURNAL + 1)
    except OSError as error:
        raise UpdateJournalError("update journal is unreadable") from error
    return _parse(raw)


def _atomic_save(path: Path, record: UntrustedUpdateJournal) -> None:
    """Atomic same-directory file replacement; no claim of durable OS protection."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pds-intent-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as writer:
            temporary = Path(writer.name)
            writer.write(_serialize(record))
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # Atomic replace succeeded; directory flush is best effort.
                pass
    except OSError as error:
        raise UpdateJournalError(
            "could not atomically persist update intent"
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _lock(path: Path) -> int:
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as error:
        raise UpdateJournalError(
            "transaction is locked or cannot be updated"
        ) from error


def _unlock(path: Path, fd: int) -> None:
    os.close(fd)
    path.unlink(missing_ok=True)


def load_update_intent(
    software_root: Path, *, classroom_workspace: Path, transaction_id: str
) -> UntrustedUpdateJournal | None:
    """Read a locally editable intent; never infer launch eligibility from it."""
    software = _safe_root(software_root, classroom_workspace)
    path, _ = _paths(software, transaction_id)
    return _read(path)


def _verify_candidate(
    software: Path,
    stage_root: Path,
    wheelhouse: Path,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None,
) -> tuple[str, str, str]:
    stage_ref = _relative_child(software, stage_root)
    wheels_ref = _relative_child(software, wheelhouse)
    try:
        prepared = parse_unverified_prepared_record(prepared_record)
        verified = verify_signed_staged_native_evidence(
            stage_root,
            wheelhouse,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
    except (PreparedRecordError, NativeEvidenceError) as error:
        raise UpdateJournalError(
            "candidate did not pass signed stage verification"
        ) from error
    if verified.transaction_id != prepared.transaction_id:
        raise UpdateJournalError("inconsistent signed stage transaction")
    return stage_ref, wheels_ref, prepared.transaction_id


def begin_verified_update_intent(
    software_root: Path,
    *,
    classroom_workspace: Path,
    stage_root: Path,
    wheelhouse: Path,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    previous_receipt_sha256: str | None = None,
    layout: str | None = None,
) -> UntrustedUpdateJournal:
    """Persist intent only after independent signed staged-byte verification.

    The previous-receipt hash is an EXPECTATION and is not authenticated here.
    No active pointer is changed and no candidate may be launched from a journal.
    """
    software = _safe_root(software_root, classroom_workspace)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise UpdateJournalError("aware update clock required")
    if previous_receipt_sha256 is not None:
        _identifier(previous_receipt_sha256, _HASH, "previous receipt SHA-256")
    stage_ref, wheels_ref, tx = _verify_candidate(
        software,
        stage_root,
        wheelhouse,
        prepared_record=prepared_record,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        evidence_envelope=evidence_envelope,
        trust=trust,
        now=now,
        layout=layout,
    )
    path, lock_path = _paths(software, tx)
    fd = _lock(lock_path)
    try:
        if _read(path) is not None:
            raise UpdateJournalError("transaction already exists; cannot reset history")
        record = UntrustedUpdateJournal(
            tx,
            1,
            UpdatePhase.CANDIDATE_VERIFIED,
            now.astimezone(timezone.utc).replace(microsecond=0),
            stage_ref,
            wheels_ref,
            hashlib.sha256(prepared_record).hexdigest(),
            hashlib.sha256(registry_envelope).hexdigest(),
            hashlib.sha256(lock_envelope).hexdigest(),
            hashlib.sha256(evidence_envelope).hexdigest(),
            previous_receipt_sha256,
        )
        _atomic_save(path, record)
        return record
    finally:
        _unlock(lock_path, fd)


def _reverify_record(
    software: Path,
    record: UntrustedUpdateJournal,
    *,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None,
) -> None:
    if any(
        hashlib.sha256(raw).hexdigest() != digest
        for raw, digest in (
            (prepared_record, record.prepared_sha256),
            (registry_envelope, record.registry_envelope_sha256),
            (lock_envelope, record.lock_envelope_sha256),
            (evidence_envelope, record.native_envelope_sha256),
        )
    ):
        raise UpdateJournalError("update journal evidence bytes have changed")
    stage = software / record.stage_relative_path
    wheels = software / record.wheelhouse_relative_path
    stage_ref, wheels_ref, tx = _verify_candidate(
        software,
        stage,
        wheels,
        prepared_record=prepared_record,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        evidence_envelope=evidence_envelope,
        trust=trust,
        now=now,
        layout=layout,
    )
    if (stage_ref, wheels_ref, tx) != (
        record.stage_relative_path,
        record.wheelhouse_relative_path,
        record.transaction_id,
    ):
        raise UpdateJournalError("update intent no longer matches candidate")


def request_activation_intent(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None = None,
) -> UntrustedUpdateJournal:
    """Write a durable SWITCH-INTENT marker, but do NOT perform a switch.

    A future activator must independently reconcile real prior/current slots;
    an interrupted intent must never auto-promote the candidate on restart.
    """
    software = _safe_root(software_root, classroom_workspace)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise UpdateJournalError("aware activation clock required")
    path, lock_path = _paths(software, transaction_id)
    fd = _lock(lock_path)
    try:
        prior = _read(path)
        if prior is None or prior.revision != expected_revision:
            raise UpdateJournalError("missing or stale update journal revision")
        if prior.phase is not UpdatePhase.CANDIDATE_VERIFIED:
            raise UpdateJournalError("update intent may only be requested once")
        if now.astimezone(timezone.utc) < prior.recorded_at:
            raise UpdateJournalError("activation clock predates candidate verification")
        _reverify_record(
            software,
            prior,
            prepared_record=prepared_record,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            evidence_envelope=evidence_envelope,
            trust=trust,
            now=now,
            layout=layout,
        )
        current = replace(
            prior,
            revision=prior.revision + 1,
            phase=UpdatePhase.ACTIVATION_INTENT,
            recorded_at=now.astimezone(timezone.utc).replace(microsecond=0),
        )
        _atomic_save(path, current)
        return current
    finally:
        _unlock(lock_path, fd)


def classify_recovery(record: UntrustedUpdateJournal) -> str:
    """Non-mutating guidance; never assumes the active files were switched."""
    if not isinstance(record, UntrustedUpdateJournal):
        raise UpdateJournalError("invalid update journal observation")
    if record.phase is UpdatePhase.CANDIDATE_VERIFIED:
        return "candidate_only_no_activation_attempted"
    if record.phase in (UpdatePhase.ACTIVATION_INTENT, UpdatePhase.RECOVERY_REQUIRED):
        return "manual_active_install_reconciliation_required"
    return "candidate_aborted_no_activation_attempted"


def record_safe_disposition(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    expected_revision: int,
    phase: UpdatePhase,
    now: datetime,
) -> UntrustedUpdateJournal:
    """Record aborted candidate or recovery requirement, without mutating apps."""
    if not isinstance(phase, UpdatePhase) or phase not in (
        UpdatePhase.ABORTED,
        UpdatePhase.RECOVERY_REQUIRED,
    ):
        raise UpdateJournalError("journal cannot mark an installation activated")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise UpdateJournalError("aware update clock required")
    software = _safe_root(software_root, classroom_workspace)
    path, lock_path = _paths(software, transaction_id)
    fd = _lock(lock_path)
    try:
        prior = _read(path)
        if prior is None or prior.revision != expected_revision:
            raise UpdateJournalError("missing or stale update journal revision")
        allowed = (
            prior.phase is UpdatePhase.CANDIDATE_VERIFIED
            if phase is UpdatePhase.ABORTED
            else prior.phase is UpdatePhase.ACTIVATION_INTENT
        )
        if not allowed:
            raise UpdateJournalError("unsafe update disposition transition")
        if now.astimezone(timezone.utc) < prior.recorded_at:
            raise UpdateJournalError("update clock predates previous journal state")
        next_record = replace(
            prior,
            phase=phase,
            revision=prior.revision + 1,
            recorded_at=now.astimezone(timezone.utc).replace(microsecond=0),
        )
        _atomic_save(path, next_record)
        return next_record
    finally:
        _unlock(lock_path, fd)


__all__ = (
    "UntrustedUpdateJournal",
    "UpdateJournalError",
    "UpdatePhase",
    "begin_verified_update_intent",
    "classify_recovery",
    "load_update_intent",
    "record_safe_disposition",
    "request_activation_intent",
)
