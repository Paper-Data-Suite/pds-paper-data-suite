"""Issue #49 Slice 43: durable *untrusted* successor proposal and signed readback.

The local proposal must exist BEFORE a service-side witness CAS may be contemplated.
It is not an active receipt. Nothing here invokes CAS, authorizes a launch,
changes the selection, or clears pending recovery. Local locks are cooperative.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_activation_slots import (
    ActivationSlotError,
    _parse_recovery,
    _parse_selection,
    _selection_bytes,
)
from paper_data_suite.evergreen_activation_slots import _lock as _selection_lock
from paper_data_suite.evergreen_activation_slots import _paths as _selection_paths
from paper_data_suite.evergreen_activation_slots import _read as _selection_read
from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    parse_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_successor_receipt_draft import (
    WitnessBoundSuccessorDraft,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    _serialize,
)
from paper_data_suite.evergreen_update_journal import _lock as _journal_lock
from paper_data_suite.evergreen_update_journal import _paths as _journal_paths
from paper_data_suite.evergreen_update_journal import _read as _journal_read
from paper_data_suite.evergreen_update_journal import _unlock as _journal_unlock
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    inspect_uncertain_witness_commit,
    make_witness_commit_request,
    parse_witness_commit_request,
    serialize_witness_commit_request,
)

_MAX_RECORD: Final = 80 * 1024
_MAX_REQUEST: Final = 48 * 1024


class LocalReceiptRecoveryError(ValueError):
    """Missing, altered, or inconsistent pending receipt evidence."""


@dataclass(frozen=True, slots=True)
class StoredSuccessorProposal:
    """Exact local proposal bytes persisted; no active-installation authority."""

    transaction_id: str
    successor_sha256: str
    predecessor_sha256: str
    expected_witness_revision: int
    record_sha256: str
    status: str = "UNTRUSTED_PROPOSAL_STORED_RECOVERY_REMAINS_PENDING"


@dataclass(frozen=True, slots=True)
class ForwardRecoveryObservation:
    """Signed head comparison only; no launch, cleanup or rollback permission."""

    transaction_id: str
    generation: int
    witness_revision: int
    observed_receipt_sha256: str
    status: str
    authority: str = "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"


@dataclass(frozen=True, slots=True)
class _LocalSnapshot:
    transaction_id: str
    journal_sha256: str
    selection_sha256: str
    recovery_sha256: str
    expected_witness_revision: int
    request: WitnessCommitRequest


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(document: dict[str, object]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _utc(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise LocalReceiptRecoveryError("whole-second aware clock required")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in pairs:
        if k in result:
            raise LocalReceiptRecoveryError("duplicate receipt proposal field")
        result[k] = v
    return result


def _ordinary_read(path: Path) -> bytes | None:
    """Bounded ordinary-file inspection, never follow a proposal symlink."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise LocalReceiptRecoveryError("proposal file cannot be inspected") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or getattr(before, "st_file_attributes", 0) & 0x400
        or not 1 <= before.st_size <= _MAX_RECORD
    ):
        raise LocalReceiptRecoveryError("unsafe or oversized receipt proposal")
    try:
        with path.open("rb") as source:
            opened = os.fstat(source.fileno())
            if (
                opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or opened.st_size != before.st_size
            ):
                raise LocalReceiptRecoveryError("proposal changed while opening")
            content = source.read(_MAX_RECORD + 1)
        after = path.lstat()
    except OSError as error:
        raise LocalReceiptRecoveryError("cannot read receipt proposal") from error
    if (
        len(content) != before.st_size
        or after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_size != before.st_size
    ):
        raise LocalReceiptRecoveryError("proposal changed while reading")
    return content


