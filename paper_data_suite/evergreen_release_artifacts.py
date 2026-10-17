"""Issue #49: verify exact wheel bytes against live signed release envelopes.

No extraction, installation, Python import, network lookup, workspace access or
permission to launch occurs. The registry and module envelopes are VERIFIED on
this call, not accepted as caller-constructed Verified* dataclasses.
"""

from __future__ import annotations

import configparser
import hashlib
import zipfile
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import BinaryIO, Final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

from paper_data_suite.evergreen_catalog_verification import (
    CatalogVerificationError,
    TrustedKeyring,
    verify_module_document,
    verify_registry_document,
)

_MAX_WHEEL_BYTES: Final = 512 * 1024 * 1024
_MAX_MEMBERS: Final = 20000
_MAX_METADATA_BYTES: Final = 128 * 1024
_MAX_ENTRY_BYTES: Final = 32 * 1024
_MAX_WHEEL_INFO_BYTES: Final = 16 * 1024


class ReleaseArtifactError(ValueError):
    """Wheel is not the exact signed artifact or its metadata disagrees."""


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    """Preserve exact entry-point names without monkey-patching methods."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True, slots=True)
class VerifiedReleaseWheel:
    """Authenticated wheel bytes and metadata; NOT an installation receipt."""

    component_id: str
    distribution: str
    version: str
    filename: str
    sha256: str
    publisher_payload_sha256: str
    registry_payload_sha256: str
    requires_dist: tuple[str, ...]
    console_script: str
    console_target: str


def _one_header(message: Message, name: str) -> str:
    matches = message.get_all(name, [])
    if len(matches) != 1:
        raise ReleaseArtifactError(f"wheel must have exactly one {name}")
    return str(matches[0]).strip()


def _file_hash(stream: BinaryIO) -> str:
    """Hash the already-open wheel; caller controls its read position."""
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _read_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    item = archive.getinfo(name)
    if item.file_size > limit:
        raise ReleaseArtifactError("oversized wheel metadata")
    with archive.open(item) as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ReleaseArtifactError("oversized wheel metadata")
    return raw


def _check_member_names(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if not members or len(members) > _MAX_MEMBERS:
        raise ReleaseArtifactError("invalid wheel member count")
    seen: set[str] = set()
    for item in members:
        name = item.filename
        segments = name.split("/")
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or ":" in name
            or any(part in {"", ".", ".."} for part in segments[:-1])
            or segments[-1] in {".", ".."}
            or name in seen
        ):
            raise ReleaseArtifactError("unsafe or duplicate wheel member")
        # UNIX symlinks are not normal installable wheel members.
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise ReleaseArtifactError("wheel contains symbolic link")
        seen.add(name)


def _read_metadata(
    archive: zipfile.ZipFile, *, distribution: str, version: str
) -> tuple[Message, str]:
    names = archive.namelist()
    prefixes = {name.split("/")[0] for name in names if ".dist-info/" in name}
    if len(prefixes) != 1:
        raise ReleaseArtifactError("wheel must have one dist-info directory")
    prefix = next(iter(prefixes))
    normalized = canonicalize_name(distribution).replace("-", "_")
    expected = f"{normalized}-{version}.dist-info"
    if prefix.lower() != expected.lower():
        raise ReleaseArtifactError("dist-info directory identity mismatch")
    required = {f"{prefix}/METADATA", f"{prefix}/WHEEL", f"{prefix}/RECORD"}
    if not required <= set(names):
        raise ReleaseArtifactError("wheel is missing required metadata")
    _read_member(archive, f"{prefix}/WHEEL", _MAX_WHEEL_INFO_BYTES)
    raw = _read_member(archive, f"{prefix}/METADATA", _MAX_METADATA_BYTES)
    return BytesParser(policy=policy.default).parsebytes(raw), prefix


def _console_entry(archive: zipfile.ZipFile, prefix: str) -> tuple[str, str]:
    name = f"{prefix}/entry_points.txt"
    if name not in archive.namelist():
        raise ReleaseArtifactError("wheel console entry_points.txt missing")
    try:
        raw = _read_member(archive, name, _MAX_ENTRY_BYTES).decode("utf-8")
        parser = _CaseSensitiveConfigParser(interpolation=None, strict=True)
        parser.read_string(raw)
    except (UnicodeDecodeError, configparser.Error) as error:
        raise ReleaseArtifactError("invalid wheel entry point metadata") from error
    if not parser.has_section("console_scripts"):
        raise ReleaseArtifactError("wheel console script section missing")
    console = dict(parser.items("console_scripts"))
    if len(console) != 1:
        raise ReleaseArtifactError("wheel has undeclared console scripts")
    return next(iter(console.items()))


def verify_signed_release_wheel(
    path: Path,
    *,
    registry_envelope: bytes,
    module_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    version: str,
) -> VerifiedReleaseWheel:
    """Reverify both signatures, match selected signed release and wheel bytes.

    The trusted keyring must come from an independently pinned provisioning
    path; caller must also enforce historical monotonic checkpoints separately.
    """
    try:
        registry = verify_registry_document(registry_envelope, trust=trust, now=now)
        module = verify_module_document(
            module_envelope, registry=registry, trust=trust, now=now
        )
    except CatalogVerificationError as error:
        raise ReleaseArtifactError("release metadata authenticity failed") from error
    found = [item for item in module.claims.releases if item.version == version]
    if len(found) != 1:
        raise ReleaseArtifactError("signed release version not present")
    release = found[0]
    if release.revoked:
        raise ReleaseArtifactError("signed release is revoked")
    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise ReleaseArtifactError("wheel must be a regular, nonsymlink file")
    if path.name != release.wheel:
        raise ReleaseArtifactError("wheel filename differs from signed release")
    if not 1 <= path.stat().st_size <= _MAX_WHEEL_BYTES:
        raise ReleaseArtifactError("wheel size outside accepted bounds")
    try:
        wheel_name, wheel_version, _, _ = parse_wheel_filename(path.name)
    except ValueError as error:
        raise ReleaseArtifactError("invalid wheel filename") from error
    if (
        wheel_name != canonicalize_name(module.claims.distribution)
        or str(wheel_version) != release.version
    ):
        raise ReleaseArtifactError("wheel filename package identity mismatch")
    try:
        with path.open("rb") as stream:
            if _file_hash(stream) != release.sha256:
                raise ReleaseArtifactError("wheel hash differs from signed release")
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                _check_member_names(archive)
                metadata, prefix = _read_metadata(
                    archive,
                    distribution=module.claims.distribution,
                    version=release.version,
                )
                console_name, console_target = _console_entry(archive, prefix)
            stream.seek(0)
            if _file_hash(stream) != release.sha256:
                raise ReleaseArtifactError("wheel changed during metadata inspection")
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        raise ReleaseArtifactError("wheel metadata could not be inspected") from error
    if canonicalize_name(_one_header(metadata, "Name")) != wheel_name:
        raise ReleaseArtifactError("wheel metadata distribution mismatch")
    if _one_header(metadata, "Version") != release.version:
        raise ReleaseArtifactError("wheel metadata version mismatch")
    if _one_header(metadata, "Requires-Python") != release.requires_python:
        raise ReleaseArtifactError("wheel Requires-Python mismatch")
    dependencies = tuple(
        str(value).strip() for value in metadata.get_all("Requires-Dist", [])
    )
    if dependencies != release.requires_dist:
        raise ReleaseArtifactError("wheel Requires-Dist mismatch")
    try:
        for dependency in dependencies:
            Requirement(dependency)
    except InvalidRequirement as error:
        raise ReleaseArtifactError("invalid wheel Requires-Dist syntax") from error
    if (console_name, console_target) != (
        release.console_script,
        release.console_target,
    ):
        raise ReleaseArtifactError("wheel console script identity mismatch")
    return VerifiedReleaseWheel(
        module.claims.component_id,
        module.claims.distribution,
        release.version,
        path.name,
        release.sha256,
        module.payload_sha256,
        registry.payload_sha256,
        dependencies,
        console_name,
        console_target,
    )


__all__ = (
    "ReleaseArtifactError",
    "VerifiedReleaseWheel",
    "verify_signed_release_wheel",
)
