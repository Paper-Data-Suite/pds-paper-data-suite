"""Reusable authentication for exact Paper Data Suite release artifacts."""

from __future__ import annotations

import configparser
import hashlib
import re
import zipfile
from collections.abc import Sequence
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from paper_data_suite.compatibility import (
    ComponentCompatibility,
    EntryPointExpectation,
    load_release_compatibility_manifest,
)

_ALLOWED_ENTRY_POINT_GROUPS = (
    "console_scripts",
    "paper_data_suite.modules",
    "paper_data_suite.publication_producers",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactVerificationError(RuntimeError):
    """Raised when an artifact disagrees with an authenticated release contract."""


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def normalize_sha256(value: str) -> str:
    """Return one canonical lowercase SHA-256 or reject malformed input."""
    normalized = value.strip().lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise ArtifactVerificationError(
            "expected SHA-256 must be exactly 64 hexadecimal characters"
        )
    return normalized


def sha256_file(path: Path) -> str:
    """Calculate SHA-256 for one existing ordinary file."""
    artifact = path.resolve()
    if not artifact.is_file():
        raise ArtifactVerificationError(
            f"artifact must be an existing file: {artifact}"
        )

    digest = hashlib.sha256()
    try:
        with artifact.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ArtifactVerificationError(
            f"artifact could not be read: {artifact}"
        ) from error
    return digest.hexdigest()


def verify_file_sha256(path: Path, expected_sha256: str) -> str:
    """Authenticate one file against an explicit external SHA-256."""
    expected = normalize_sha256(expected_sha256)
    actual = sha256_file(path)
    if actual != expected:
        raise ArtifactVerificationError(
            f"SHA-256 mismatch: expected {expected}, got {actual}"
        )
    return actual


def _single_metadata_value(message: Message, field: str, label: str) -> str:
    values = message.get_all(field, [])
    if len(values) != 1:
        raise ArtifactVerificationError(
            f"{label} must contain exactly one {field} metadata field"
        )
    return str(values[0]).strip()


def _expected_entry_points(
    expectations: Sequence[EntryPointExpectation],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {
        group: {} for group in _ALLOWED_ENTRY_POINT_GROUPS
    }
    for item in expectations:
        result[item.group][item.name] = item.target
    return result


def _read_entry_points(
    archive: zipfile.ZipFile,
    names: Sequence[str],
) -> dict[str, dict[str, str]]:
    members = tuple(
        name for name in names if name.endswith(".dist-info/entry_points.txt")
    )
    if not members:
        return {group: {} for group in _ALLOWED_ENTRY_POINT_GROUPS}
    if len(members) != 1:
        raise ArtifactVerificationError(
            "wheel must contain at most one top-level entry_points.txt"
        )

    parser = _CaseSensitiveConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(archive.read(members[0]).decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as error:
        raise ArtifactVerificationError(
            "wheel entry_points.txt is invalid"
        ) from error

    unexpected_groups = sorted(
        set(parser.sections()) - set(_ALLOWED_ENTRY_POINT_GROUPS)
    )
    if unexpected_groups:
        raise ArtifactVerificationError(
            "wheel exposes undeclared entry-point groups: "
            + ", ".join(unexpected_groups)
        )

    return {
        group: dict(sorted(parser.items(group)))
        if parser.has_section(group)
        else {}
        for group in _ALLOWED_ENTRY_POINT_GROUPS
    }


def verify_component_wheel(
    component: ComponentCompatibility,
    path: Path,
) -> None:
    """Verify one exact component wheel without installing or importing it."""
    wheel = path.resolve()
    label = f"{component.component_id} wheel"

    if wheel.name != component.release.wheel:
        raise ArtifactVerificationError(
            f"{label} filename mismatch: expected {component.release.wheel!r}, "
            f"got {wheel.name!r}"
        )
    if not wheel.is_file():
        raise ArtifactVerificationError(f"{label} is missing: {wheel}")

    try:
        actual_digest = verify_file_sha256(wheel, component.release.sha256)
    except ArtifactVerificationError as error:
        raise ArtifactVerificationError(f"{label} {error}") from error

    try:
        with zipfile.ZipFile(wheel) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise ArtifactVerificationError(
                    f"{label} contains corrupt member: {corrupt_member}"
                )
            names = tuple(archive.namelist())
            metadata_members = tuple(
                name for name in names if name.endswith(".dist-info/METADATA")
            )
            if len(metadata_members) != 1:
                raise ArtifactVerificationError(
                    f"{label} must contain exactly one METADATA file"
                )
            metadata = BytesParser(policy=policy.default).parsebytes(
                archive.read(metadata_members[0])
            )
            entry_points = _read_entry_points(archive, names)
    except zipfile.BadZipFile as error:
        raise ArtifactVerificationError(
            f"{label} is not a readable wheel ZIP"
        ) from error

    if actual_digest != component.release.sha256:
        raise ArtifactVerificationError(f"{label} SHA-256 verification failed")
    if _single_metadata_value(metadata, "Name", label) != component.distribution:
        raise ArtifactVerificationError(
            f"{label} distribution identity mismatch"
        )
    if _single_metadata_value(metadata, "Version", label) != component.version:
        raise ArtifactVerificationError(f"{label} version identity mismatch")
    if (
        _single_metadata_value(metadata, "Requires-Python", label)
        != component.requires_python
    ):
        raise ArtifactVerificationError(f"{label} Requires-Python mismatch")

    expected_entry_points = _expected_entry_points(component.entry_points)
    if entry_points != expected_entry_points:
        raise ArtifactVerificationError(
            f"{label} entry-point metadata disagrees with manifest"
        )


def verify_artifact_directory(artifact_dir: Path) -> None:
    """Verify every supported component wheel in one local directory."""
    manifest = load_release_compatibility_manifest()
    directory = artifact_dir.resolve()
    if not directory.is_dir():
        raise ArtifactVerificationError(
            f"artifact directory does not exist: {directory}"
        )

    for component in manifest.components:
        verify_component_wheel(component, directory / component.release.wheel)
