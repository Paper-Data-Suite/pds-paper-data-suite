"""Issue #49 Slice 98: recheck signed release bytes against installed code.

This is a **non-authorizing** bridge from signed release verification to observed
installed files. It never imports application code, installs, starts a process,
or treats an on-disk receipt or caller-created dataclass as a trust anchor.
A separately protected installation head, OS/native executable custody, and
transitive signed installation qualification remain necessary for production
launch. This module deliberately has no execute/permit API.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import stat
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Final

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_release_artifacts import (
    ReleaseArtifactError,
    verify_signed_release_wheel,
)

_APPROVED: Final = frozenset(
    {"quillan", "scoreform", "concord", "meridian", "vitrine", "portia"}
)
_MAX_RECORD: Final = 2_000_000
_MAX_MEMBERS: Final = 20_000
_MAX_FILE: Final = 60_000_000
_MAX_TOTAL: Final = 400_000_000
_SHA_B64: Final = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class InstalledLaunchEvidenceError(ValueError):
    """Fail closed on identity, installed bytes, dependency or launcher drift."""


@dataclass(frozen=True, slots=True)
class InstalledSignedLaunchObservation:
    """Signed wheel matches observed files, NEVER a launch/activation grant."""

    component_id: str
    distribution: str
    version: str
    wheel_sha256: str
    console_script: str
    console_target: str
    files_checked: int
    runtime_dependencies_checked: int
    status: str = "SIGNED_WHEEL_INSTALLED_BYTES_MATCH_OBSERVED_ONLY"
    authority: str = "NO_LAUNCH_ACTIVATION_UPDATE_OR_INTEGRATION_AUTHORITY"


def _ordinary(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return not (
        stat.S_ISLNK(info.st_mode)
        or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(root.resolve()))) == str(
            root.resolve()
        )
    except (OSError, ValueError):
        return False


def _safe_relative(name: str) -> bool:
    return bool(
        name
        and not name.startswith("/")
        and ":" not in name
        and "\\" not in name
        and all(p not in {"", ".", ".."} for p in name.split("/"))
    )


def _record_rows(raw: bytes) -> dict[str, tuple[str, str]]:
    if not raw or len(raw) > _MAX_RECORD:
        raise InstalledLaunchEvidenceError("wheel RECORD outside bounds")
    try:
        rows = csv.reader(io.StringIO(raw.decode("utf-8")), strict=True)
        found: dict[str, tuple[str, str]] = {}
        for i, row in enumerate(rows):
            if i >= _MAX_MEMBERS or len(row) != 3 or not _safe_relative(row[0]):
                raise InstalledLaunchEvidenceError("invalid RECORD row or path")
            if row[0] in found:
                raise InstalledLaunchEvidenceError("duplicate RECORD path")
            found[row[0]] = (row[1], row[2])
        return found
    except (csv.Error, UnicodeError) as error:
        raise InstalledLaunchEvidenceError("wheel RECORD is unreadable") from error


def _verify_installed_bytes(
    wheel: Path, dist: metadata.Distribution, environment: Path
) -> int:
    """Match original signed wheel file hashes to installed files, not local RECORD.

    Compiled bytecode and pip-generated wrappers are not signed wheel members.
    The wheel RECORD itself changes on installation and is excluded explicitly.
    Any unsupported wheel .data layout is refused rather than guessed.
    """
    checked = 0
    total = 0
    try:
        if not _ordinary(wheel):
            raise InstalledLaunchEvidenceError("signed wheel path is a reparse point")
        with zipfile.ZipFile(wheel) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= _MAX_MEMBERS:
                raise InstalledLaunchEvidenceError("wheel member count invalid")
            record_files = [
                i.filename for i in members if i.filename.endswith(".dist-info/RECORD")
            ]
            if len(record_files) != 1:
                raise InstalledLaunchEvidenceError("wheel RECORD identity ambiguous")
            if archive.getinfo(record_files[0]).file_size > _MAX_RECORD:
                raise InstalledLaunchEvidenceError("wheel RECORD exceeds bounds")
            rows = _record_rows(archive.read(record_files[0]))
            names: set[str] = set()
            for item in members:
                name = item.filename
                if (
                    name in names
                    or not _safe_relative(name[:-1] if name.endswith("/") else name)
                    or item.orig_filename != name
                ):
                    raise InstalledLaunchEvidenceError(
                        "unsafe or duplicate wheel member"
                    )
                names.add(name)
                if name.endswith("/"):
                    continue
                if name.endswith(".dist-info/RECORD"):
                    continue
                if ".data/" in name:
                    raise InstalledLaunchEvidenceError("unsupported wheel data layout")
                if item.file_size > _MAX_FILE or total + item.file_size > _MAX_TOTAL:
                    raise InstalledLaunchEvidenceError("wheel file budget exceeded")
                digest, size = rows.get(name, ("", ""))
                if (
                    not digest.startswith("sha256=")
                    or not _SHA_B64.fullmatch(digest.removeprefix("sha256="))
                    or size != str(item.file_size)
                ):
                    raise InstalledLaunchEvidenceError(
                        "wheel RECORD lacks exact digest"
                    )
                expected = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(archive.read(item)).digest()
                    )
                    .rstrip(b"=")
                    .decode("ascii")
                )
                if digest.removeprefix("sha256=") != expected:
                    raise InstalledLaunchEvidenceError("wheel RECORD content drift")
                path = Path(str(dist.locate_file(name)))
                if not _inside(path, environment) or not path.is_file():
                    raise InstalledLaunchEvidenceError(
                        "installed file outside environment"
                    )
                if not _ordinary(path):
                    raise InstalledLaunchEvidenceError(
                        "installed file is a reparse point"
                    )
                if path.stat().st_size != item.file_size:
                    raise InstalledLaunchEvidenceError("installed file size changed")
                h = hashlib.sha256()
                with path.open("rb") as handle:
                    while chunk := handle.read(65536):
                        h.update(chunk)
                if (
                    base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode()
                    != expected
                ):
                    raise InstalledLaunchEvidenceError(
                        "installed file differs from signed wheel"
                    )
                checked += 1
                total += item.file_size
            file_names = {n for n in names if not n.endswith("/")}
            if checked == 0 or set(rows) != file_names:
                raise InstalledLaunchEvidenceError("incomplete wheel RECORD")
    except (OSError, RuntimeError, ValueError, KeyError, zipfile.BadZipFile) as error:
        if isinstance(error, InstalledLaunchEvidenceError):
            raise
        raise InstalledLaunchEvidenceError(
            "wheel/installation verification failed"
        ) from error
    return checked


def _runtime_dependencies(
    requirements: tuple[str, ...],
) -> int:
    checked = 0
    environment: dict[str, str] = {
        key: str(value) for key, value in default_environment().items()
    }
    environment["extra"] = ""
    for raw in requirements:
        try:
            item = Requirement(raw)
        except InvalidRequirement as error:
            raise InstalledLaunchEvidenceError(
                "invalid signed runtime dependency"
            ) from error
        if item.url is not None:
            raise InstalledLaunchEvidenceError("direct-URL runtime dependency refused")
        if item.marker is not None and not item.marker.evaluate(environment):
            continue
        checked += 1
        try:
            installed = metadata.version(item.name)
        except metadata.PackageNotFoundError as error:
            raise InstalledLaunchEvidenceError(
                "required distribution unavailable"
            ) from error
        if item.specifier and not item.specifier.contains(installed):
            raise InstalledLaunchEvidenceError("runtime dependency version mismatch")
    return checked


def inspect_signed_installed_launch_candidate(
    component_id: str,
    *,
    wheel: Path,
    registry_envelope: bytes,
    module_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    version: str,
) -> InstalledSignedLaunchObservation:
    """Reverify signed bytes and installed files for the RUNNING interpreter.

    Caller must obtain `trust` through an independently pinned provisioner and
    enforce signed catalog anti-rollback separately. Even when matching, this
    result lacks protected active installation receipt, complete transitive
    artifact authentication, and OS/native executable provenance. It MUST NOT
    be passed to `launch_application` as a permission token.
    """
    if component_id not in _APPROVED or not isinstance(wheel, Path):
        raise InstalledLaunchEvidenceError("unknown or invalid module identity")
    try:
        signed = verify_signed_release_wheel(
            wheel,
            registry_envelope=registry_envelope,
            module_envelope=module_envelope,
            trust=trust,
            now=now,
            version=version,
        )
    except (ReleaseArtifactError, OSError, ValueError) as error:
        raise InstalledLaunchEvidenceError("signed wheel validation refused") from error
    if signed.component_id != component_id:
        raise InstalledLaunchEvidenceError("signed component differs from selection")
    try:
        dist = metadata.distribution(signed.distribution)
        actual = canonicalize_name(dist.metadata["Name"] or "")
        installed_version = dist.version
    except (metadata.PackageNotFoundError, KeyError, ValueError) as error:
        raise InstalledLaunchEvidenceError(
            "signed distribution not installed"
        ) from error
    if (
        actual != canonicalize_name(signed.distribution)
        or installed_version != signed.version
        or not _inside(Path(str(dist.locate_file(""))), Path(sys.prefix))
    ):
        raise InstalledLaunchEvidenceError("installed distribution identity mismatch")
    scripts = [
        ep
        for ep in metadata.entry_points(group="console_scripts")
        if ep.name.casefold() == signed.console_script.casefold()
    ]
    if (
        len(scripts) != 1
        or scripts[0].dist is None
        or (
            canonicalize_name(scripts[0].dist.name) != actual
            or scripts[0].name != signed.console_script
            or scripts[0].value != signed.console_target
        )
    ):
        raise InstalledLaunchEvidenceError("console launcher owner/target mismatch")
    checked = _verify_installed_bytes(wheel, dist, Path(sys.prefix))
    dependencies = _runtime_dependencies(signed.requires_dist)
    return InstalledSignedLaunchObservation(
        component_id=component_id,
        distribution=actual,
        version=signed.version,
        wheel_sha256=signed.sha256,
        console_script=signed.console_script,
        console_target=signed.console_target,
        files_checked=checked,
        runtime_dependencies_checked=dependencies,
    )


__all__ = (
    "InstalledLaunchEvidenceError",
    "InstalledSignedLaunchObservation",
    "inspect_signed_installed_launch_candidate",
)
