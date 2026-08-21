"""Independent integrity verification for completed whole-workspace backups.

Verification treats a backup as opaque filesystem custody. It validates the
suite-owned manifest and byte inventory without parsing Core- or module-owned
records and without resolving or mutating the active workspace.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from paper_data_suite.workspace_backup import (
    BACKUP_COPY_CHUNK_BYTES,
    BACKUP_MANIFEST_FILENAME,
    BACKUP_NAME_PREFIX,
    BACKUP_PAYLOAD_ROOT,
    BackupFileEntry,
    WorkspaceBackupError,
    WorkspaceBackupManifest,
    WorkspaceBackupVerificationError,
    inventory_workspace,
    parse_workspace_backup_manifest,
    serialize_workspace_backup_manifest,
)


@dataclass(frozen=True, slots=True)
class WorkspaceBackupVerificationResult:
    """Verified facts for one completed backup."""

    backup_root: Path
    manifest: WorkspaceBackupManifest
    manifest_sha256: str

    @property
    def payload_root(self) -> Path:
        return self.backup_root / BACKUP_PAYLOAD_ROOT

    @property
    def manifest_path(self) -> Path:
        return self.backup_root / BACKUP_MANIFEST_FILENAME


def _redirecting_reparse(status: os.stat_result) -> bool:
    attributes = getattr(status, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not reparse_flag or not attributes & reparse_flag:
        return False
    tag = getattr(status, "st_reparse_tag", None)
    redirect_tags = {
        value
        for value in (
            getattr(stat, "IO_REPARSE_TAG_SYMLINK", None),
            getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None),
        )
        if value is not None
    }
    return tag in redirect_tags


def _canonical_backup_root(path: str | Path) -> Path:
    raw = os.fspath(path)
    if not raw.strip():
        raise WorkspaceBackupVerificationError("Backup path cannot be empty.")
    expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
    try:
        supplied_status = expanded.lstat()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Backup does not exist or cannot be inspected: {expanded}"
        ) from error
    if stat.S_ISLNK(supplied_status.st_mode) or _redirecting_reparse(
        supplied_status
    ):
        raise WorkspaceBackupVerificationError(
            "Backup root must not be a redirecting filesystem entry."
        )
    if not stat.S_ISDIR(supplied_status.st_mode):
        raise WorkspaceBackupVerificationError(
            f"Backup root is not a directory: {expanded}"
        )
    try:
        root = expanded.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspaceBackupVerificationError(
            f"Backup does not exist or cannot be resolved: {expanded}"
        ) from error
    try:
        status = root.lstat()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Could not inspect backup root: {root}"
        ) from error
    if stat.S_ISLNK(status.st_mode) or _redirecting_reparse(status):
        raise WorkspaceBackupVerificationError(
            "Backup root must not be a redirecting filesystem entry."
        )
    if not stat.S_ISDIR(status.st_mode):
        raise WorkspaceBackupVerificationError(
            f"Backup root is not a directory: {root}"
        )
    if root.name.startswith(".") and ".incomplete-" in root.name:
        raise WorkspaceBackupVerificationError(
            "Incomplete backup staging is not a completed backup."
        )
    return root


def _top_level_entry_status(path: Path, *, expected: str) -> os.stat_result:
    try:
        status = path.lstat()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Completed backup is missing required {expected}: {path.name}"
        ) from error
    if stat.S_ISLNK(status.st_mode) or _redirecting_reparse(status):
        raise WorkspaceBackupVerificationError(
            f"Completed backup {expected} must not be a linked filesystem entry: "
            f"{path.name}"
        )
    return status


def _validate_top_level(backup_root: Path) -> tuple[Path, Path]:
    try:
        with os.scandir(backup_root) as scan:
            names = tuple(sorted(entry.name for entry in scan))
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Could not enumerate backup root: {backup_root}"
        ) from error

    expected = (BACKUP_MANIFEST_FILENAME, BACKUP_PAYLOAD_ROOT)
    if names != expected:
        missing = tuple(name for name in expected if name not in names)
        extra = tuple(name for name in names if name not in expected)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected top-level entries present")
        suffix = "; ".join(details) or "top-level layout mismatch"
        raise WorkspaceBackupVerificationError(
            f"Completed backup top-level layout is invalid: {suffix}."
        )

    manifest_path = backup_root / BACKUP_MANIFEST_FILENAME
    payload_root = backup_root / BACKUP_PAYLOAD_ROOT
    manifest_status = _top_level_entry_status(manifest_path, expected="manifest")
    payload_status = _top_level_entry_status(payload_root, expected="payload")
    if not stat.S_ISREG(manifest_status.st_mode):
        raise WorkspaceBackupVerificationError(
            "Completed backup manifest.json is not an ordinary file."
        )
    if not stat.S_ISDIR(payload_status.st_mode):
        raise WorkspaceBackupVerificationError(
            "Completed backup workspace payload is not an ordinary directory."
        )
    return manifest_path, payload_root


def _load_manifest(
    manifest_path: Path,
    backup_root: Path,
) -> tuple[WorkspaceBackupManifest, bytes]:
    try:
        payload = manifest_path.read_bytes()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            "Could not read backup manifest.json."
        ) from error
    try:
        manifest = parse_workspace_backup_manifest(payload)
    except WorkspaceBackupError:
        raise
    except (TypeError, ValueError) as error:
        raise WorkspaceBackupVerificationError(
            "Backup manifest.json failed v1 validation."
        ) from error

    if backup_root.name != manifest.backup_id:
        if ".incomplete-" in backup_root.name:
            raise WorkspaceBackupVerificationError(
                "Incomplete backup staging is not a completed backup."
            )
        raise WorkspaceBackupVerificationError(
            "Backup directory name does not match manifest backup_id."
        )
    if not backup_root.name.startswith(BACKUP_NAME_PREFIX):
        raise WorkspaceBackupVerificationError(
            "Backup directory name is not a canonical completed backup name."
        )

    canonical = serialize_workspace_backup_manifest(manifest)
    if payload != canonical:
        raise WorkspaceBackupVerificationError(
            "Backup manifest bytes are not the canonical deterministic v1 "
            "serialization."
        )
    return manifest, payload


def _payload_path(payload_root: Path, relative: str) -> Path:
    return payload_root.joinpath(*PurePosixPath(relative).parts)


def _hash_payload_file(
    payload_root: Path,
    expected: BackupFileEntry,
    *,
    chunk_size: int,
) -> BackupFileEntry:
    path = _payload_path(payload_root, expected.path)
    try:
        before = path.lstat()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Backup payload file cannot be inspected: {expected.path}"
        ) from error
    if stat.S_ISLNK(before.st_mode) or _redirecting_reparse(before):
        raise WorkspaceBackupVerificationError(
            f"Backup payload contains linked filesystem entry: {expected.path}"
        )
    if not stat.S_ISREG(before.st_mode):
        raise WorkspaceBackupVerificationError(
            f"Backup payload entry is not an ordinary file: {expected.path}"
        )

    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise WorkspaceBackupVerificationError(
                    f"Backup payload file changed type while opening: {expected.path}"
                )
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
    except WorkspaceBackupError:
        raise
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Backup payload file cannot be read: {expected.path}"
        ) from error

    try:
        after = path.lstat()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            f"Backup payload file changed while being verified: {expected.path}"
        ) from error
    if stat.S_ISLNK(after.st_mode) or _redirecting_reparse(after):
        raise WorkspaceBackupVerificationError(
            f"Backup payload file changed type while being verified: {expected.path}"
        )
    if not stat.S_ISREG(after.st_mode):
        raise WorkspaceBackupVerificationError(
            f"Backup payload file changed type while being verified: {expected.path}"
        )
    if total != before.st_size or total != after.st_size:
        raise WorkspaceBackupVerificationError(
            f"Backup payload file changed size while being verified: {expected.path}"
        )
    return BackupFileEntry(
        path=expected.path,
        size=total,
        sha256=digest.hexdigest(),
    )


def _verify_inventory(
    payload_root: Path,
    manifest: WorkspaceBackupManifest,
    *,
    chunk_size: int,
) -> None:
    try:
        inventory = inventory_workspace(payload_root)
    except WorkspaceBackupError as error:
        raise WorkspaceBackupVerificationError(str(error)) from error

    expected_directories = manifest.directories
    observed_directories = inventory.directories
    if observed_directories != expected_directories:
        raise WorkspaceBackupVerificationError(
            "Backup payload directory inventory does not match the manifest."
        )

    expected_sizes = tuple((entry.path, entry.size) for entry in manifest.files)
    observed_sizes = tuple((entry.path, entry.size) for entry in inventory.files)
    if observed_sizes != expected_sizes:
        raise WorkspaceBackupVerificationError(
            "Backup payload file inventory or sizes do not match the manifest."
        )
    if inventory.total_bytes != manifest.total_bytes:
        raise WorkspaceBackupVerificationError(
            "Backup payload total byte count does not match the manifest."
        )

    for expected in manifest.files:
        actual = _hash_payload_file(
            payload_root,
            expected,
            chunk_size=chunk_size,
        )
        if actual != expected:
            raise WorkspaceBackupVerificationError(
                f"Backup payload SHA-256 mismatch: {expected.path}"
            )

    try:
        final_inventory = inventory_workspace(payload_root)
    except WorkspaceBackupError as error:
        raise WorkspaceBackupVerificationError(str(error)) from error
    if final_inventory != inventory:
        raise WorkspaceBackupVerificationError(
            "Backup payload changed while verification was running."
        )


def verify_workspace_backup(
    backup: str | Path,
    *,
    chunk_size: int = BACKUP_COPY_CHUNK_BYTES,
) -> WorkspaceBackupVerificationResult:
    """Independently verify one completed v1 backup without mutating it."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    backup_root = _canonical_backup_root(backup)
    manifest_path, payload_root = _validate_top_level(backup_root)
    manifest, manifest_bytes = _load_manifest(manifest_path, backup_root)
    _verify_inventory(payload_root, manifest, chunk_size=chunk_size)
    return WorkspaceBackupVerificationResult(
        backup_root=backup_root,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


__all__ = (
    "WorkspaceBackupVerificationResult",
    "verify_workspace_backup",
)
