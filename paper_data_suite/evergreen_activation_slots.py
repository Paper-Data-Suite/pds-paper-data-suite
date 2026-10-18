"""Issue #49: reversible, journal-bound candidate slot selection.

This deliberately switches ONLY an inert Suite-local candidate-selection file.
It does not switch `pds launch`, create a trusted installed-state receipt, run
code, mutate installed packages, or authenticate the previously selected slot.
Both physical slot directories remain untouched, enabling truthful recovery.
Same-user filesystem replacement defeats this local state: never use it alone
as authorization to execute a selected environment.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
    verify_signed_staged_native_evidence,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    UpdatePhase,
    _relative_child,
    _safe_root,
    load_update_intent,
)

_MAX_BYTES: Final = 8 * 1024
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_HASH: Final = re.compile(r"[0-9a-f]{64}\Z")
_REL: Final = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")


class ActivationSlotError(ValueError):
    """Candidate selection cannot be safely changed or recovered."""


@dataclass(frozen=True, slots=True)
class UntrustedSlotSelection:
    """Locally editable selection hint; never an active-installation receipt."""

    transaction_id: str
    stage_relative_path: str
    prepared_sha256: str
    native_envelope_sha256: str
    generation: int


@dataclass(frozen=True, slots=True)
class PendingSlotRecovery:
    """Expected before/after states for an incomplete, reversible switch."""

    transaction_id: str
    previous_bytes: bytes | None
    candidate_sha256: str
    previous_sha256: str | None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise ActivationSlotError("duplicate selection JSON field")
        parsed[key] = value
    return parsed


def _object(raw: bytes, label: str) -> dict[str, object]:
    if not 1 <= len(raw) <= _MAX_BYTES:
        raise ActivationSlotError(f"invalid {label} length")
    try:
        document: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except ActivationSlotError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ActivationSlotError(f"malformed {label}") from error
    if not isinstance(document, dict):
        raise ActivationSlotError(f"{label} must be a JSON object")
    return cast(dict[str, object], document)


def _canonical(data: dict[str, object]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _string(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise ActivationSlotError(f"invalid {label}")
    return value


def _parse_selection(raw: bytes) -> UntrustedSlotSelection:
    data = _object(raw, "selection")
    if (
        data.keys()
        != {
            "record_type",
            "schema_version",
            "transaction_id",
            "stage_relative_path",
            "prepared_sha256",
            "native_envelope_sha256",
            "generation",
        }
        or data["record_type"] != "pds_evergreen_candidate_selection"
        or (type(data["schema_version"]) is not int or data["schema_version"] != 1)
    ):
        raise ActivationSlotError("unsupported selection schema")
    generation = data["generation"]
    if type(generation) is not int or not 1 <= generation <= 2**53 - 1:
        raise ActivationSlotError("invalid selection generation")
    selection = UntrustedSlotSelection(
        _string(data["transaction_id"], _TX, "transaction ID"),
        _string(data["stage_relative_path"], _REL, "stage reference"),
        _string(data["prepared_sha256"], _HASH, "prepared digest"),
        _string(data["native_envelope_sha256"], _HASH, "native digest"),
        generation,
    )
    if _selection_bytes(selection) != raw:
        raise ActivationSlotError("noncanonical selection encoding")
    return selection


def _selection_bytes(selection: UntrustedSlotSelection) -> bytes:
    return _canonical(
        {
            "record_type": "pds_evergreen_candidate_selection",
            "schema_version": 1,
            "transaction_id": selection.transaction_id,
            "stage_relative_path": selection.stage_relative_path,
            "prepared_sha256": selection.prepared_sha256,
            "native_envelope_sha256": selection.native_envelope_sha256,
            "generation": selection.generation,
        }
    )


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decode_previous(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4 * ((_MAX_BYTES + 2) // 3):
        raise ActivationSlotError("invalid previous selection encoding")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ActivationSlotError("invalid previous selection base64") from error
    _parse_selection(decoded)
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ActivationSlotError("noncanonical previous selection base64")
    return decoded


def _recovery_bytes(recovery: PendingSlotRecovery) -> bytes:
    return _canonical(
        {
            "record_type": "pds_evergreen_pending_slot_recovery",
            "schema_version": 1,
            "transaction_id": recovery.transaction_id,
            "previous_selection_b64": (
                base64.b64encode(recovery.previous_bytes).decode("ascii")
                if recovery.previous_bytes is not None
                else None
            ),
            "previous_sha256": recovery.previous_sha256,
            "candidate_sha256": recovery.candidate_sha256,
        }
    )


def _parse_recovery(raw: bytes) -> PendingSlotRecovery:
    data = _object(raw, "pending recovery")
    if (
        data.keys()
        != {
            "record_type",
            "schema_version",
            "transaction_id",
            "previous_selection_b64",
            "previous_sha256",
            "candidate_sha256",
        }
        or data["record_type"] != "pds_evergreen_pending_slot_recovery"
        or (type(data["schema_version"]) is not int or data["schema_version"] != 1)
    ):
        raise ActivationSlotError("unsupported recovery schema")
    previous = _decode_previous(data["previous_selection_b64"])
    previous_digest = data["previous_sha256"]
    if previous_digest is not None:
        previous_digest = _string(previous_digest, _HASH, "previous digest")
    if (previous is None) != (previous_digest is None):
        raise ActivationSlotError("previous selection/digest mismatch")
    if previous is not None and _digest(previous) != previous_digest:
        raise ActivationSlotError("previous selection hash mismatch")
    record = PendingSlotRecovery(
        _string(data["transaction_id"], _TX, "recovery transaction"),
        previous,
        _string(data["candidate_sha256"], _HASH, "candidate digest"),
        previous_digest,
    )
    if _recovery_bytes(record) != raw:
        raise ActivationSlotError("noncanonical recovery encoding")
    return record


def _ordinary(path: Path, *, optional: bool = False) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return False
        raise ActivationSlotError("missing candidate selection file") from None
    except OSError as error:
        raise ActivationSlotError("cannot inspect selection file") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or (getattr(info, "st_file_attributes", 0) & 0x400)
    ):
        raise ActivationSlotError("unsafe selection file or reparse point")
    return True


def _read(path: Path) -> bytes | None:
    if not _ordinary(path, optional=True):
        return None
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
    except OSError as error:
        raise ActivationSlotError("could not read candidate selection") from error
    if not 1 <= len(raw) <= _MAX_BYTES:
        raise ActivationSlotError("invalid candidate selection length")
    return raw


def _atomic(path: Path, raw: bytes) -> None:
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            mode="wb",
            prefix=".pds-selector-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        temp = None
    except OSError as error:
        raise ActivationSlotError("candidate selection atomic write failed") from error
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _lock(root: Path) -> tuple[Path, int]:
    path = root / "candidate-selection.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as error:
        raise ActivationSlotError("candidate selection already locked") from error
    return path, descriptor


def _paths(software_root: Path, classroom_workspace: Path) -> tuple[Path, Path, Path]:
    try:
        root = _safe_root(software_root, classroom_workspace)
    except UpdateJournalError as error:
        raise ActivationSlotError("unsafe software/classroom root boundary") from error
    return root, root / "candidate-selection.json", root / "pending-slot-recovery.json"


def read_candidate_selection(
    software_root: Path, *, classroom_workspace: Path
) -> UntrustedSlotSelection | None:
    """Read untrusted candidate pointer; reject unhandled crash markers."""
    _, selected, pending = _paths(software_root, classroom_workspace)
    if _read(pending) is not None:
        raise ActivationSlotError("pending slot recovery requires reconciliation")
    raw = _read(selected)
    return _parse_selection(raw) if raw is not None else None


def read_pending_slot_recovery(
    software_root: Path, *, classroom_workspace: Path
) -> PendingSlotRecovery | None:
    """Inspect expected rollback state; no file mutation or launch approval."""
    _, _, pending = _paths(software_root, classroom_workspace)
    raw = _read(pending)
    return _parse_recovery(raw) if raw is not None else None


def switch_verified_candidate_selection(
    software_root: Path,
    *,
    classroom_workspace: Path,
    transaction_id: str,
    prepared_record: bytes,
    registry_envelope: bytes,
    lock_envelope: bytes,
    evidence_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None = None,
) -> UntrustedSlotSelection:
    """Atomically select a reverified stage under journal intent.

    Leaves previous stage and wheelhouse bytes *entirely untouched*. A pending
    recovery capsule is written BEFORE pointer mutation. This cannot grant
    permission to launch; future verifier must reconstruct signed evidence.
    """
    root, selection_path, recovery_path = _paths(software_root, classroom_workspace)
    _string(transaction_id, _TX, "transaction ID")
    lock_path, descriptor = _lock(root)
    try:
        if _read(recovery_path) is not None:
            raise ActivationSlotError("prior candidate switch needs recovery")
        journal = load_update_intent(
            root,
            classroom_workspace=classroom_workspace,
            transaction_id=transaction_id,
        )
        if journal is None or journal.phase is not UpdatePhase.ACTIVATION_INTENT:
            raise ActivationSlotError("verified activation intent is required")
        if any(
            _digest(raw) != expected
            for raw, expected in (
                (prepared_record, journal.prepared_sha256),
                (registry_envelope, journal.registry_envelope_sha256),
                (lock_envelope, journal.lock_envelope_sha256),
                (evidence_envelope, journal.native_envelope_sha256),
            )
        ):
            raise ActivationSlotError("activation evidence differs from journal")
        candidate = root / journal.stage_relative_path
        wheelhouse = root / journal.wheelhouse_relative_path
        try:
            if _relative_child(root, candidate) != journal.stage_relative_path:
                raise ActivationSlotError("candidate stage reference changed")
            if _relative_child(root, wheelhouse) != journal.wheelhouse_relative_path:
                raise ActivationSlotError("wheelhouse stage reference changed")
            observed = verify_signed_staged_native_evidence(
                candidate,
                wheelhouse,
                evidence_envelope=evidence_envelope,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                trust=trust,
                now=now,
                layout=layout,
            )
        except (UpdateJournalError, NativeEvidenceError) as error:
            raise ActivationSlotError(
                "candidate stage failed reauthentication"
            ) from error
        if (
            observed.transaction_id != transaction_id
            or observed.stage_root != candidate
        ):
            raise ActivationSlotError("candidate identity mismatch")
        if journal.expected_previous_receipt_sha256 is not None:
            raise ActivationSlotError(
                "previous receipt authority is not yet supported by slot selection"
            )
        previous_bytes = _read(selection_path)
        previous = (
            _parse_selection(previous_bytes) if previous_bytes is not None else None
        )
        if previous is not None:
            if previous.transaction_id == transaction_id:
                raise ActivationSlotError("candidate is already selected")
            # Preserve the physical prior slot so a pointer rollback is real.
            # This check does NOT authenticate its package or executable bytes.
            try:
                _relative_child(root, root / previous.stage_relative_path)
            except UpdateJournalError as error:
                raise ActivationSlotError(
                    "previous software slot is missing or unsafe"
                ) from error
            generation = previous.generation + 1
        else:
            generation = 1
        if generation > 2**53 - 1:
            raise ActivationSlotError("selection generation exhausted")
        selected = UntrustedSlotSelection(
            transaction_id,
            journal.stage_relative_path,
            journal.prepared_sha256,
            journal.native_envelope_sha256,
            generation,
        )
        candidate_bytes = _selection_bytes(selected)
        recovery = PendingSlotRecovery(
            transaction_id,
            previous_bytes,
            _digest(candidate_bytes),
            _digest(previous_bytes) if previous_bytes is not None else None,
        )
        _atomic(recovery_path, _recovery_bytes(recovery))
        # CRASH BOUNDARY: before this atomic replace, recovery knows prior state.
        _atomic(selection_path, candidate_bytes)
        return selected
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def restore_previous_selection(
    software_root: Path, *, classroom_workspace: Path, transaction_id: str
) -> UntrustedSlotSelection | None:
    """Reconcile either side of an interrupted selection switch idempotently.

    If current bytes equal neither the candidate nor the saved preimage, refuse
    to overwrite an ambiguous selection. Never delete physical installation
    directories; that is what makes software rollback feasible in later slices.
    """
    root, selection_path, recovery_path = _paths(software_root, classroom_workspace)
    lock_path, descriptor = _lock(root)
    try:
        raw = _read(recovery_path)
        if raw is None:
            raise ActivationSlotError("no pending candidate switch to recover")
        recovery = _parse_recovery(raw)
        if recovery.transaction_id != transaction_id:
            raise ActivationSlotError("recovery transaction mismatch")
        current = _read(selection_path)
        current_digest = _digest(current) if current is not None else None
        if current_digest not in {
            recovery.candidate_sha256,
            recovery.previous_sha256,
        }:
            raise ActivationSlotError("ambiguous candidate selection: manual recovery")
        if current_digest == recovery.candidate_sha256:
            if recovery.previous_bytes is None:
                try:
                    selection_path.unlink()
                except OSError as error:
                    raise ActivationSlotError(
                        "could not restore empty selection"
                    ) from error
            else:
                _atomic(selection_path, recovery.previous_bytes)
        # CRASH BOUNDARY: if we crash here, retry sees the saved preimage.
        try:
            recovery_path.unlink()
        except OSError as error:
            raise ActivationSlotError("could not clear recovery marker") from error
        previous = recovery.previous_bytes
        return _parse_selection(previous) if previous is not None else None
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


__all__ = (
    "ActivationSlotError",
    "PendingSlotRecovery",
    "UntrustedSlotSelection",
    "read_candidate_selection",
    "read_pending_slot_recovery",
    "restore_previous_selection",
    "switch_verified_candidate_selection",
)
