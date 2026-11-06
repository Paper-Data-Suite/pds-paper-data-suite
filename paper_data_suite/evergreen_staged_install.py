"""Issue #49: read-only, exact-wheel staged site-packages audit.

A successful audit establishes ONLY a match in a restricted, isolated staging
layout. It does not attest the installer, Python interpreter, generated launchers,
active environment, native loader, publisher delegation or lasting immutability.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Final

from paper_data_suite.evergreen_catalog_verification import (
    RevisionCheckpoint,
    TrustedKeyring,
)
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    verify_prepared_record_against_wheelhouse,
)

_MAX_INSTALLED_FILES: Final = 30000
_MAX_RECORD_BYTES: Final = 2 * 1024 * 1024
_MAX_RELATIVE_LENGTH: Final = 400
_MAX_FILE_BYTES: Final = 512 * 1024 * 1024


class StageAuditError(ValueError):
    """A supposedly isolated candidate installation cannot be verified."""


@dataclass(frozen=True, slots=True)
class AuditedInstalledFile:
    """One staged file that matched exact authenticated wheel content."""

    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class StagedSiteAudit:
    """One-time observation only; never a trusted ACTIVE install receipt."""

    transaction_id: str
    registry_payload_sha256: str
    lock_payload_sha256: str
    stage_site: Path
    distributions: tuple[str, ...]
    files: tuple[AuditedInstalledFile, ...]


def _reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & 0x400)


def _regular(path: Path) -> None:
    if _reparse(path) or not stat.S_ISREG(path.lstat().st_mode):
        raise StageAuditError("staged files must be ordinary, nonsymlink files")


def _safe_relative(value: str) -> None:
    if (
        not value
        or len(value) > _MAX_RELATIVE_LENGTH
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise StageAuditError("unsafe staged relative path")


def _walk_stage(site: Path) -> dict[str, Path]:
    if not site.is_dir() or _reparse(site):
        raise StageAuditError("staged site-packages directory invalid")
    found: dict[str, Path] = {}
    pending = [site]
    while pending:
        directory = pending.pop()
        for item in directory.iterdir():
            if _reparse(item):
                raise StageAuditError("staged directory contains a reparse point")
            relative = item.relative_to(site).as_posix()
            _safe_relative(relative)
            mode = item.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(item)
            elif stat.S_ISREG(mode):
                if relative in found:
                    raise StageAuditError("duplicate staged file")
                found[relative] = item
                if len(found) > _MAX_INSTALLED_FILES:
                    raise StageAuditError("staged file count exceeds bound")
            else:
                raise StageAuditError("staged directory contains special file")
    return found


def _sha_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while part := handle.read(1024 * 1024):
            length += len(part)
            if length > _MAX_FILE_BYTES:
                raise StageAuditError("staged file exceeds size bound")
            digest.update(part)
    return digest.hexdigest(), length


def _sha_handle(handle: BinaryIO) -> str:
    sha = hashlib.sha256()
    while block := handle.read(1024 * 1024):
        sha.update(block)
    return sha.hexdigest()


def _sha_archive_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    if member.file_size > _MAX_FILE_BYTES:
        raise StageAuditError("wheel payload file exceeds size bound")
    sha = hashlib.sha256()
    length = 0
    with archive.open(member) as source:
        while chunk := source.read(1024 * 1024):
            length += len(chunk)
            if length > _MAX_FILE_BYTES:
                raise StageAuditError("wheel member expands beyond bound")
            sha.update(chunk)
    if length != member.file_size:
        raise StageAuditError("truncated wheel member")
    return sha.hexdigest()


def _wheel_expectations(
    wheelhouse: Path, wheels: tuple[tuple[str, str], ...]
) -> tuple[dict[str, tuple[str, int]], dict[str, set[str]]]:
    expected: dict[str, tuple[str, int]] = {}
    records: dict[str, set[str]] = {}
    for filename, signed_digest in wheels:
        wheel = wheelhouse / filename
        try:
            if _reparse(wheel) or not wheel.is_file():
                raise StageAuditError("staged source wheel is not an ordinary file")
            with wheel.open("rb") as stream:
                if _sha_handle(stream) != signed_digest:
                    raise StageAuditError("source wheel changed after lock inspection")
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive:
                    entries = archive.infolist()
                    record_names = [
                        info.filename
                        for info in entries
                        if info.filename.endswith(".dist-info/RECORD")
                    ]
                    if len(record_names) != 1:
                        raise StageAuditError("wheel has no unique RECORD")
                    record_name = record_names[0]
                    owned: set[str] = set()
                    for item in entries:
                        relative = item.filename
                        if relative.endswith("/"):
                            continue
                        _safe_relative(relative)
                        if item.orig_filename != relative:
                            raise StageAuditError("wheel member name was normalized")
                        owned.add(relative)
                        if ".data/" in relative:
                            raise StageAuditError("unsupported staged wheel layout")
                        if relative in expected:
                            raise StageAuditError(
                                "staged wheels claim overlapping files"
                            )
                        if relative == record_name:
                            expected[relative] = ("", -1)
                            records[record_name] = owned
                        else:
                            expected[relative] = (
                                _sha_archive_member(archive, item),
                                item.file_size,
                            )
                stream.seek(0)
                if _sha_handle(stream) != signed_digest:
                    raise StageAuditError("source wheel mutated during inspection")
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise StageAuditError("source wheel could not be read") from error
    return expected, records


def _record_entries(raw: bytes) -> dict[str, tuple[str, int]]:
    if len(raw) > _MAX_RECORD_BYTES:
        raise StageAuditError("installed RECORD exceeds size bound")
    try:
        text = raw.decode("utf-8")
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        found: dict[str, tuple[str, int]] = {}
        for row in rows:
            if len(row) != 3:
                raise StageAuditError("malformed installed RECORD row")
            name, encoded, size_raw = row
            _safe_relative(name)
            if name in found:
                raise StageAuditError("duplicate installed RECORD entry")
            if not encoded or not size_raw:
                if encoded or size_raw or not name.endswith(".dist-info/RECORD"):
                    raise StageAuditError("unhashed staged file in RECORD")
                found[name] = ("", -1)
                continue
            if not encoded.startswith("sha256="):
                raise StageAuditError("unsupported installed RECORD hash")
            hash_bytes = encoded[7:]
            if not hash_bytes or "=" in hash_bytes:
                raise StageAuditError("noncanonical installed RECORD hash")
            raw_digest = base64.urlsafe_b64decode(
                hash_bytes + "=" * (-len(hash_bytes) % 4)
            )
            if (
                len(raw_digest) != 32
                or base64.urlsafe_b64encode(raw_digest).decode().rstrip("=")
                != hash_bytes
            ):
                raise StageAuditError("invalid installed RECORD hash")
            if not size_raw.isascii() or not size_raw.isdecimal():
                raise StageAuditError("invalid installed RECORD size")
            found[name] = (raw_digest.hex(), int(size_raw))
        return found
    except (UnicodeDecodeError, csv.Error, ValueError) as error:
        raise StageAuditError("malformed installed RECORD") from error


def audit_staged_site_packages(
    stage_root: Path,
    wheelhouse: Path,
    *,
    prepared_record: bytes,
    lock_envelope: bytes,
    registry_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    checkpoint: RevisionCheckpoint | None = None,
) -> StagedSiteAudit:
    """Check staged purelib bytes against reauthenticated signed wheelhouse.

    The only supported layout is stage_root/site-packages for already-installed
    purelib wheels. No executable, pip, site-package import or workspace access.
    Real installers with .data schemes and generated scripts are not yet covered.
    """
    if not isinstance(stage_root, Path) or not isinstance(wheelhouse, Path):
        raise StageAuditError("stage root and wheelhouse must be Path")
    root = stage_root.absolute()
    if not root.is_dir() or _reparse(root):
        raise StageAuditError("stage root must be a regular directory")
    if root.resolve() in {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}:
        raise StageAuditError("refusing audit of active interpreter environment")
    site = root / "site-packages"
    if not site.is_dir() or _reparse(site):
        raise StageAuditError("stage must contain isolated site-packages")
    try:
        record = verify_prepared_record_against_wheelhouse(
            prepared_record,
            wheelhouse,
            lock_envelope=lock_envelope,
            registry_envelope=registry_envelope,
            trust=trust,
            now=now,
            checkpoint=checkpoint,
        )
    except (PreparedRecordError, ValueError, OSError) as error:
        raise StageAuditError(
            "prepared record or signed wheelhouse mismatch"
        ) from error
    expected, records = _wheel_expectations(
        wheelhouse, tuple((item.filename, item.sha256) for item in record.wheels)
    )
    installed = _walk_stage(site)
    if set(installed) != set(expected):
        raise StageAuditError("staged file set differs from authenticated wheels")
    observed: dict[str, AuditedInstalledFile] = {}
    for relative, path in installed.items():
        digest, size = _sha_file(path)
        expected_digest, expected_size = expected[relative]
        if expected_size >= 0 and (digest, size) != (expected_digest, expected_size):
            raise StageAuditError("staged file bytes disagree with signed wheel")
        observed[relative] = AuditedInstalledFile(relative, digest, size)
    for record_path, owned in records.items():
        with installed[record_path].open("rb") as handle:
            entries = _record_entries(handle.read(_MAX_RECORD_BYTES + 1))
        if set(entries) != owned:
            raise StageAuditError("installed RECORD has missing/foreign files")
        for relative, (digest, size) in entries.items():
            if relative not in expected:
                raise StageAuditError("RECORD names unexpected file")
            if (digest, size) != (
                ("", -1)
                if relative == record_path
                else (observed[relative].sha256, observed[relative].size)
            ):
                raise StageAuditError("installed RECORD hash or size disagrees")
    return StagedSiteAudit(
        record.transaction_id,
        record.registry_payload_sha256,
        record.lock_payload_sha256,
        site,
        tuple(w.distribution for w in record.wheels),
        tuple(observed[key] for key in sorted(observed)),
    )


__all__ = (
    "AuditedInstalledFile",
    "StageAuditError",
    "StagedSiteAudit",
    "audit_staged_site_packages",
)
