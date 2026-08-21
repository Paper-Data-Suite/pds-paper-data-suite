"""Planning and execution for verified whole-workspace restore operations.

Restore remains opaque filesystem custody. A completed backup is independently
verified before planning and again immediately before mutation. Restored bytes
are staged outside both the backup and active workspace, independently checked,
and published only to a previously nonexistent explicit alternate location.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import secrets
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from paper_data_suite.workspace_backup import (
    BACKUP_COPY_CHUNK_BYTES,
    BackupFileEntry,
    WorkspaceBackupError,
    WorkspaceBackupManifest,
    inventory_workspace,
    required_backup_free_bytes,
)
from paper_data_suite.workspace_backup_verification import (
    WorkspaceBackupVerificationResult,
    verify_workspace_backup,
)
from paper_data_suite.workspace_setup import (
    CoreWorkspaceServices,
    load_core_workspace_services,
)


class WorkspaceRestoreError(RuntimeError):
    """Base class for bounded restore failures."""


class WorkspaceRestoreCoreError(WorkspaceRestoreError):
    """Raised when Core cannot provide a usable resolved-workspace observation."""


class WorkspaceRestoreDestinationError(WorkspaceRestoreError):
    """Raised when the requested alternate restore destination is unsafe."""


class WorkspaceRestoreSpaceError(WorkspaceRestoreDestinationError):
    """Raised when destination free space is below the conservative threshold."""


class WorkspaceRestoreDriftError(WorkspaceRestoreError):
    """Raised when the reviewed backup or Core workspace state changes."""


class WorkspaceRestoreCopyError(WorkspaceRestoreError):
    """Raised when opaque restore copying cannot complete safely."""


class WorkspaceRestoreVerificationError(WorkspaceRestoreError):
    """Raised when staged restored bytes do not match the backup manifest."""


class WorkspaceRestoreCollisionError(WorkspaceRestoreDestinationError):
    """Raised when restore staging or the final destination already exists."""


class WorkspaceRestorePublicationError(WorkspaceRestoreError):
    """Raised when verified restore staging cannot be published safely."""


class DiskUsageLike(Protocol):
    """Read-only free-space field consumed from a disk-usage provider."""

    @property
    def free(self) -> int: ...


DiskUsageReader = Callable[[str | os.PathLike[str]], DiskUsageLike]
BackupVerifier = Callable[[str | Path], WorkspaceBackupVerificationResult]
CoreServicesLoader = Callable[[], CoreWorkspaceServices]
StagingNonceFactory = Callable[[], str]
FileCopier = Callable[[Path, Path, BackupFileEntry, int], BackupFileEntry]
AfterCopyHook = Callable[[Path, Path], None]
BeforePublishHook = Callable[[Path, Path], None]


@dataclass(frozen=True, slots=True)
class WorkspaceRestorePlan:
    """Fully verified, read-only restore proposal shown before mutation."""

    verification: WorkspaceBackupVerificationResult
    workspace_root: Path
    workspace_source: str
    destination_root: Path
    destination_parent: Path
    destination_anchor: Path
    destination_free_bytes: int
    required_free_bytes: int
    destination_parent_exists: bool

    @property
    def backup_root(self) -> Path:
        return self.verification.backup_root

    @property
    def payload_root(self) -> Path:
        return self.verification.payload_root

    @property
    def manifest_sha256(self) -> str:
        return self.verification.manifest_sha256


@dataclass(frozen=True, slots=True)
class WorkspaceRestoreResult:
    """Verified alternate workspace after non-overwriting publication."""

    destination_root: Path
    manifest: WorkspaceBackupManifest
    manifest_sha256: str


def _read_disk_usage(path: str | os.PathLike[str]) -> DiskUsageLike:
    return shutil.disk_usage(path)


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or _contains(first, second) or _contains(second, first)


def _expanded_path(path: str | Path, label: str) -> Path:
    raw = os.fspath(path)
    if not raw.strip():
        raise WorkspaceRestoreDestinationError(f"{label} cannot be empty.")
    expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
    try:
        return expanded.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise WorkspaceRestoreDestinationError(
            f"Could not resolve {label.lower()}."
        ) from error


def _path_entry_exists(path: str | Path) -> bool:
    try:
        return os.path.lexists(os.fspath(path))
    except (OSError, TypeError, ValueError) as error:
        raise WorkspaceRestoreDestinationError(
            "Could not inspect restore destination existence."
        ) from error


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while True:
        if candidate.exists():
            if not candidate.is_dir():
                raise WorkspaceRestoreDestinationError(
                    "Restore destination has no usable existing directory ancestor."
                )
            try:
                return candidate.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise WorkspaceRestoreDestinationError(
                    "Could not resolve restore destination filesystem anchor."
                ) from error
        if _path_entry_exists(candidate):
            raise WorkspaceRestoreDestinationError(
                "Restore destination passes through an unusable filesystem entry."
            )
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    raise WorkspaceRestoreDestinationError(
        "Restore destination has no usable existing directory ancestor."
    )


def _destination_free_bytes(
    anchor: Path,
    disk_usage_reader: DiskUsageReader,
) -> int:
    try:
        usage = disk_usage_reader(anchor)
        free = usage.free
    except (OSError, TypeError, ValueError, AttributeError) as error:
        raise WorkspaceRestoreDestinationError(
            f"Could not inspect free space for restore destination: {anchor}"
        ) from error
    if not isinstance(free, int) or isinstance(free, bool) or free < 0:
        raise WorkspaceRestoreDestinationError(
            "Destination free-space provider returned an invalid value."
        )
    return free


def _resolved_workspace(services: CoreWorkspaceServices) -> tuple[Path, str]:
    try:
        status = services.inspect_workspace_root()
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspaceRestoreCoreError(
            f"Core could not inspect the currently resolved workspace: {message}"
        ) from error
    try:
        raw_root = Path(status.root)
        source = status.source
    except (AttributeError, TypeError, ValueError) as error:
        raise WorkspaceRestoreCoreError(
            "Core returned an invalid workspace status result."
        ) from error
    if not isinstance(source, str) or not source.strip():
        raise WorkspaceRestoreCoreError(
            "Core returned an invalid workspace resolution source."
        )
    try:
        root = raw_root.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise WorkspaceRestoreCoreError(
            f"Could not resolve the Core workspace path: {raw_root}"
        ) from error
    return root, source


def _assert_restore_separation(
    destination_root: Path,
    *,
    backup_root: Path,
    payload_root: Path,
    workspace_root: Path,
) -> None:
    if _overlaps(destination_root, backup_root) or _overlaps(
        destination_root, payload_root
    ):
        raise WorkspaceRestoreDestinationError(
            "Restore destination must not overlap the source backup."
        )
    if _overlaps(destination_root, workspace_root):
        raise WorkspaceRestoreDestinationError(
            "Restore destination must not overlap the currently resolved workspace."
        )


def plan_workspace_restore(
    backup: str | Path,
    destination: str | Path,
    *,
    services: CoreWorkspaceServices | None = None,
    services_loader: CoreServicesLoader = load_core_workspace_services,
    verifier: BackupVerifier = verify_workspace_backup,
    disk_usage_reader: DiskUsageReader = _read_disk_usage,
) -> WorkspaceRestorePlan:
    """Build a full read-only restore proposal without creating destination state."""
    verification = verifier(backup)
    active_services = services or services_loader()
    workspace_root, workspace_source = _resolved_workspace(active_services)

    expanded_destination = Path(
        os.path.expandvars(os.path.expanduser(os.fspath(destination)))
    )
    destination_root = _expanded_path(destination, "Restore destination")
    _assert_restore_separation(
        destination_root,
        backup_root=verification.backup_root,
        payload_root=verification.payload_root,
        workspace_root=workspace_root,
    )
    if _path_entry_exists(expanded_destination) or _path_entry_exists(
        destination_root
    ):
        raise WorkspaceRestoreDestinationError(
            f"Restore destination already exists and will not be modified: "
            f"{destination_root}"
        )

    destination_parent = destination_root.parent
    destination_anchor = _nearest_existing_directory(destination_parent)
    free_bytes = _destination_free_bytes(destination_anchor, disk_usage_reader)
    required_bytes = required_backup_free_bytes(
        verification.manifest.total_bytes
    )
    if free_bytes < required_bytes:
        raise WorkspaceRestoreSpaceError(
            "Insufficient destination free space for restore: "
            f"required {required_bytes} bytes, available {free_bytes} bytes."
        )

    return WorkspaceRestorePlan(
        verification=verification,
        workspace_root=workspace_root,
        workspace_source=workspace_source,
        destination_root=destination_root,
        destination_parent=destination_parent,
        destination_anchor=destination_anchor,
        destination_free_bytes=free_bytes,
        required_free_bytes=required_bytes,
        destination_parent_exists=destination_parent.exists(),
    )


def _same_verification(
    expected: WorkspaceBackupVerificationResult,
    observed: WorkspaceBackupVerificationResult,
) -> bool:
    return (
        expected.backup_root == observed.backup_root
        and expected.manifest == observed.manifest
        and expected.manifest_sha256 == observed.manifest_sha256
    )


def _recheck_restore_sources(
    plan: WorkspaceRestorePlan,
    *,
    services: CoreWorkspaceServices,
    verifier: BackupVerifier,
) -> WorkspaceBackupVerificationResult:
    try:
        observed = verifier(plan.backup_root)
    except WorkspaceBackupError as error:
        raise WorkspaceRestoreDriftError(
            "The backup no longer verifies as reviewed after restore preview."
        ) from error
    if not _same_verification(plan.verification, observed):
        raise WorkspaceRestoreDriftError(
            "The backup changed after restore preview; "
            "verify and plan the restore again."
        )
    workspace_root, workspace_source = _resolved_workspace(services)
    if (
        workspace_root != plan.workspace_root
        or workspace_source != plan.workspace_source
    ):
        raise WorkspaceRestoreDriftError(
            "The currently resolved workspace changed after restore preview."
        )
    return observed


def _prepare_destination_for_execution(
    plan: WorkspaceRestorePlan,
    *,
    disk_usage_reader: DiskUsageReader,
) -> Path:
    destination = _expanded_path(plan.destination_root, "Restore destination")
    if destination != plan.destination_root:
        raise WorkspaceRestoreDestinationError(
            "Restore destination resolved differently after confirmation; "
            "rerun preview."
        )
    _assert_restore_separation(
        destination,
        backup_root=plan.backup_root,
        payload_root=plan.payload_root,
        workspace_root=plan.workspace_root,
    )
    if _path_entry_exists(destination):
        raise WorkspaceRestoreCollisionError(
            "Restore destination already exists and will not be modified: "
            f"{destination}"
        )

    precreate_anchor = _nearest_existing_directory(destination.parent)
    precreate_free_bytes = _destination_free_bytes(
        precreate_anchor,
        disk_usage_reader,
    )
    if precreate_free_bytes < plan.required_free_bytes:
        raise WorkspaceRestoreSpaceError(
            "Insufficient destination free space for restore: "
            f"required {plan.required_free_bytes} bytes, "
            f"available {precreate_free_bytes} bytes."
        )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise WorkspaceRestoreDestinationError(
            f"Could not create restore destination parent: {destination.parent}"
        ) from error
    try:
        parent = destination.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspaceRestoreDestinationError(
            "Could not resolve restore destination parent after creation."
        ) from error
    if parent != plan.destination_parent:
        raise WorkspaceRestoreDestinationError(
            "Restore destination parent resolved differently after confirmation; "
            "rerun preview."
        )
    final_root = parent / destination.name
    _assert_restore_separation(
        final_root,
        backup_root=plan.backup_root,
        payload_root=plan.payload_root,
        workspace_root=plan.workspace_root,
    )
    if final_root != plan.destination_root:
        raise WorkspaceRestoreDestinationError(
            "Restore destination changed after confirmation; rerun preview."
        )
    if _path_entry_exists(final_root):
        raise WorkspaceRestoreCollisionError(
            f"Restore destination already exists and will not be modified: {final_root}"
        )

    current_anchor = _nearest_existing_directory(parent)
    if current_anchor != parent:
        raise WorkspaceRestoreDestinationError(
            "Restore destination parent is not a stable ordinary directory."
        )
    if not _contains(precreate_anchor, parent) and precreate_anchor != parent:
        raise WorkspaceRestoreDestinationError(
            "Restore destination filesystem ancestry changed after confirmation."
        )
    free_bytes = _destination_free_bytes(parent, disk_usage_reader)
    if free_bytes < plan.required_free_bytes:
        raise WorkspaceRestoreSpaceError(
            "Insufficient destination free space for restore: "
            f"required {plan.required_free_bytes} bytes, "
            f"available {free_bytes} bytes."
        )
    return parent


def _default_staging_nonce() -> str:
    return secrets.token_hex(8)


def _staging_root(plan: WorkspaceRestorePlan, nonce: str) -> Path:
    if not isinstance(nonce, str) or not nonce or any(
        character not in (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        )
        for character in nonce
    ):
        raise WorkspaceRestoreDestinationError("Restore staging nonce is invalid.")
    return (
        plan.destination_parent
        / f".{plan.destination_root.name}.pds-restore.incomplete-{nonce}"
    )


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


def _payload_path(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def _regular_file_status(
    path: Path,
    *,
    relative: str,
    area: str,
) -> os.stat_result:
    try:
        status = path.lstat()
    except OSError as error:
        raise WorkspaceRestoreCopyError(
            f"Could not inspect {area} file: {relative}"
        ) from error
    if stat.S_ISLNK(status.st_mode) or _redirecting_reparse(status):
        raise WorkspaceRestoreDriftError(
            f"Restore {area} contains linked filesystem entry: {relative}"
        )
    if not stat.S_ISREG(status.st_mode):
        raise WorkspaceRestoreDriftError(
            f"Restore {area} contains non-regular file entry: {relative}"
        )
    return status


def _copy_verified_file(
    payload_root: Path,
    staging_root: Path,
    expected: BackupFileEntry,
    chunk_size: int,
) -> BackupFileEntry:
    """Copy one manifest-qualified payload file exclusively into restore staging."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    source = _payload_path(payload_root, expected.path)
    destination = _payload_path(staging_root, expected.path)
    before = _regular_file_status(
        source,
        relative=expected.path,
        area="backup payload",
    )
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            opened = os.fstat(input_stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise WorkspaceRestoreDriftError(
                    f"Backup payload file changed type while opening: {expected.path}"
                )
            while True:
                chunk = input_stream.read(chunk_size)
                if not chunk:
                    break
                output_stream.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except WorkspaceRestoreError:
        raise
    except FileExistsError as error:
        raise WorkspaceRestoreCopyError(
            f"Restore staging unexpectedly already contains file: {expected.path}"
        ) from error
    except OSError as error:
        raise WorkspaceRestoreCopyError(
            f"Could not copy verified backup payload file: {expected.path}"
        ) from error
    after = _regular_file_status(
        source,
        relative=expected.path,
        area="backup payload",
    )
    copied = BackupFileEntry(
        path=expected.path,
        size=total,
        sha256=digest.hexdigest(),
    )
    if total != before.st_size or total != after.st_size or copied != expected:
        raise WorkspaceRestoreDriftError(
            f"Backup payload changed while restore was copying: {expected.path}"
        )
    return copied


def _create_staging_tree(
    plan: WorkspaceRestorePlan,
    staging_root: Path,
) -> None:
    try:
        for relative in plan.verification.manifest.directories:
            _payload_path(staging_root, relative).mkdir(exist_ok=False)
    except OSError as error:
        raise WorkspaceRestoreCopyError(
            f"Could not create restore staging tree: {staging_root}"
        ) from error


def _hash_staged_file(
    staging_root: Path,
    expected: BackupFileEntry,
    *,
    chunk_size: int,
) -> BackupFileEntry:
    path = _payload_path(staging_root, expected.path)
    try:
        before = path.lstat()
    except OSError as error:
        raise WorkspaceRestoreVerificationError(
            f"Restored staging file cannot be inspected: {expected.path}"
        ) from error
    if stat.S_ISLNK(before.st_mode) or _redirecting_reparse(before):
        raise WorkspaceRestoreVerificationError(
            f"Restored staging contains linked filesystem entry: {expected.path}"
        )
    if not stat.S_ISREG(before.st_mode):
        raise WorkspaceRestoreVerificationError(
            f"Restored staging entry is not an ordinary file: {expected.path}"
        )
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise WorkspaceRestoreVerificationError(
                    f"Restored staging file changed type while opening: {expected.path}"
                )
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
    except WorkspaceRestoreError:
        raise
    except OSError as error:
        raise WorkspaceRestoreVerificationError(
            f"Restored staging file cannot be read: {expected.path}"
        ) from error
    try:
        after = path.lstat()
    except OSError as error:
        raise WorkspaceRestoreVerificationError(
            f"Restored staging file changed while being verified: {expected.path}"
        ) from error
    if not stat.S_ISREG(after.st_mode) or _redirecting_reparse(after):
        raise WorkspaceRestoreVerificationError(
            f"Restored staging file changed type while being verified: {expected.path}"
        )
    if total != before.st_size or total != after.st_size:
        raise WorkspaceRestoreVerificationError(
            f"Restored staging file changed size while being verified: {expected.path}"
        )
    return BackupFileEntry(
        path=expected.path,
        size=total,
        sha256=digest.hexdigest(),
    )


def _verify_staged_restore(
    staging_root: Path,
    manifest: WorkspaceBackupManifest,
    *,
    chunk_size: int,
) -> None:
    try:
        inventory = inventory_workspace(staging_root)
    except WorkspaceBackupError as error:
        raise WorkspaceRestoreVerificationError(str(error)) from error
    if inventory.directories != manifest.directories:
        raise WorkspaceRestoreVerificationError(
            "Restored staging directory inventory does not match the manifest."
        )
    expected_sizes = tuple((item.path, item.size) for item in manifest.files)
    observed_sizes = tuple((item.path, item.size) for item in inventory.files)
    if (
        observed_sizes != expected_sizes
        or inventory.total_bytes != manifest.total_bytes
    ):
        raise WorkspaceRestoreVerificationError(
            "Restored staging file inventory or sizes do not match the manifest."
        )
    for expected in manifest.files:
        actual = _hash_staged_file(
            staging_root,
            expected,
            chunk_size=chunk_size,
        )
        if actual != expected:
            raise WorkspaceRestoreVerificationError(
                f"Restored staging SHA-256 mismatch: {expected.path}"
            )
    try:
        final_inventory = inventory_workspace(staging_root)
    except WorkspaceBackupError as error:
        raise WorkspaceRestoreVerificationError(str(error)) from error
    if final_inventory != inventory:
        raise WorkspaceRestoreVerificationError(
            "Restored staging changed while verification was running."
        )


def _cleanup_staging(staging_root: Path) -> str | None:
    if not staging_root.exists():
        return None
    try:
        shutil.rmtree(staging_root)
    except OSError:
        return str(staging_root)
    return None


def _raise_rename_error(error_code: int, final_root: Path) -> None:
    if error_code in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(
            error_code,
            os.strerror(error_code),
            os.fspath(final_root),
        )
    raise OSError(
        error_code,
        os.strerror(error_code),
        os.fspath(final_root),
    )


def _try_renameat2_no_replace(staging_root: Path, final_root: Path) -> bool:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        function = getattr(libc, "renameat2")
    except (AttributeError, OSError):
        return False

    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        -100,
        os.fsencode(staging_root),
        -100,
        os.fsencode(final_root),
        1,
    )
    if result != 0:
        _raise_rename_error(ctypes.get_errno(), final_root)
    return True


