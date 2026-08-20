"""Planning, manifest, and safe creation for whole-workspace backups.

Backup is the suite architecture's opaque-custody exception: this module may
enumerate and copy workspace files as bytes, but it never parses or rewrites
Core- or module-owned records.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module, metadata
from pathlib import Path, PurePosixPath
from typing import Final, Protocol, cast

from paper_data_suite._version import __version__
from paper_data_suite.compatibility import (
    ReleaseCompatibilityManifest,
    load_release_compatibility_manifest,
)
from paper_data_suite.component_inspection import DistributionVersionLookup
from paper_data_suite.workspace_setup import (
    CoreWorkspaceQualificationError,
    WorkspaceInspector,
    load_core_workspace_services,
)

BACKUP_MANIFEST_RECORD_TYPE: Final[str] = "pds_workspace_backup_manifest"
BACKUP_MANIFEST_SCHEMA_VERSION: Final[str] = "1"
BACKUP_PAYLOAD_ROOT: Final[str] = "workspace"
BACKUP_HASH_ALGORITHM: Final[str] = "sha256"
BACKUP_NAME_PREFIX: Final[str] = "pds-workspace-backup-"
BACKUP_MINIMUM_RESERVE_BYTES: Final[int] = 64 * 1024 * 1024
BACKUP_RESERVE_PERCENT: Final[int] = 2
BACKUP_MANIFEST_FILENAME: Final[str] = "manifest.json"
BACKUP_COPY_CHUNK_BYTES: Final[int] = 1024 * 1024

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^pds-workspace-backup-\d{8}T\d{12}Z$"
)
_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "record_type",
        "schema_version",
        "backup_id",
        "created_at",
        "suite_version",
        "core_version",
        "payload_root",
        "hash_algorithm",
        "directory_count",
        "file_count",
        "total_bytes",
        "directories",
        "files",
        "exclusions",
    }
)
_FILE_ENTRY_KEYS: Final[frozenset[str]] = frozenset({"path", "size", "sha256"})

Clock = Callable[[], datetime]
ModuleImporter = Callable[[str], object]


class WorkspaceBackupError(RuntimeError):
    """Base class for bounded workspace-backup failures."""


class WorkspaceBackupManifestError(WorkspaceBackupError, ValueError):
    """Raised when a backup manifest violates the v1 contract."""


class WorkspaceBackupSourceError(WorkspaceBackupError):
    """Raised when the currently resolved source workspace cannot be backed up."""


class WorkspaceBackupDestinationError(WorkspaceBackupError):
    """Raised when the requested backup destination is unsafe or unusable."""


class WorkspaceBackupUnsupportedEntryError(WorkspaceBackupSourceError):
    """Raised when source traversal encounters a link or special entry."""


class WorkspaceBackupSpaceError(WorkspaceBackupDestinationError):
    """Raised when destination free space is below the conservative threshold."""


class WorkspaceBackupCollisionError(WorkspaceBackupDestinationError):
    """Raised when the deterministic final backup path already exists."""


class WorkspaceBackupDriftError(WorkspaceBackupSourceError):
    """Raised when the source workspace changes during backup creation."""


class WorkspaceBackupCopyError(WorkspaceBackupError):
    """Raised when opaque payload copying cannot complete safely."""


class WorkspaceBackupVerificationError(WorkspaceBackupError):
    """Raised when copied payload or persisted manifest verification fails."""


class WorkspaceBackupPublicationError(WorkspaceBackupError):
    """Raised when a verified staging backup cannot be published safely."""


class DiskUsageLike(Protocol):
    """Read-only free-space field consumed from a disk-usage provider."""

    @property
    def free(self) -> int: ...


DiskUsageReader = Callable[[str | os.PathLike[str]], DiskUsageLike]


def _read_disk_usage(path: str | os.PathLike[str]) -> DiskUsageLike:
    """Read filesystem usage through the project-owned injectable signature."""
    return shutil.disk_usage(path)


class WorkspaceStatusLike(Protocol):
    """Public Core workspace status fields consumed by backup planning."""

    root: Path
    source: str
    exists: bool
    is_dir: bool


@dataclass(frozen=True, slots=True)
class CoreBackupServices:
    """Qualified public Core services/facts required for backup planning."""

    inspect_workspace_root: WorkspaceInspector
    core_version: str


@dataclass(frozen=True, slots=True)
class BackupSourceFile:
    """One regular source file discovered during read-only preflight."""

    path: str
    size: int

    def __post_init__(self) -> None:
        _validate_relative_manifest_path(self.path, "source file path")
        if (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
        ):
            raise WorkspaceBackupManifestError("source file size must be >= 0")


@dataclass(frozen=True, slots=True)
class WorkspaceBackupInventory:
    """Deterministic read-only source tree inventory before confirmation."""

    directories: tuple[str, ...]
    files: tuple[BackupSourceFile, ...]
    total_bytes: int

    def __post_init__(self) -> None:
        _validate_sorted_unique_paths(self.directories, "directories")
        file_paths = tuple(entry.path for entry in self.files)
        _validate_sorted_unique_paths(file_paths, "files")
        if tuple(sorted(self.files, key=lambda item: item.path)) != self.files:
            raise WorkspaceBackupManifestError("files must be sorted by relative path")
        expected_total = sum(entry.size for entry in self.files)
        if self.total_bytes != expected_total:
            raise WorkspaceBackupManifestError(
                "inventory total_bytes does not match file sizes"
            )

    @property
    def directory_count(self) -> int:
        return len(self.directories)

    @property
    def file_count(self) -> int:
        return len(self.files)


@dataclass(frozen=True, slots=True)
class BackupFileEntry:
    """Portable integrity facts for one copied regular payload file."""

    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_relative_manifest_path(self.path, "file path")
        if (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
        ):
            raise WorkspaceBackupManifestError("file size must be >= 0")
        if (
            not isinstance(self.sha256, str)
            or _SHA256_RE.fullmatch(self.sha256) is None
        ):
            raise WorkspaceBackupManifestError(
                "file sha256 must be 64 lowercase hexadecimal characters"
            )


@dataclass(frozen=True, slots=True)
class WorkspaceBackupManifest:
    """Versioned deterministic manifest for one completed workspace backup."""

    record_type: str
    schema_version: str
    backup_id: str
    created_at: datetime
    suite_version: str
    core_version: str
    payload_root: str
    hash_algorithm: str
    directory_count: int
    file_count: int
    total_bytes: int
    directories: tuple[str, ...]
    files: tuple[BackupFileEntry, ...]
    exclusions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.record_type != BACKUP_MANIFEST_RECORD_TYPE:
            raise WorkspaceBackupManifestError(
                "unsupported backup manifest record_type"
            )
        if self.schema_version != BACKUP_MANIFEST_SCHEMA_VERSION:
            raise WorkspaceBackupManifestError(
                "unsupported backup manifest schema_version"
            )
        if not isinstance(self.backup_id, str) or _BACKUP_NAME_RE.fullmatch(
            self.backup_id
        ) is None:
            raise WorkspaceBackupManifestError(
                "backup_id is not a canonical backup name"
            )
        normalized_created_at = _utc_datetime(self.created_at, "created_at")
        object.__setattr__(self, "created_at", normalized_created_at)
        if self.backup_id != backup_name(normalized_created_at):
            raise WorkspaceBackupManifestError(
                "backup_id does not match created_at timestamp identity"
            )
        for value, field_name in (
            (self.suite_version, "suite_version"),
            (self.core_version, "core_version"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise WorkspaceBackupManifestError(f"{field_name} must not be blank")
        if self.payload_root != BACKUP_PAYLOAD_ROOT:
            raise WorkspaceBackupManifestError("payload_root must be 'workspace'")
        if self.hash_algorithm != BACKUP_HASH_ALGORITHM:
            raise WorkspaceBackupManifestError("hash_algorithm must be 'sha256'")
        _validate_sorted_unique_paths(self.directories, "directories")
        file_paths = tuple(entry.path for entry in self.files)
        _validate_sorted_unique_paths(file_paths, "files")
        if tuple(sorted(self.files, key=lambda item: item.path)) != self.files:
            raise WorkspaceBackupManifestError("files must be sorted by relative path")
        if self.directory_count != len(self.directories):
            raise WorkspaceBackupManifestError(
                "directory_count does not match directories inventory"
            )
        if self.file_count != len(self.files):
            raise WorkspaceBackupManifestError(
                "file_count does not match files inventory"
            )
        if self.total_bytes != sum(entry.size for entry in self.files):
            raise WorkspaceBackupManifestError("total_bytes does not match file sizes")
        if self.exclusions != ():
            raise WorkspaceBackupManifestError(
                "backup manifest v1 requires an empty source-content exclusions set"
            )


@dataclass(frozen=True, slots=True)
class WorkspaceBackupPlan:
    """Read-only backup proposal shown before any destination mutation."""

    workspace_root: Path
    workspace_source: str
    destination_parent: Path
    final_backup_root: Path
    backup_id: str
    created_at: datetime
    suite_version: str
    core_version: str
    inventory: WorkspaceBackupInventory
    destination_free_bytes: int
    required_free_bytes: int
    destination_parent_exists: bool

    @property
    def payload_root(self) -> Path:
        return self.final_backup_root / BACKUP_PAYLOAD_ROOT


@dataclass(frozen=True, slots=True)
class WorkspaceBackupResult:
    """Verified completed backup after non-overwriting publication."""

    final_backup_root: Path
    manifest: WorkspaceBackupManifest
    manifest_sha256: str

    @property
    def payload_root(self) -> Path:
        return self.final_backup_root / BACKUP_PAYLOAD_ROOT

    @property
    def manifest_path(self) -> Path:
        return self.final_backup_root / BACKUP_MANIFEST_FILENAME


def _utc_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise WorkspaceBackupManifestError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkspaceBackupManifestError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _format_created_at(value: datetime) -> str:
    normalized = _utc_datetime(value, "created_at")
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_created_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise WorkspaceBackupManifestError("created_at must be a UTC timestamp string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as error:
        raise WorkspaceBackupManifestError(
            "created_at must use YYYY-MM-DDTHH:MM:SS.ffffffZ"
        ) from error
    return parsed.replace(tzinfo=timezone.utc)


def backup_name(created_at: datetime) -> str:
    """Return the deterministic Windows-safe backup directory identity."""
    normalized = _utc_datetime(created_at, "created_at")
    return BACKUP_NAME_PREFIX + normalized.strftime("%Y%m%dT%H%M%S%fZ")


def required_backup_free_bytes(total_payload_bytes: int) -> int:
    """Return the conservative destination free-space threshold."""
    if (
        not isinstance(total_payload_bytes, int)
        or isinstance(total_payload_bytes, bool)
        or total_payload_bytes < 0
    ):
        raise WorkspaceBackupDestinationError("total payload bytes must be >= 0")
    percent_reserve = (
        total_payload_bytes * BACKUP_RESERVE_PERCENT + 99
    ) // 100
    reserve = max(BACKUP_MINIMUM_RESERVE_BYTES, percent_reserve)
    return total_payload_bytes + reserve


def _validate_relative_manifest_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceBackupManifestError(f"{label} must be a non-empty string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WorkspaceBackupManifestError(
            f"{label} must not contain control characters"
        )
    if "\\" in value or ":" in value:
        raise WorkspaceBackupManifestError(
            f"{label} contains non-portable path syntax"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/"):
        raise WorkspaceBackupManifestError(f"{label} must be relative")
    if value.endswith("/") or "//" in value:
        raise WorkspaceBackupManifestError(f"{label} is not canonical")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise WorkspaceBackupManifestError(f"{label} must not contain dot segments")
    if path.as_posix() != value:
        raise WorkspaceBackupManifestError(f"{label} must use canonical '/' separators")
    return value


def _validate_sorted_unique_paths(values: Sequence[str], label: str) -> None:
    for value in values:
        _validate_relative_manifest_path(value, f"{label} path")
    if tuple(values) != tuple(sorted(values)):
        raise WorkspaceBackupManifestError(f"{label} must be sorted")
    if len(values) != len(set(values)):
        raise WorkspaceBackupManifestError(f"{label} must not contain duplicates")


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkspaceBackupManifestError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise WorkspaceBackupManifestError(f"{label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise WorkspaceBackupManifestError(
            f"{label} is missing field(s): {', '.join(missing)}"
        )
    if unknown:
        raise WorkspaceBackupManifestError(
            f"{label} has unknown field(s): {', '.join(unknown)}"
        )


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceBackupManifestError(f"{label} must be a non-empty string")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise WorkspaceBackupManifestError(f"{label} must be an integer >= 0")
    return value


def workspace_backup_manifest_to_dict(
    manifest: WorkspaceBackupManifest,
) -> dict[str, object]:
    """Return the canonical JSON-compatible v1 manifest mapping."""
    return {
        "record_type": manifest.record_type,
        "schema_version": manifest.schema_version,
        "backup_id": manifest.backup_id,
        "created_at": _format_created_at(manifest.created_at),
        "suite_version": manifest.suite_version,
        "core_version": manifest.core_version,
        "payload_root": manifest.payload_root,
        "hash_algorithm": manifest.hash_algorithm,
        "directory_count": manifest.directory_count,
        "file_count": manifest.file_count,
        "total_bytes": manifest.total_bytes,
        "directories": list(manifest.directories),
        "files": [
            {"path": entry.path, "size": entry.size, "sha256": entry.sha256}
            for entry in manifest.files
        ],
        "exclusions": list(manifest.exclusions),
    }


def serialize_workspace_backup_manifest(manifest: WorkspaceBackupManifest) -> bytes:
    """Serialize a manifest deterministically as UTF-8 JSON plus one newline."""
    payload = json.dumps(
        workspace_backup_manifest_to_dict(manifest),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    return payload.encode("utf-8")


def workspace_backup_manifest_sha256(manifest: WorkspaceBackupManifest) -> str:
    """Return SHA-256 of the canonical serialized manifest bytes."""
    return hashlib.sha256(serialize_workspace_backup_manifest(manifest)).hexdigest()


def parse_workspace_backup_manifest(data: bytes | str) -> WorkspaceBackupManifest:
    """Parse and strictly validate one v1 backup manifest."""
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as error:
        raise WorkspaceBackupManifestError("manifest must be UTF-8") from error
    if not isinstance(text, str):
        raise WorkspaceBackupManifestError("manifest input must be bytes or text")
    try:
        raw = json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except json.JSONDecodeError as error:
        raise WorkspaceBackupManifestError(
            f"manifest is invalid JSON: {error}"
        ) from error
    mapping = _mapping(raw, "manifest")
    _exact_keys(mapping, _MANIFEST_KEYS, "manifest")

    raw_directories = mapping["directories"]
    raw_files = mapping["files"]
    raw_exclusions = mapping["exclusions"]
    if not isinstance(raw_directories, list):
        raise WorkspaceBackupManifestError("directories must be an array")
    if not isinstance(raw_files, list):
        raise WorkspaceBackupManifestError("files must be an array")
    if not isinstance(raw_exclusions, list):
        raise WorkspaceBackupManifestError("exclusions must be an array")

    directories = tuple(
        _string(value, f"directories[{index}]")
        for index, value in enumerate(raw_directories)
    )
    files: list[BackupFileEntry] = []
    for index, raw_entry in enumerate(raw_files):
        entry = _mapping(raw_entry, f"files[{index}]")
        _exact_keys(entry, _FILE_ENTRY_KEYS, f"files[{index}]")
        files.append(
            BackupFileEntry(
                path=_string(entry["path"], f"files[{index}].path"),
                size=_integer(entry["size"], f"files[{index}].size"),
                sha256=_string(entry["sha256"], f"files[{index}].sha256"),
            )
        )
    exclusions = tuple(
        _string(value, f"exclusions[{index}]")
        for index, value in enumerate(raw_exclusions)
    )

    return WorkspaceBackupManifest(
        record_type=_string(mapping["record_type"], "record_type"),
        schema_version=_string(mapping["schema_version"], "schema_version"),
        backup_id=_string(mapping["backup_id"], "backup_id"),
        created_at=_parse_created_at(mapping["created_at"]),
        suite_version=_string(mapping["suite_version"], "suite_version"),
        core_version=_string(mapping["core_version"], "core_version"),
        payload_root=_string(mapping["payload_root"], "payload_root"),
        hash_algorithm=_string(mapping["hash_algorithm"], "hash_algorithm"),
        directory_count=_integer(mapping["directory_count"], "directory_count"),
        file_count=_integer(mapping["file_count"], "file_count"),
        total_bytes=_integer(mapping["total_bytes"], "total_bytes"),
        directories=directories,
        files=tuple(files),
        exclusions=exclusions,
    )


def create_workspace_backup_manifest(
    plan: WorkspaceBackupPlan,
    files: Sequence[BackupFileEntry],
) -> WorkspaceBackupManifest:
    """Build the final manifest only from a reviewed plan and verified file hashes."""
    sorted_files = tuple(sorted(files, key=lambda item: item.path))
    expected = {entry.path: entry.size for entry in plan.inventory.files}
    observed = {entry.path: entry.size for entry in sorted_files}
    if observed != expected or len(sorted_files) != len(expected):
        raise WorkspaceBackupManifestError(
            "verified file entries do not match the reviewed source inventory"
        )
    return WorkspaceBackupManifest(
        record_type=BACKUP_MANIFEST_RECORD_TYPE,
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=plan.backup_id,
        created_at=plan.created_at,
        suite_version=plan.suite_version,
        core_version=plan.core_version,
        payload_root=BACKUP_PAYLOAD_ROOT,
        hash_algorithm=BACKUP_HASH_ALGORITHM,
        directory_count=plan.inventory.directory_count,
        file_count=plan.inventory.file_count,
        total_bytes=plan.inventory.total_bytes,
        directories=plan.inventory.directories,
        files=sorted_files,
        exclusions=(),
    )


def _shared_core_version(manifest: ReleaseCompatibilityManifest) -> str:
    candidates = tuple(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    if len(candidates) != 1:
        raise CoreWorkspaceQualificationError(
            "The suite manifest does not identify exactly one shared Core component."
        )
    return candidates[0].version


def load_core_backup_services(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
    module_importer: ModuleImporter = import_module,
) -> CoreBackupServices:
    """Qualify Core exactly, then expose only its read-only workspace inspector."""
    active_manifest = manifest or load_release_compatibility_manifest()
    workspace_services = load_core_workspace_services(
        active_manifest,
        version_lookup=version_lookup,
        module_importer=module_importer,
    )
    return CoreBackupServices(
        inspect_workspace_root=workspace_services.inspect_workspace_root,
        core_version=_shared_core_version(active_manifest),
    )


def _workspace_source(services: CoreBackupServices) -> tuple[Path, str]:
    try:
        status = services.inspect_workspace_root()
    except Exception as error:
        message = str(error)[:300] or error.__class__.__name__
        raise WorkspaceBackupSourceError(
            f"Core could not inspect the currently resolved workspace: {message}"
        ) from error
    try:
        root = Path(status.root)
        source = status.source
        exists = status.exists
        is_dir = status.is_dir
    except (AttributeError, TypeError, ValueError) as error:
        raise WorkspaceBackupSourceError(
            "Core returned an invalid workspace status result."
        ) from error
    if not isinstance(source, str) or not source.strip():
        raise WorkspaceBackupSourceError(
            "Core returned an invalid workspace resolution source."
        )
    if not isinstance(exists, bool) or not isinstance(is_dir, bool):
        raise WorkspaceBackupSourceError(
            "Core returned invalid workspace status flags."
        )
    if not exists:
        raise WorkspaceBackupSourceError(
            f"The currently resolved workspace does not exist: {root}. "
            "Run 'pds workspace setup' first."
        )
    if not is_dir:
        raise WorkspaceBackupSourceError(
            f"The currently resolved workspace is not a directory: {root}. "
            "Run 'pds workspace setup' to select a usable workspace."
        )
    try:
        canonical = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspaceBackupSourceError(
            f"Could not resolve the current workspace: {root}."
        ) from error
    if not canonical.is_dir():
        raise WorkspaceBackupSourceError(
            f"The currently resolved workspace is not a directory: {canonical}."
        )
    return canonical, source


def _manifest_relative(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise WorkspaceBackupSourceError(
            f"Workspace entry escaped the source root: {path}"
        ) from error
    value = "/".join(relative.parts)
    try:
        return _validate_relative_manifest_path(value, "workspace entry path")
    except WorkspaceBackupManifestError as error:
        raise WorkspaceBackupUnsupportedEntryError(
            "Workspace backup path is not portable in manifest v1: "
            f"{value!r}"
        ) from error


def _redirecting_reparse(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not reparse_flag or not attributes & reparse_flag:
        return False
    tag = getattr(stat_result, "st_reparse_tag", None)
    redirect_tags = {
        value
        for value in (
            getattr(stat, "IO_REPARSE_TAG_SYMLINK", None),
            getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None),
        )
        if value is not None
    }
    return tag in redirect_tags


def inventory_workspace(workspace_root: Path) -> WorkspaceBackupInventory:
    """Enumerate ordinary files/directories without following filesystem links."""
    directories: list[str] = []
    files: list[BackupSourceFile] = []

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as scan:
                entries = sorted(tuple(scan), key=lambda item: item.name)
        except OSError as error:
            raise WorkspaceBackupSourceError(
                f"Could not enumerate workspace directory: "
                f"{_display_relative(workspace_root, directory)}"
            ) from error

        for entry in entries:
            entry_path = Path(entry.path)
            relative = _manifest_relative(workspace_root, entry_path)
            try:
                status = entry.stat(follow_symlinks=False)
                is_symlink = entry.is_symlink()
            except OSError as error:
                raise WorkspaceBackupSourceError(
                    f"Could not inspect workspace entry: {relative}"
                ) from error
            if (
                is_symlink
                or stat.S_ISLNK(status.st_mode)
                or _redirecting_reparse(status)
            ):
                raise WorkspaceBackupUnsupportedEntryError(
                    "Workspace backup does not follow linked filesystem entry: "
                    f"{relative}"
                )
            if stat.S_ISDIR(status.st_mode):
                directories.append(relative)
                walk(entry_path)
                continue
            if stat.S_ISREG(status.st_mode):
                files.append(BackupSourceFile(path=relative, size=status.st_size))
                continue
            raise WorkspaceBackupUnsupportedEntryError(
                "Workspace backup does not support special filesystem entry: "
                f"{relative}"
            )

    walk(workspace_root)
    sorted_directories = tuple(sorted(directories))
    sorted_files = tuple(sorted(files, key=lambda item: item.path))
    return WorkspaceBackupInventory(
        directories=sorted_directories,
        files=sorted_files,
        total_bytes=sum(entry.size for entry in sorted_files),
    )


def _display_relative(root: Path, path: Path) -> str:
    if path == root:
        return "."
    try:
        return "/".join(path.relative_to(root).parts)
    except ValueError:
        return "<outside workspace>"


def _expanded_path(path: str | Path, label: str) -> Path:
    raw = os.fspath(path)
    if not raw.strip():
        raise WorkspaceBackupDestinationError(f"{label} cannot be empty")
    expanded = os.path.expandvars(os.path.expanduser(raw))
    try:
        return Path(expanded).resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise WorkspaceBackupDestinationError(
            f"Could not resolve {label.lower()}."
        ) from error


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_safe_destination(
    workspace_root: Path,
    destination_parent: Path,
    final_backup_root: Path,
) -> None:
    if destination_parent == workspace_root or _contains(
        workspace_root, destination_parent
    ):
        raise WorkspaceBackupDestinationError(
            "Backup destination must be outside the active workspace."
        )
    if final_backup_root == workspace_root or _contains(
        workspace_root, final_backup_root
    ):
        raise WorkspaceBackupDestinationError(
            "Final backup path must be outside the active workspace."
        )
    if _contains(final_backup_root, workspace_root):
        raise WorkspaceBackupDestinationError(
            "Final backup path must not contain the active workspace."
        )


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    if not candidate.exists() or not candidate.is_dir():
        raise WorkspaceBackupDestinationError(
            "Backup destination has no usable existing directory ancestor."
        )
    return candidate


def _destination_free_bytes(
    destination_parent: Path,
    disk_usage_reader: DiskUsageReader,
) -> int:
    anchor = _nearest_existing_directory(destination_parent)
    try:
        usage = disk_usage_reader(anchor)
        free = usage.free
    except (OSError, TypeError, ValueError, AttributeError) as error:
        raise WorkspaceBackupDestinationError(
            f"Could not inspect free space for backup destination: {anchor}"
        ) from error
    if not isinstance(free, int) or isinstance(free, bool) or free < 0:
        raise WorkspaceBackupDestinationError(
            "Destination free-space provider returned an invalid value."
        )
    return free


def plan_workspace_backup(
    destination_parent: str | Path,
    *,
    services: CoreBackupServices | None = None,
    clock: Clock | None = None,
    disk_usage_reader: DiskUsageReader = _read_disk_usage,
) -> WorkspaceBackupPlan:
    """Build a complete read-only backup proposal without creating destination state."""
    active_services = services or load_core_backup_services()
    workspace_root, workspace_source = _workspace_source(active_services)
    created_at = _utc_datetime(
        (clock or (lambda: datetime.now(timezone.utc)))(),
        "created_at",
    )
    backup_id = backup_name(created_at)
    destination = _expanded_path(destination_parent, "Backup destination")
    if destination.exists() and not destination.is_dir():
        raise WorkspaceBackupDestinationError(
            f"Backup destination exists but is not a directory: {destination}"
        )
    final_root = destination / backup_id
    _assert_safe_destination(workspace_root, destination, final_root)
    if final_root.exists():
        raise WorkspaceBackupCollisionError(
            f"Backup already exists and will not be overwritten: {final_root}"
        )

    inventory = inventory_workspace(workspace_root)
    free_bytes = _destination_free_bytes(destination, disk_usage_reader)
    required_bytes = required_backup_free_bytes(inventory.total_bytes)
    if free_bytes < required_bytes:
        raise WorkspaceBackupSpaceError(
            "Insufficient destination free space for backup: "
            f"required {required_bytes} bytes, available {free_bytes} bytes."
        )

    return WorkspaceBackupPlan(
        workspace_root=workspace_root,
        workspace_source=workspace_source,
        destination_parent=destination,
        final_backup_root=final_root,
        backup_id=backup_id,
        created_at=created_at,
        suite_version=__version__,
        core_version=active_services.core_version,
        inventory=inventory,
        destination_free_bytes=free_bytes,
        required_free_bytes=required_bytes,
        destination_parent_exists=destination.exists(),
    )


def _payload_path(root: Path, relative: str) -> Path:
    """Return a native path for one already-validated manifest relative path."""
    canonical = _validate_relative_manifest_path(relative, "payload path")
    return root.joinpath(*PurePosixPath(canonical).parts)


def _regular_file_status(path: Path, *, relative: str, area: str) -> os.stat_result:
    """Inspect one regular file without following the leaf entry."""
    try:
        status = path.lstat()
    except OSError as error:
        if area == "source":
            raise WorkspaceBackupSourceError(
                f"Could not inspect source backup file: {relative}"
            ) from error
        raise WorkspaceBackupVerificationError(
            f"Could not inspect staged backup file: {relative}"
        ) from error
    if stat.S_ISLNK(status.st_mode) or _redirecting_reparse(status):
        if area == "source":
            raise WorkspaceBackupUnsupportedEntryError(
                f"Backup source contains linked filesystem entry: {relative}"
            )
        raise WorkspaceBackupVerificationError(
            f"Backup staged contains linked filesystem entry: {relative}"
        )
    if not stat.S_ISREG(status.st_mode):
        if area == "source":
            raise WorkspaceBackupUnsupportedEntryError(
                f"Backup source contains non-regular file entry: {relative}"
            )
        raise WorkspaceBackupVerificationError(
            f"Backup staged contains non-regular file entry: {relative}"
        )
    return status


def _hash_file(
    path: Path,
    *,
    relative: str,
    area: str,
    chunk_size: int,
) -> BackupFileEntry:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    before = _regular_file_status(path, relative=relative, area=area)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise WorkspaceBackupVerificationError(
                    f"Backup {area} file changed type while opening: {relative}"
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
        if area == "source":
            raise WorkspaceBackupSourceError(
                f"Could not read source backup file: {relative}"
            ) from error
        raise WorkspaceBackupVerificationError(
            f"Could not read staged backup file: {relative}"
        ) from error
    after = _regular_file_status(path, relative=relative, area=area)
    if total != before.st_size or total != after.st_size:
        if area == "source":
            raise WorkspaceBackupDriftError(
                f"Backup source file changed while being read: {relative}"
            )
        raise WorkspaceBackupVerificationError(
            f"Backup staged file changed while being read: {relative}"
        )
    return BackupFileEntry(path=relative, size=total, sha256=digest.hexdigest())


def _copy_regular_file(
    source_root: Path,
    payload_root: Path,
    relative: str,
    chunk_size: int,
) -> BackupFileEntry:
    """Copy one regular source file exclusively while hashing written bytes."""
    source = _payload_path(source_root, relative)
    destination = _payload_path(payload_root, relative)
    before = _regular_file_status(source, relative=relative, area="source")
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            opened = os.fstat(input_stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise WorkspaceBackupUnsupportedEntryError(
                    f"Workspace file changed type while opening: {relative}"
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
    except WorkspaceBackupError:
        raise
    except FileExistsError as error:
        raise WorkspaceBackupCopyError(
            f"Staging payload unexpectedly already contains file: {relative}"
        ) from error
    except OSError as error:
        raise WorkspaceBackupCopyError(
            f"Could not copy workspace file into backup staging: {relative}"
        ) from error
    after = _regular_file_status(source, relative=relative, area="source")
    if total != before.st_size or total != after.st_size:
        raise WorkspaceBackupDriftError(
            f"Workspace file changed while being copied: {relative}"
        )
    return BackupFileEntry(path=relative, size=total, sha256=digest.hexdigest())


FileCopier = Callable[[Path, Path, str, int], BackupFileEntry]
StagingNonceFactory = Callable[[], str]
AfterCopyHook = Callable[[Path, Path], None]
BeforePublishHook = Callable[[Path, Path], None]


def _default_staging_nonce() -> str:
    return secrets.token_hex(8)


def _staging_root(plan: WorkspaceBackupPlan, nonce: str) -> Path:
    if not isinstance(nonce, str) or not nonce or any(
        character not in (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        )
        for character in nonce
    ):
        raise WorkspaceBackupDestinationError("Backup staging nonce is invalid.")
    return plan.destination_parent / f".{plan.backup_id}.incomplete-{nonce}"


def _same_inventory(
    expected: WorkspaceBackupInventory,
    observed: WorkspaceBackupInventory,
) -> bool:
    return expected == observed


def _recheck_plan_source(
    plan: WorkspaceBackupPlan,
    services: CoreBackupServices,
) -> None:
    current_root, _current_source = _workspace_source(services)
    if current_root != plan.workspace_root:
        raise WorkspaceBackupDriftError(
            "The currently resolved workspace changed after backup preview."
        )
    current_inventory = inventory_workspace(current_root)
    if not _same_inventory(plan.inventory, current_inventory):
        raise WorkspaceBackupDriftError(
            "The workspace changed after backup preview; create a new backup plan."
        )


def _prepare_destination_for_execution(
    plan: WorkspaceBackupPlan,
    *,
    disk_usage_reader: DiskUsageReader,
) -> Path:
    """Create/re-resolve the destination parent only at the execution boundary."""
    precreate = _expanded_path(plan.destination_parent, "Backup destination")
    proposed_final = precreate / plan.backup_id
    _assert_safe_destination(plan.workspace_root, precreate, proposed_final)
    if proposed_final.exists():
        raise WorkspaceBackupCollisionError(
            f"Backup already exists and will not be overwritten: {proposed_final}"
        )
    try:
        precreate.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise WorkspaceBackupDestinationError(
            f"Could not create backup destination: {precreate}"
        ) from error
    try:
        destination = precreate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspaceBackupDestinationError(
            f"Could not resolve created backup destination: {precreate}"
        ) from error
    if not destination.is_dir():
        raise WorkspaceBackupDestinationError(
            f"Backup destination is not a directory: {destination}"
        )
    final_root = destination / plan.backup_id
    _assert_safe_destination(plan.workspace_root, destination, final_root)
    if destination != plan.destination_parent:
        raise WorkspaceBackupDestinationError(
            "Backup destination resolved differently after confirmation; rerun preview."
        )
    if final_root != plan.final_backup_root:
        raise WorkspaceBackupDestinationError(
            "Final backup path changed after confirmation; rerun preview."
        )
    if final_root.exists():
        raise WorkspaceBackupCollisionError(
            f"Backup already exists and will not be overwritten: {final_root}"
        )
    free_bytes = _destination_free_bytes(destination, disk_usage_reader)
    if free_bytes < plan.required_free_bytes:
        raise WorkspaceBackupSpaceError(
            "Insufficient destination free space for backup: "
            f"required {plan.required_free_bytes} bytes, available {free_bytes} bytes."
        )
    return destination


def _create_staging_payload(
    plan: WorkspaceBackupPlan,
    staging_root: Path,
) -> Path:
    """Populate a staging root that this execution already created exclusively."""
    try:
        payload_root = staging_root / BACKUP_PAYLOAD_ROOT
        payload_root.mkdir(exist_ok=False)
        for relative in plan.inventory.directories:
            _payload_path(payload_root, relative).mkdir(exist_ok=False)
    except OSError as error:
        raise WorkspaceBackupCopyError(
            f"Could not create backup staging tree: {staging_root}"
        ) from error
    return payload_root


def _verify_source_matches_copied(
    plan: WorkspaceBackupPlan,
    copied: Sequence[BackupFileEntry],
    *,
    chunk_size: int,
) -> None:
    observed_inventory = inventory_workspace(plan.workspace_root)
    if not _same_inventory(plan.inventory, observed_inventory):
        raise WorkspaceBackupDriftError(
            "The workspace changed while the backup was being created."
        )
    copied_by_path = {entry.path: entry for entry in copied}
    for source_entry in plan.inventory.files:
        current = _hash_file(
            _payload_path(plan.workspace_root, source_entry.path),
            relative=source_entry.path,
            area="source",
            chunk_size=chunk_size,
        )
        if current != copied_by_path.get(source_entry.path):
            raise WorkspaceBackupDriftError(
                "The workspace changed while the backup was being created: "
                f"{source_entry.path}"
            )


def _verify_staged_payload(
    plan: WorkspaceBackupPlan,
    payload_root: Path,
    copied: Sequence[BackupFileEntry],
    *,
    chunk_size: int,
) -> None:
    observed_inventory = inventory_workspace(payload_root)
    if not _same_inventory(plan.inventory, observed_inventory):
        raise WorkspaceBackupVerificationError(
            "Staged backup inventory does not match the reviewed workspace inventory."
        )
    copied_by_path = {entry.path: entry for entry in copied}
    for expected in copied:
        actual = _hash_file(
            _payload_path(payload_root, expected.path),
            relative=expected.path,
            area="staged",
            chunk_size=chunk_size,
        )
        if actual != copied_by_path[expected.path]:
            raise WorkspaceBackupVerificationError(
                f"Staged backup file failed integrity verification: {expected.path}"
            )


def _write_verified_manifest(
    staging_root: Path,
    manifest: WorkspaceBackupManifest,
) -> str:
    manifest_path = staging_root / BACKUP_MANIFEST_FILENAME
    temporary = staging_root / f".{BACKUP_MANIFEST_FILENAME}.tmp"
    payload = serialize_workspace_backup_manifest(manifest)
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(manifest_path)
        persisted = manifest_path.read_bytes()
    except OSError as error:
        raise WorkspaceBackupVerificationError(
            "Could not persist backup manifest in verified staging."
        ) from error
    if persisted != payload:
        raise WorkspaceBackupVerificationError(
            "Persisted backup manifest bytes do not match canonical serialization."
        )
    parsed = parse_workspace_backup_manifest(persisted)
    if parsed != manifest:
        raise WorkspaceBackupVerificationError(
            "Persisted backup manifest failed read-after-write validation."
        )
    return hashlib.sha256(persisted).hexdigest()


def _cleanup_staging(staging_root: Path) -> str | None:
    if not staging_root.exists():
        return None
    try:
        shutil.rmtree(staging_root)
    except OSError:
        return str(staging_root)
    return None


def _publish_staging(staging_root: Path, final_root: Path) -> None:
    """Publish a verified staging directory without intentionally replacing state."""
    if final_root.exists():
        raise WorkspaceBackupCollisionError(
            f"Backup already exists and will not be overwritten: {final_root}"
        )
    try:
        os.rename(staging_root, final_root)
    except FileExistsError as error:
        raise WorkspaceBackupCollisionError(
            f"Backup already exists and will not be overwritten: {final_root}"
        ) from error
    except OSError as error:
        raise WorkspaceBackupPublicationError(
            f"Could not publish verified backup: {final_root}"
        ) from error


def create_workspace_backup(
    plan: WorkspaceBackupPlan,
    *,
    services: CoreBackupServices | None = None,
    disk_usage_reader: DiskUsageReader = _read_disk_usage,
    staging_nonce_factory: StagingNonceFactory = _default_staging_nonce,
    file_copier: FileCopier = _copy_regular_file,
    chunk_size: int = BACKUP_COPY_CHUNK_BYTES,
    after_copy_hook: AfterCopyHook | None = None,
    before_publish_hook: BeforePublishHook | None = None,
) -> WorkspaceBackupResult:
    """Create, verify, and publish one reviewed whole-workspace backup."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    active_services = services or load_core_backup_services()

    # All source checks happen before the first destination mutation.
    _recheck_plan_source(plan, active_services)
    _prepare_destination_for_execution(
        plan,
        disk_usage_reader=disk_usage_reader,
    )

    staging_root = _staging_root(plan, staging_nonce_factory())
    try:
        staging_root.mkdir(exist_ok=False)
    except FileExistsError as error:
        raise WorkspaceBackupCollisionError(
            "Backup staging path already exists and will not be overwritten: "
            f"{staging_root}"
        ) from error
    except OSError as error:
        raise WorkspaceBackupCopyError(
            f"Could not create backup staging root: {staging_root}"
        ) from error

    try:
        payload_root = _create_staging_payload(plan, staging_root)
        copied: list[BackupFileEntry] = []
        for source_entry in plan.inventory.files:
            copied.append(
                file_copier(
                    plan.workspace_root,
                    payload_root,
                    source_entry.path,
                    chunk_size,
                )
            )

        if after_copy_hook is not None:
            after_copy_hook(plan.workspace_root, payload_root)

        _verify_source_matches_copied(
            plan,
            copied,
            chunk_size=chunk_size,
        )
        _verify_staged_payload(
            plan,
            payload_root,
            copied,
            chunk_size=chunk_size,
        )
        manifest = create_workspace_backup_manifest(plan, copied)
        manifest_sha256 = _write_verified_manifest(staging_root, manifest)

        if before_publish_hook is not None:
            before_publish_hook(staging_root, plan.final_backup_root)
        _publish_staging(staging_root, plan.final_backup_root)
        return WorkspaceBackupResult(
            final_backup_root=plan.final_backup_root,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
    except WorkspaceBackupError as error:
        remaining = _cleanup_staging(staging_root)
        if remaining is not None:
            raise WorkspaceBackupCopyError(
                f"{error} Incomplete staging remains at: {remaining}"
            ) from error
        raise
    except OSError as error:
        remaining = _cleanup_staging(staging_root)
        message = "Backup creation failed due to a filesystem error."
        if remaining is not None:
            message += f" Incomplete staging remains at: {remaining}"
        raise WorkspaceBackupCopyError(message) from error

__all__ = [
    "BACKUP_COPY_CHUNK_BYTES",
    "BACKUP_HASH_ALGORITHM",
    "BACKUP_MANIFEST_FILENAME",
    "BACKUP_MANIFEST_RECORD_TYPE",
    "BACKUP_MANIFEST_SCHEMA_VERSION",
    "BACKUP_MINIMUM_RESERVE_BYTES",
    "BACKUP_NAME_PREFIX",
    "BACKUP_PAYLOAD_ROOT",
    "BackupFileEntry",
    "BackupSourceFile",
    "CoreBackupServices",
    "WorkspaceBackupCollisionError",
    "WorkspaceBackupCopyError",
    "WorkspaceBackupDestinationError",
    "WorkspaceBackupDriftError",
    "WorkspaceBackupError",
    "WorkspaceBackupInventory",
    "WorkspaceBackupManifest",
    "WorkspaceBackupManifestError",
    "WorkspaceBackupPlan",
    "WorkspaceBackupPublicationError",
    "WorkspaceBackupResult",
    "WorkspaceBackupSourceError",
    "WorkspaceBackupSpaceError",
    "WorkspaceBackupUnsupportedEntryError",
    "WorkspaceBackupVerificationError",
    "backup_name",
    "create_workspace_backup",
    "create_workspace_backup_manifest",
    "inventory_workspace",
    "load_core_backup_services",
    "parse_workspace_backup_manifest",
    "plan_workspace_backup",
    "required_backup_free_bytes",
    "serialize_workspace_backup_manifest",
    "workspace_backup_manifest_sha256",
    "workspace_backup_manifest_to_dict",
]
