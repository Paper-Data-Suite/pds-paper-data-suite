"""#19A2: compare pinned release wheel payloads with installed files, read-only.

This is diagnostic evidence, NOT live Suite paper-dispatch authorization.
It reuses #18's independently pinned official release SHA-256 values; install
metadata, even with matching payload bytes, cannot attest loaded native code,
interpreter isolation, current installed routing profiles or teacher consent.
"""

from __future__ import annotations

import csv
import hashlib
import json
import stat
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from packaging.utils import canonicalize_name

from paper_data_suite.returned_paper_installed_wheels import (
    OFFICIAL_WHEELS,
    OfficialWheel,
    WheelQualificationError,
    verify_official_wheel,
)

_PAYLOAD_AUDIT_VERSION: Final[str] = "1"
_MAX_PAYLOAD_FILES: Final[int] = 4_096
_MAX_PAYLOAD_BYTES: Final[int] = 80 * 1024 * 1024


class InstalledPayloadAuditError(ValueError):
    """Exact wheel / current installed payload evidence was not established."""


@dataclass(frozen=True, slots=True)
class MatchedWheelPayloadV1:
    """One observed payload match, not a source-of-execution certificate."""

    distribution: str
    version: str
    official_wheel_sha256: str
    file_count: int

    def __post_init__(self) -> None:
        if not 1 <= self.file_count <= _MAX_PAYLOAD_FILES:
            raise InstalledPayloadAuditError("invalid audited payload file count")
        if len(self.official_wheel_sha256) != 64:
            raise InstalledPayloadAuditError("invalid wheel digest")


@dataclass(frozen=True, slots=True)
class InstalledPayloadAuditV1:
    """Verified on-disk wheel members; *always* non-authorizing."""

    wheels: tuple[MatchedWheelPayloadV1, ...]
    contract_version: Literal["1"] = "1"
    producer_dispatch_authorized: Literal[False] = False

    def __post_init__(self) -> None:
        if self.contract_version != _PAYLOAD_AUDIT_VERSION:
            raise InstalledPayloadAuditError("unsupported installed-audit contract")
        if self.producer_dispatch_authorized is not False:
            raise InstalledPayloadAuditError("payload audit cannot grant dispatch")
        if type(self.wheels) is not tuple or len(self.wheels) != 3:
            raise InstalledPayloadAuditError("exact three-wheel audit is required")
        if tuple(row.distribution for row in self.wheels) != (
            "pds-core", "scoreform", "quillan"
        ):
            raise InstalledPayloadAuditError("unexpected installed audit owners")


