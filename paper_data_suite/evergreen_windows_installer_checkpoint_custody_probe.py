"""Issue #49 Slice 119: observe fixed Windows checkpoint/journal custody.

READ-ONLY, NON-AUTHORIZING. All path checks are non-handle-based snapshots;
this Python process can be raced or compromised. A native service must open
OS-anchored protected handles, validate security under an exclusive lock,
verify antirollback independently, and commit durably before any activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Final

from paper_data_suite.evergreen_windows_custody import (
    CustodyAuditError,
    _powershell_acl,
    inspect_acl_document,
)
from paper_data_suite.evergreen_windows_deployment_preflight import (
    inspect_state_parent_acl,
)
from paper_data_suite.evergreen_windows_installer_checkpoint_cas import (
    InstallerCheckpointCasError,
    parse_claimed_checkpoint,
)
from paper_data_suite.evergreen_windows_installer_checkpoint_recovery import (
    InstallerCheckpointRecoveryError,
    parse_claimed_checkpoint_journal,
)

_APP: Final = "Paper Data Suite"
_STATE: Final = "service-state"
_CHECKPOINT: Final = "installer-checkpoint-v1.json"
_JOURNAL: Final = "installer-intent-journal-v1.json"
_LIMIT: Final = 4096
_REPARSE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)


class InstallerCheckpointCustodyProbeError(ValueError):
    """Read-only Windows path, ACL or checkpoint inventory was refused."""


@dataclass(frozen=True, slots=True)
class CheckpointCustodyObservation:
    """Sanitized snapshot; no verified native handles or transition authority."""

    status: str
    checked_entries: int
    checkpoint_present: bool
    journal_present: bool
    checkpoint_generation: int | None = None
    journal_phase: str | None = None
    checkpoint_sha256: str | None = None
    journal_sha256: str | None = None
    relationship: str = "NOT_EVALUATED"
    os_handle_custody_verified: bool = False
    privileged_service_authenticated: bool = False
    durable_state_verified: bool = False
    independent_antirollback_verified: bool = False
    permitted_to_resume: bool = False
    permitted_to_replace: bool = False
    permitted_to_publish_receipt: bool = False
    permitted_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def _inspect_node(path: Path, *, is_dir: bool) -> bool:
    """Reject reparse/symlink/other types; return False only on missing file."""
    try:
        item = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise InstallerCheckpointCustodyProbeError(
            "protected state stat failed"
        ) from exc
    if (
        stat.S_ISLNK(item.st_mode)
        or bool(getattr(item, "st_file_attributes", 0) & _REPARSE)
        or not (stat.S_ISDIR(item.st_mode) if is_dir else stat.S_ISREG(item.st_mode))
    ):
        raise InstallerCheckpointCustodyProbeError("unsafe protected state node")
    return True


def _acl(path: Path, *, read_acl: Callable[[Path], object], parent: bool) -> None:
    try:
        data = read_acl(path)
        if parent:
            inspect_state_parent_acl(data)
        else:
            inspect_acl_document(data)
    except (CustodyAuditError, OSError, TypeError, ValueError) as exc:
        raise InstallerCheckpointCustodyProbeError(
            "protected state ACL refused"
        ) from exc


def _bounded_file(path: Path) -> bytes:
    """Read only up to 4097 bytes. Not race-safe and never proof of custody."""
    try:
        with path.open("rb") as stream:
            value = stream.read(_LIMIT + 1)
    except OSError as exc:
        raise InstallerCheckpointCustodyProbeError(
            "protected state read failed"
        ) from exc
    if not 1 <= len(value) <= _LIMIT:
        raise InstallerCheckpointCustodyProbeError(
            "protected state record size invalid"
        )
    return value


def inspect_claimed_windows_checkpoint_paths(
    program_data: Path, *, read_acl: Callable[[Path], object]
) -> CheckpointCustodyObservation:
    """Observe fixed proposed child names; caller controls path/ACL evidence.

    For local tests only, `program_data` and `read_acl` are injectable. Only
    inspect_windows_checkpoint_custody() selects the intended Windows path.
    Neither form establishes OS-anchored handles or prevents TOCTOU.
    """
    if (
        not isinstance(program_data, Path)
        or not program_data.is_absolute()
        or not callable(read_acl)
    ):
        raise InstallerCheckpointCustodyProbeError("invalid Windows custody inputs")
    protected = program_data / _APP
    state = protected / _STATE
    checkpoint = state / _CHECKPOINT
    journal = state / _JOURNAL
    checked = 0
    for path, parent in ((program_data, True), (protected, False), (state, False)):
        if not _inspect_node(path, is_dir=True):
            # Missing preprovisioned parents do not authorize genesis.
            if path == program_data:
                raise InstallerCheckpointCustodyProbeError("ProgramData root missing")
            return CheckpointCustodyObservation(
                "PROTECTED_CHECKPOINT_PROVISIONING_REQUIRED", checked, False, False
            )
        _acl(path, read_acl=read_acl, parent=parent)
        checked += 1
    # Refuse either unsafe child before reading any bytes.
    checkpoint_present = _inspect_node(checkpoint, is_dir=False)
    journal_present = _inspect_node(journal, is_dir=False)
    for path, present in ((checkpoint, checkpoint_present), (journal, journal_present)):
        if present:
            _acl(path, read_acl=read_acl, parent=False)
            checked += 1
    if not checkpoint_present or not journal_present:
        return CheckpointCustodyObservation(
            (
                "PROTECTED_CHECKPOINT_GENESIS_NOT_ESTABLISHED"
                if not checkpoint_present and not journal_present
                else "PROTECTED_CHECKPOINT_INCOMPLETE_REFUSE_RECOVERY"
            ),
            checked,
            checkpoint_present,
            journal_present,
        )
    raw_checkpoint = _bounded_file(checkpoint)
    raw_journal = _bounded_file(journal)
    try:
        parsed = parse_claimed_checkpoint(raw_checkpoint)
        record = parse_claimed_checkpoint_journal(raw_journal)
    except (InstallerCheckpointCasError, InstallerCheckpointRecoveryError) as exc:
        raise InstallerCheckpointCustodyProbeError(
            "malformed protected state bytes"
        ) from exc
    checkpoint_hash = hashlib.sha256(raw_checkpoint).hexdigest()
    journal_hash = hashlib.sha256(raw_journal).hexdigest()
    generation = parsed["generation"]
    phase = record["phase"]
    if (
        generation == 0
        and checkpoint_hash == record["previous_checkpoint_sha256"]
        and phase == "INTENT_PREPARED"
    ):
        relation = "PREPARED_PREVIOUS_STATE_OBSERVED"
    elif (
        generation == 1
        and checkpoint_hash == record["proposed_checkpoint_sha256"]
        and parsed["last_transaction_id"] == record["transaction_id"]
        and parsed["last_request_sha256"] == record["request_sha256"]
    ):
        relation = (
            "REPLACEMENT_WITH_UNFINALIZED_JOURNAL_OBSERVED"
            if phase == "INTENT_PREPARED"
            else "REPLACEMENT_CLAIMED_COMMIT_UNVERIFIED"
        )
    else:
        raise InstallerCheckpointCustodyProbeError(
            "journal/checkpoint bytes inconsistent with transaction"
        )
    return CheckpointCustodyObservation(
        status="PROTECTED_CHECKPOINT_PATHS_OBSERVED_NO_NATIVE_CUSTODY",
        checked_entries=checked,
        checkpoint_present=True,
        journal_present=True,
        checkpoint_generation=int(generation),
        journal_phase=str(phase),
        checkpoint_sha256=checkpoint_hash,
        journal_sha256=journal_hash,
        relationship=relation,
    )


def inspect_windows_checkpoint_custody() -> CheckpointCustodyObservation:
    """Read-only fixed Windows ProgramData inventory; never production proof."""
    if os.name != "nt":
        raise InstallerCheckpointCustodyProbeError("Windows is required")
    root = os.environ.get("ProgramData", "")
    if not root or not Path(root).is_absolute():
        raise InstallerCheckpointCustodyProbeError("Windows ProgramData unavailable")
    return inspect_claimed_windows_checkpoint_paths(
        Path(root).absolute(), read_acl=_powershell_acl
    )


def main(argv: list[str] | None = None) -> int:
    """Fixed-path diagnostic only. No user-supplied path/approval/apply flag."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = inspect_windows_checkpoint_custody()
    except InstallerCheckpointCustodyProbeError as exc:
        print(f"REFUSED: {exc}. {_NO_AUTHORITY}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(report), indent=2))
    print(_NO_AUTHORITY)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