def _try_renamex_no_replace(staging_root: Path, final_root: Path) -> bool:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        function = getattr(libc, "renamex_np")
    except (AttributeError, OSError):
        return False

    function.argtypes = (
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        os.fsencode(staging_root),
        os.fsencode(final_root),
        0x00000004,
    )
    if result != 0:
        _raise_rename_error(ctypes.get_errno(), final_root)
    return True


def _rename_no_replace(staging_root: Path, final_root: Path) -> None:
    if os.name == "nt":
        os.rename(staging_root, final_root)
        return
    if os.name == "posix":
        if _try_renameat2_no_replace(staging_root, final_root):
            return
        if _try_renamex_no_replace(staging_root, final_root):
            return
    raise OSError(
        errno.ENOTSUP,
        "No supported non-overwriting directory rename primitive is available.",
        os.fspath(final_root),
    )


def _publish_staging(staging_root: Path, final_root: Path) -> None:
    if _path_entry_exists(final_root):
        raise WorkspaceRestoreCollisionError(
            f"Restore destination already exists and will not be modified: {final_root}"
        )
    try:
        _rename_no_replace(staging_root, final_root)
    except FileExistsError as error:
        raise WorkspaceRestoreCollisionError(
            f"Restore destination already exists and will not be modified: {final_root}"
        ) from error
    except OSError as error:
        raise WorkspaceRestorePublicationError(
            f"Could not publish verified restored workspace: {final_root}"
        ) from error