def _not_reparse(path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        value = path.lstat()
    except OSError:
        return False
    attributes = getattr(value, "st_file_attributes", 0)
    return not bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _confined_installed_file(path: Path, environment_root: Path) -> Path:
    """Reject links, missing targets and paths outside the active venv."""
    try:
        root = environment_root.resolve(strict=True)
        absolute = path.absolute()
        target = absolute.resolve(strict=True)
        relative = absolute.relative_to(root)
        if (
            not relative.parts or relative.is_absolute()
            or target != absolute or not target.is_file()
        ):
            raise InstalledPayloadAuditError("installed wheel file is not confined")
        current = root
        for part in relative.parts:
            current = current / part
            if not _not_reparse(current):
                raise InstalledPayloadAuditError("installed wheel path uses a link")
    except (OSError, RuntimeError, ValueError) as error:
        raise InstalledPayloadAuditError(
            "installed wheel file is absent or outside current environment"
        ) from error
    return target


def _installed_distribution(
    specification: OfficialWheel,
    *,
    lookup: Callable[[str], metadata.Distribution],
) -> metadata.Distribution:
    try:
        dist = lookup(specification.distribution)
        observed_name = dist.metadata["Name"]
        observed_version = dist.metadata["Version"]
    except (metadata.PackageNotFoundError, KeyError, OSError, ValueError) as error:
        raise InstalledPayloadAuditError(
            "installed distribution unavailable"
        ) from error
    if (
        not isinstance(observed_name, str)
        or not isinstance(observed_version, str)
        or canonicalize_name(observed_name)
        != canonicalize_name(specification.distribution)
        or observed_version != specification.version
    ):
        raise InstalledPayloadAuditError("installed distribution identity mismatch")
    try:
        source = dist.read_text("direct_url.json")
    except (OSError, UnicodeError) as error:
        raise InstalledPayloadAuditError(
            "installed origin metadata unreadable"
        ) from error
    if source is not None:
        try:
            info = json.loads(source)
        except (ValueError, TypeError) as error:
            raise InstalledPayloadAuditError(
                "invalid installed origin metadata"
            ) from error
        if not isinstance(info, dict):
            raise InstalledPayloadAuditError("invalid installed origin metadata")
        directory = info.get("dir_info")
        if isinstance(directory, dict) and directory.get("editable") is True:
            raise InstalledPayloadAuditError("editable installed distribution refused")
    return dist


def _audit_one(
    wheelhouse: Path,
    specification: OfficialWheel,
    *,
    environment_root: Path,
    distribution_lookup: Callable[[str], metadata.Distribution],
) -> MatchedWheelPayloadV1:
    try:
        wheel_path = verify_official_wheel(wheelhouse, specification)
    except (WheelQualificationError, OSError) as error:
        raise InstalledPayloadAuditError("pinned release wheel unavailable") from error
    dist = _installed_distribution(specification, lookup=distribution_lookup)
    try:
        files = dist.files
    except (TypeError, ValueError, UnicodeError, OSError, csv.Error) as error:
        raise InstalledPayloadAuditError(
            "installed RECORD inventory malformed"
        ) from error
    if files is None or len(files) > _MAX_PAYLOAD_FILES * 2:
        raise InstalledPayloadAuditError("installed RECORD inventory unavailable")
    owned = {str(item).replace("\\", "/") for item in files}
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            archive_members = tuple(
                entry for entry in archive.infolist() if not entry.is_dir()
            )
            if not archive_members or len(archive_members) > _MAX_PAYLOAD_FILES:
                raise InstalledPayloadAuditError("wheel payload member count invalid")
            total = 0
            checked = 0
            for entry in archive_members:
                name = entry.filename
                pure = PurePosixPath(name)
                if (
                    name.startswith("/") or "\\" in name
                    or any(part in (".", "..") for part in pure.parts)
                    or any(part.endswith(".data") for part in pure.parts)
                ):
                    raise InstalledPayloadAuditError("unsupported wheel data layout")
                if name.endswith(".dist-info/RECORD"):
                    # Pip rewrites RECORD during normal installation.
                    continue
                total += entry.file_size
                if total > _MAX_PAYLOAD_BYTES or name not in owned:
                    raise InstalledPayloadAuditError("wheel payload not installed")
                installed_path = _confined_installed_file(
                    Path(str(dist.locate_file(name))), environment_root
                )
                with archive.open(entry) as source:
                    expected = hashlib.sha256(source.read()).digest()
                actual = hashlib.sha256()
                with installed_path.open("rb") as installed:
                    while block := installed.read(1024 * 1024):
                        actual.update(block)
                if actual.digest() != expected:
                    raise InstalledPayloadAuditError("installed payload differs")
                checked += 1
    except (OSError, UnicodeError, zipfile.BadZipFile, RuntimeError) as error:
        raise InstalledPayloadAuditError("wheel payload inspection refused") from error
    if checked < 2:
        raise InstalledPayloadAuditError("wheel payload has too few verified files")
    return MatchedWheelPayloadV1(
        specification.distribution, specification.version,
        specification.sha256, checked,
    )


def audit_installed_paper_payloads(
    wheelhouse: Path,
    *,
    environment_root: Path | None = None,
    distribution_lookup: Callable[[str], metadata.Distribution] = (
        metadata.distribution
    ),
    specifications: tuple[OfficialWheel, ...] = OFFICIAL_WHEELS,
) -> InstalledPayloadAuditV1:
    """Match pinned wheel payloads to disk; never produce dispatcher permission.

    The explicit lookup/specification seams support synthetic tests only. This
    audit cannot qualify a live producer even if all file hashes match.
    """
    if not isinstance(wheelhouse, Path) or (
        environment_root is not None and not isinstance(environment_root, Path)
    ):
        raise InstalledPayloadAuditError("explicit wheelhouse and valid root needed")
    if (
        type(specifications) is not tuple or len(specifications) != 3
        or any(not isinstance(s, OfficialWheel) for s in specifications)
        or tuple(s.distribution for s in specifications) != (
            "pds-core", "scoreform", "quillan"
        )
    ):
        raise InstalledPayloadAuditError("exact published producer subset required")
    root = environment_root if environment_root is not None else Path(sys.prefix)
    if not root.is_dir() or not callable(distribution_lookup):
        raise InstalledPayloadAuditError("active environment unavailable")
    rows = tuple(
        _audit_one(
            wheelhouse, specification, environment_root=root,
            distribution_lookup=distribution_lookup,
        )
        for specification in specifications
    )
    return InstalledPayloadAuditV1(rows)


__all__ = (
    "InstalledPayloadAuditError",
    "InstalledPayloadAuditV1",
    "MatchedWheelPayloadV1",
    "audit_installed_paper_payloads",
)