def _atomic_new(path: Path, raw: bytes) -> None:
    """Atomic same-directory proposal write, guarded by cooperating locks.

    Windows rename atomicity is not a guarantee of power-loss durability or
    protection from malicious same-user filesystem changes.
    """
    temp: Path | None = None
    try:
        if _ordinary_read(path) is not None:
            raise LocalReceiptRecoveryError("successor proposal already exists")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pds-proposal-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temp = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if _ordinary_read(path) is not None:
            raise LocalReceiptRecoveryError("proposal unexpectedly appeared")
        os.replace(temp, path)
        temp = None
        if os.name != "nt":
            try:
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
    except OSError as error:
        raise LocalReceiptRecoveryError("atomic proposal persistence failed") from error
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _snapshot(
    root: Path,
    classroom_workspace: Path,
    transaction_id: str,
    request: WitnessCommitRequest,
) -> _LocalSnapshot:
    _, selection_file, pending_file = _selection_paths(root, classroom_workspace)
    journal_file, _ = _journal_paths(root, transaction_id)
    selection_bytes = _selection_read(selection_file)
    recovery_bytes = _selection_read(pending_file)
    journal = _journal_read(journal_file)
    if selection_bytes is None or recovery_bytes is None or journal is None:
        raise LocalReceiptRecoveryError("pending pointer, capsule and intent required")
    selected = _parse_selection(selection_bytes)
    pending = _parse_recovery(recovery_bytes)
    if pending.previous_bytes is None:
        raise LocalReceiptRecoveryError("missing exact predecessor preimage")
    old_selection = _parse_selection(pending.previous_bytes)
    previous = parse_untrusted_active_receipt(request.previous_receipt_bytes)
    successor = parse_untrusted_active_receipt(request.successor_receipt_bytes)
    paths = (
        root / previous.stage_relative_path,
        root / previous.wheelhouse_relative_path,
        root / successor.stage_relative_path,
        root / successor.wheelhouse_relative_path,
    )
    for directory in paths:
        _relative_child(root, directory)
    if any(
        a == b or a in b.parents or b in a.parents
        for index, a in enumerate(paths)
        for b in paths[index + 1 :]
    ):
        raise LocalReceiptRecoveryError("prior and candidate directories overlap")
    if (
        journal.transaction_id != transaction_id
        or journal.revision != 2
        or journal.phase is not UpdatePhase.ACTIVATION_INTENT
        or journal.expected_previous_receipt_sha256 is None
        or pending.transaction_id != transaction_id
        or pending.candidate_sha256 != _sha(selection_bytes)
        or pending.previous_sha256 != _sha(pending.previous_bytes)
        or selected.transaction_id != transaction_id
        or selected.stage_relative_path != journal.stage_relative_path
        or selected.prepared_sha256 != journal.prepared_sha256
        or selected.native_envelope_sha256 != journal.native_envelope_sha256
        or selected.generation != previous.generation + 1
        or successor.transaction_id != selected.transaction_id
        or successor.stage_relative_path != selected.stage_relative_path
        or successor.wheelhouse_relative_path != journal.wheelhouse_relative_path
        or successor.generation != selected.generation
        or successor.prepared_sha256 != journal.prepared_sha256
        or successor.registry_sha256 != journal.registry_envelope_sha256
        or successor.lock_sha256 != journal.lock_envelope_sha256
        or successor.native_envelope_sha256 != journal.native_envelope_sha256
        or successor.previous_receipt_sha256 != request.predecessor_sha256
        or old_selection.transaction_id != previous.transaction_id
        or old_selection.stage_relative_path != previous.stage_relative_path
        or old_selection.generation != previous.generation
        or old_selection.prepared_sha256 != previous.prepared_sha256
        or old_selection.native_envelope_sha256 != previous.native_envelope_sha256
        or previous.recorded_at > journal.recorded_at
        or successor.recorded_at < journal.recorded_at
        or selection_bytes != _selection_bytes(selected)
    ):
        raise LocalReceiptRecoveryError("local journal, capsule or receipts differ")
    return _LocalSnapshot(
        transaction_id,
        _sha(_serialize(journal)),
        _sha(selection_bytes),
        _sha(recovery_bytes),
        request.expected_witness_revision,
        request,
    )


def _document(snapshot: _LocalSnapshot, now: datetime) -> bytes:
    request_bytes = serialize_witness_commit_request(snapshot.request)
    return _canonical(
        {
            "record_type": "pds_untrusted_successor_receipt_proposal",
            "schema_version": 1,
            "transaction_id": snapshot.transaction_id,
            "recorded_at": _utc(now),
            "journal_sha256": snapshot.journal_sha256,
            "selection_sha256": snapshot.selection_sha256,
            "recovery_sha256": snapshot.recovery_sha256,
            "request_sha256": _sha(request_bytes),
            "request_b64": base64.b64encode(request_bytes).decode("ascii"),
            "status": "proposal_only_not_active",
        }
    )