def restore_workspace_backup(
    plan: WorkspaceRestorePlan,
    *,
    services: CoreWorkspaceServices | None = None,
    services_loader: CoreServicesLoader = load_core_workspace_services,
    verifier: BackupVerifier = verify_workspace_backup,
    disk_usage_reader: DiskUsageReader = _read_disk_usage,
    staging_nonce_factory: StagingNonceFactory = _default_staging_nonce,
    file_copier: FileCopier = _copy_verified_file,
    chunk_size: int = BACKUP_COPY_CHUNK_BYTES,
    after_copy_hook: AfterCopyHook | None = None,
    before_publish_hook: BeforePublishHook | None = None,
) -> WorkspaceRestoreResult:
    """Restore one reviewed verified backup to a new explicit alternate location."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    active_services = services or services_loader()

    # Reverify all reviewed source/safety state before the first destination mutation.
    _recheck_restore_sources(
        plan,
        services=active_services,
        verifier=verifier,
    )
    _prepare_destination_for_execution(
        plan,
        disk_usage_reader=disk_usage_reader,
    )

    staging_root = _staging_root(plan, staging_nonce_factory())
    try:
        staging_root.mkdir(exist_ok=False)
    except FileExistsError as error:
        raise WorkspaceRestoreCollisionError(
            "Restore staging path already exists and will not be overwritten: "
            f"{staging_root}"
        ) from error
    except OSError as error:
        raise WorkspaceRestoreCopyError(
            f"Could not create restore staging root: {staging_root}"
        ) from error

    try:
        _create_staging_tree(plan, staging_root)
        copied: list[BackupFileEntry] = []
        for expected in plan.verification.manifest.files:
            copied.append(
                file_copier(
                    plan.payload_root,
                    staging_root,
                    expected,
                    chunk_size,
                )
            )

        if after_copy_hook is not None:
            after_copy_hook(plan.payload_root, staging_root)

        try:
            observed = verifier(plan.backup_root)
        except WorkspaceBackupError as error:
            raise WorkspaceRestoreDriftError(
                "The backup changed while the restore was being created."
            ) from error
        if not _same_verification(plan.verification, observed):
            raise WorkspaceRestoreDriftError(
                "The backup changed while the restore was being created."
            )
        if tuple(copied) != plan.verification.manifest.files:
            raise WorkspaceRestoreDriftError(
                "Copied restore bytes do not match the reviewed backup manifest."
            )
        _verify_staged_restore(
            staging_root,
            plan.verification.manifest,
            chunk_size=chunk_size,
        )

        if before_publish_hook is not None:
            before_publish_hook(staging_root, plan.destination_root)
        _publish_staging(staging_root, plan.destination_root)
        return WorkspaceRestoreResult(
            destination_root=plan.destination_root,
            manifest=plan.verification.manifest,
            manifest_sha256=plan.manifest_sha256,
        )
    except WorkspaceRestoreError as error:
        remaining = _cleanup_staging(staging_root)
        if remaining is not None:
            raise WorkspaceRestoreCopyError(
                f"{error} Incomplete restore staging remains at: {remaining}"
            ) from error
        raise
    except (OSError, WorkspaceBackupError) as error:
        remaining = _cleanup_staging(staging_root)
        message = "Workspace restore failed due to a filesystem/integrity error."
        if remaining is not None:
            message += f" Incomplete restore staging remains at: {remaining}"
        raise WorkspaceRestoreCopyError(message) from error


__all__ = (
    "WorkspaceRestoreCollisionError",
    "WorkspaceRestoreCopyError",
    "WorkspaceRestoreCoreError",
    "WorkspaceRestoreDestinationError",
    "WorkspaceRestoreDriftError",
    "WorkspaceRestoreError",
    "WorkspaceRestorePlan",
    "WorkspaceRestorePublicationError",
    "WorkspaceRestoreResult",
    "WorkspaceRestoreSpaceError",
    "WorkspaceRestoreVerificationError",
    "plan_workspace_restore",
    "restore_workspace_backup",
)