def _parse(raw: bytes) -> tuple[_LocalSnapshot, str]:
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_RECORD:
        raise LocalReceiptRecoveryError("invalid durable proposal length")
    try:
        data: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except LocalReceiptRecoveryError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise LocalReceiptRecoveryError("invalid proposal JSON") from error
    if not isinstance(data, dict):
        raise LocalReceiptRecoveryError("proposal must be a JSON object")
    item = cast(dict[str, object], data)
    if (
        item.keys()
        != {
            "record_type",
            "schema_version",
            "transaction_id",
            "recorded_at",
            "journal_sha256",
            "selection_sha256",
            "recovery_sha256",
            "request_sha256",
            "request_b64",
            "status",
        }
        or item["record_type"] != "pds_untrusted_successor_receipt_proposal"
        or (type(item["schema_version"]) is not int or item["schema_version"] != 1)
        or item["status"] != "proposal_only_not_active"
    ):
        raise LocalReceiptRecoveryError("unknown durable proposal schema")
    transaction = item["transaction_id"]
    clock = item["recorded_at"]
    if type(clock) is not str:
        raise LocalReceiptRecoveryError("invalid proposal timestamp")
    try:
        parsed_time = datetime.strptime(clock, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise LocalReceiptRecoveryError("invalid proposal timestamp") from error
    if _utc(parsed_time) != clock:
        raise LocalReceiptRecoveryError("noncanonical proposal timestamp")
    digests = [
        item[n]
        for n in (
            "journal_sha256",
            "selection_sha256",
            "recovery_sha256",
            "request_sha256",
        )
    ]
    if any(
        type(v) is not str
        or len(v) != 64
        or any(c not in "0123456789abcdef" for c in v)
        for v in digests
    ):
        raise LocalReceiptRecoveryError("invalid receipt proposal digest")
    encoded = item["request_b64"]
    if type(encoded) is not str or not 1 <= len(encoded) <= 4 * (
        (_MAX_REQUEST + 2) // 3
    ):
        raise LocalReceiptRecoveryError("invalid request base64 length")
    try:
        request_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise LocalReceiptRecoveryError("invalid request base64") from error
    if (
        not 1 <= len(request_bytes) <= _MAX_REQUEST
        or base64.b64encode(request_bytes).decode("ascii") != encoded
        or _sha(request_bytes) != item["request_sha256"]
    ):
        raise LocalReceiptRecoveryError("changed successor request")
    request = parse_witness_commit_request(request_bytes)
    if (
        transaction
        != parse_untrusted_active_receipt(
            request.successor_receipt_bytes
        ).transaction_id
    ):
        raise LocalReceiptRecoveryError("durable proposal transaction differs")
    result = _LocalSnapshot(
        transaction,
        cast(str, item["journal_sha256"]),
        cast(str, item["selection_sha256"]),
        cast(str, item["recovery_sha256"]),
        request.expected_witness_revision,
        request,
    )
    if _document(result, parsed_time) != raw:
        raise LocalReceiptRecoveryError("noncanonical durable proposal")
    return result, clock


def _with_locks(
    software_root: Path,
    classroom_workspace: Path,
    transaction_id: str,
) -> tuple[Path, Path, int, Path, int, Path]:
    """Locks selection then journal; caller MUST always release both."""
    root = _safe_root(software_root, classroom_workspace)
    selection_lock_path, selection_fd = _selection_lock(root)
    try:
        _, journal_lock_path = _journal_paths(root, transaction_id)
        journal_fd = _journal_lock(journal_lock_path)
    except Exception:
        os.close(selection_fd)
        selection_lock_path.unlink(missing_ok=True)
        raise
    proposal = root / "transactions" / f"{transaction_id}.successor-proposal.json"
    return (
        root,
        selection_lock_path,
        selection_fd,
        journal_lock_path,
        journal_fd,
        proposal,
    )


def _release(
    selection_lock: Path, selection_fd: int, journal_lock: Path, journal_fd: int
) -> None:
    _journal_unlock(journal_lock, journal_fd)
    os.close(selection_fd)
    selection_lock.unlink(missing_ok=True)


def persist_untrusted_successor_proposal(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    draft: WitnessBoundSuccessorDraft,
    previous_receipt_bytes: bytes,
    installation_id: str,
    witness_id: str,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
) -> StoredSuccessorProposal:
    """Store an exact proposal BEFORE a possible CAS. Never invoke CAS itself.

    Rechecks a signed *predecessor* head under both locks. This does not rerun
    signed publisher/pip/native audits, or establish physical activation.
    """
    _utc(now)
    try:
        request = make_witness_commit_request(
            draft,
            installation_id=installation_id,
            witness_id=witness_id,
            previous_receipt_bytes=previous_receipt_bytes,
        )
        root, sl, sf, jl, jf, path = _with_locks(
            software_root, classroom_workspace, transaction_id
        )
    except (
        WitnessCommitProtocolError,
        ActivationSlotError,
        UpdateJournalError,
    ) as error:
        raise LocalReceiptRecoveryError("invalid or locked proposal inputs") from error
    try:
        if _ordinary_read(path) is not None:
            raise LocalReceiptRecoveryError("proposal already persisted; no replay")
        initial = _snapshot(root, classroom_workspace, transaction_id, request)
        if parse_untrusted_active_receipt(
            request.previous_receipt_bytes
        ).recorded_at > now.astimezone(timezone.utc) or parse_untrusted_active_receipt(
            request.successor_receipt_bytes
        ).recorded_at > now.astimezone(timezone.utc):
            raise LocalReceiptRecoveryError("receipt timestamp is in the future")
        if (
            draft.transaction_id != transaction_id
            or draft.expected_witness_revision != initial.expected_witness_revision
        ):
            raise LocalReceiptRecoveryError("proposal transaction or revision differs")
        signed = inspect_uncertain_witness_commit(
            request,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            minimum_witness_revision=request.expected_witness_revision,
        )
        if signed.status != "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED":
            raise LocalReceiptRecoveryError(
                "successor already witnessed; cannot prepare"
            )
        if _snapshot(root, classroom_workspace, transaction_id, request) != initial:
            raise LocalReceiptRecoveryError("local state changed across witness read")
        raw = _document(initial, now)
        if not 1 <= len(raw) <= _MAX_RECORD:
            raise LocalReceiptRecoveryError("proposal exceeds record size limit")
        _atomic_new(path, raw)
        return StoredSuccessorProposal(
            transaction_id,
            request.successor_sha256,
            request.predecessor_sha256,
            request.expected_witness_revision,
            _sha(raw),
        )
    except (
        ActiveReceiptError,
        ActivationSlotError,
        UpdateJournalError,
        WitnessCommitProtocolError,
    ) as error:
        raise LocalReceiptRecoveryError(
            "untrusted proposal persistence refused"
        ) from error
    finally:
        _release(sl, sf, jl, jf)


def inspect_pending_forward_recovery(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    witness_transport: CheckpointWitnessTransport,
    pinned_public_key: bytes,
    now: datetime,
) -> ForwardRecoveryObservation:
    """Read signed previous/successor witness head against the durable proposal.

    Does not recover software, resolve an in-flight CAS, or treat any locally
    persisted file as active receipt authority. Never delete a recovery capsule.
    """
    _utc(now)
    try:
        root, sl, sf, jl, jf, path = _with_locks(
            software_root, classroom_workspace, transaction_id
        )
    except (ActivationSlotError, UpdateJournalError) as error:
        raise LocalReceiptRecoveryError(
            "invalid or locked forward-recovery inputs"
        ) from error
    try:
        raw = _ordinary_read(path)
        if raw is None:
            raise LocalReceiptRecoveryError(
                "no durable proposal; manual reconciliation"
            )
        persisted, _ = _parse(raw)
        if persisted.transaction_id != transaction_id:
            raise LocalReceiptRecoveryError("wrong forward-recovery transaction")
        current = _snapshot(
            root, classroom_workspace, transaction_id, persisted.request
        )
        if current != persisted:
            raise LocalReceiptRecoveryError("local pointer, capsule or journal drift")
        signed = inspect_uncertain_witness_commit(
            persisted.request,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            minimum_witness_revision=persisted.expected_witness_revision,
        )
        if (
            _ordinary_read(path) != raw
            or _snapshot(root, classroom_workspace, transaction_id, persisted.request)
            != current
        ):
            raise LocalReceiptRecoveryError(
                "forward-recovery state changed during read"
            )
        if signed.status not in (
            "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED",
            "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED",
        ):
            raise LocalReceiptRecoveryError("unrecognized signed head state")
        return ForwardRecoveryObservation(
            transaction_id,
            signed.generation,
            signed.witness_revision,
            signed.receipt_sha256,
            signed.status,
        )
    except (
        ActiveReceiptError,
        ActivationSlotError,
        UpdateJournalError,
        WitnessCommitProtocolError,
    ) as error:
        raise LocalReceiptRecoveryError(
            "guarded forward-recovery inspection refused"
        ) from error
    finally:
        _release(sl, sf, jl, jf)


__all__ = (
    "ForwardRecoveryObservation",
    "LocalReceiptRecoveryError",
    "StoredSuccessorProposal",
    "inspect_pending_forward_recovery",
    "persist_untrusted_successor_proposal",
)
