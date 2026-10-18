"""Issue #49: inspect a closed, exact-hash wheelhouse without installing it.

IMPORTANT: WheelPin inputs are EXPECTATIONS, not authenticated authorizations.
A caller must independently authenticate a full, immutable lock before using
this inspection as one input to a managed installation. No installation, import,
network request, signing, workspace access, receipt, or launch permit occurs.
"""

from __future__ import annotations

import hashlib
import re
import stat
import sys
import zipfile
from collections import deque
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import BinaryIO, Final

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, parse_tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

_MAX_WHEELS: Final = 128
_MAX_WHEEL_SIZE: Final = 512 * 1024 * 1024
_MAX_MEMBERS: Final = 20000
_MAX_UNCOMPRESSED: Final = 1024 * 1024 * 1024
_MAX_METADATA: Final = 256 * 1024
_MAX_WHEEL_INFO: Final = 32 * 1024
_WHEEL_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,190}\.whl\Z")
_SHA256: Final = re.compile(r"[0-9a-f]{64}\Z")
_DIST: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")


class WheelhouseError(ValueError):
    """A local wheelhouse fails a closed, hash-pinned dependency inspection."""


@dataclass(frozen=True, slots=True)
class WheelPin:
    """Claimed expected wheel filename and digest; never its own trust root."""

    filename: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not _WHEEL_NAME.fullmatch(
            self.filename
        ):
            raise WheelhouseError("invalid wheel pin filename")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise WheelhouseError("invalid wheel pin SHA-256")
        try:
            parse_wheel_filename(self.filename)
        except ValueError as error:
            raise WheelhouseError("invalid pinned wheel filename") from error


@dataclass(frozen=True, slots=True)
class InspectedWheel:
    """One digest-matched wheel observation, not a trusted installed artifact."""

    distribution: str
    version: str
    filename: str
    sha256: str
    requires_python: str | None
    requires_dist: tuple[str, ...]
    provides_extras: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WheelhouseInspection:
    """Closed on the CURRENT interpreter/platform, but not trust-authorizing."""

    roots: tuple[str, ...]
    wheels: tuple[InspectedWheel, ...]
    dependency_edges: tuple[tuple[str, str], ...]


def _reparse(path: Path) -> bool:
    """Reject normal symlinks and detectable Windows reparse points."""
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _sha256(stream: BinaryIO) -> str:
    value = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        value.update(block)
    return value.hexdigest()


def _member(archive: zipfile.ZipFile, name: str, maximum: int) -> bytes:
    try:
        info = archive.getinfo(name)
        if info.file_size > maximum:
            raise WheelhouseError("wheel metadata exceeds size limit")
        with archive.open(info) as reader:
            result = reader.read(maximum + 1)
    except (KeyError, RuntimeError, OSError, zipfile.BadZipFile) as error:
        raise WheelhouseError("wheel metadata is unreadable") from error
    if len(result) > maximum:
        raise WheelhouseError("wheel metadata exceeds size limit")
    return result


def _members(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if not 1 <= len(infos) <= _MAX_MEMBERS:
        raise WheelhouseError("wheel member count exceeds bounds")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        # zipfile normalizes names on Windows; validate the original ZIP name.
        original_name = info.orig_filename
        segments = name.split("/")
        if (
            not name
            or original_name != name
            or "\\" in original_name
            or "\x00" in original_name
            or name.startswith("/")
            or "\\" in name
            or ":" in name
            or any(part in {"", ".", ".."} for part in segments[:-1])
            or segments[-1] in {".", ".."}
            or name in names
            or (info.external_attr >> 16) & 0o170000 == 0o120000
        ):
            raise WheelhouseError("unsafe or duplicate wheel archive entry")
        names.add(name)
        total += info.file_size
        if total > _MAX_UNCOMPRESSED:
            raise WheelhouseError("wheel uncompressed size exceeds bounds")


def _single(message: Message, field: str, *, required: bool) -> str | None:
    fields = message.get_all(field, [])
    if len(fields) > 1 or (required and len(fields) != 1):
        raise WheelhouseError(f"wheel metadata has invalid {field}")
    if not fields:
        return None
    value = str(fields[0]).strip()
    if not value:
        raise WheelhouseError(f"wheel metadata has blank {field}")
    return value


def _metadata(
    archive: zipfile.ZipFile,
    distribution: str,
    version: str,
    wheel_tags: frozenset[Tag],
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    names = set(archive.namelist())
    dirs = {name.split("/")[0] for name in names if ".dist-info/" in name}
    if len(dirs) != 1:
        raise WheelhouseError("wheel must contain exactly one dist-info directory")
    folder = next(iter(dirs))
    expected = f"{distribution.replace('-', '_')}-{version}.dist-info"
    if folder.lower() != expected.lower():
        raise WheelhouseError("wheel dist-info identity does not match filename")
    if (
        not {
            f"{folder}/METADATA",
            f"{folder}/WHEEL",
            f"{folder}/RECORD",
        }
        <= names
    ):
        raise WheelhouseError("wheel missing required dist-info members")
    metadata = BytesParser(policy=policy.default).parsebytes(
        _member(archive, f"{folder}/METADATA", _MAX_METADATA)
    )
    wheel_info = BytesParser(policy=policy.default).parsebytes(
        _member(archive, f"{folder}/WHEEL", _MAX_WHEEL_INFO)
    )
    name = _single(metadata, "Name", required=True)
    observed_version = _single(metadata, "Version", required=True)
    if name is None or not _DIST.fullmatch(name):
        raise WheelhouseError("invalid wheel distribution metadata")
    if canonicalize_name(name) != distribution:
        raise WheelhouseError("wheel distribution mismatch")
    try:
        if observed_version is None or Version(observed_version) != Version(version):
            raise WheelhouseError("wheel version mismatch")
    except InvalidVersion as error:
        raise WheelhouseError("invalid wheel version metadata") from error
    if _single(wheel_info, "Wheel-Version", required=True) is None:
        raise WheelhouseError("wheel version header missing")
    info_tags = wheel_info.get_all("Tag", [])
    if not info_tags:
        raise WheelhouseError("wheel has no WHEEL tags")
    declared_tags: set[Tag] = set()
    try:
        for tag in info_tags:
            declared_tags.update(parse_tag(str(tag)))
    except ValueError as error:
        raise WheelhouseError("invalid wheel WHEEL tag") from error
    if not declared_tags <= wheel_tags:
        raise WheelhouseError("WHEEL tags disagree with wheel filename")
    python_spec = _single(metadata, "Requires-Python", required=False)
    if python_spec is not None:
        try:
            supported = SpecifierSet(python_spec)
        except InvalidSpecifier as error:
            raise WheelhouseError("invalid Requires-Python") from error
        current_python = (
            f"{sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}"
        )
        if not supported.contains(current_python):
            raise WheelhouseError("wheel does not support current Python")
    raw_requirements = tuple(
        str(v).strip() for v in metadata.get_all("Requires-Dist", [])
    )
    if len(raw_requirements) > 128 or len(set(raw_requirements)) != len(
        raw_requirements
    ):
        raise WheelhouseError("invalid wheel dependency declarations")
    for raw in raw_requirements:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as error:
            raise WheelhouseError("invalid Requires-Dist") from error
        if requirement.url is not None:
            raise WheelhouseError("direct-URL dependencies are not wheelhouse-locked")
    extras = tuple(str(v).strip() for v in metadata.get_all("Provides-Extra", []))
    if len(extras) > 64 or any(not _DIST.fullmatch(extra) for extra in extras):
        raise WheelhouseError("invalid Provides-Extra")
    normalized_extras = tuple(canonicalize_name(extra) for extra in extras)
    if len(set(normalized_extras)) != len(normalized_extras):
        raise WheelhouseError("duplicate Provides-Extra")
    return python_spec, raw_requirements, normalized_extras


def _inspect(path: Path, pin: WheelPin) -> InspectedWheel:
    name, version, _, wheel_tags = parse_wheel_filename(pin.filename)
    if not (frozenset(wheel_tags) & frozenset(sys_tags())):
        raise WheelhouseError("wheel is incompatible with current platform/Python")
    try:
        if _reparse(path) or not path.is_file():
            raise WheelhouseError("wheel must be a regular file, not a link")
        if not 1 <= path.stat().st_size <= _MAX_WHEEL_SIZE:
            raise WheelhouseError("wheel size exceeds bounds")
        with path.open("rb") as stream:
            if _sha256(stream) != pin.sha256:
                raise WheelhouseError("wheel SHA-256 differs from expected pin")
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                _members(archive)
                python_spec, dependencies, extras = _metadata(
                    archive, str(name), str(version), frozenset(wheel_tags)
                )
            stream.seek(0)
            if _sha256(stream) != pin.sha256:
                raise WheelhouseError("wheel changed during inspection")
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise WheelhouseError("wheel could not be inspected") from error
    return InspectedWheel(
        str(name),
        str(version),
        pin.filename,
        pin.sha256,
        python_spec,
        dependencies,
        extras,
    )


def _closure(
    wheels: dict[str, InspectedWheel], roots: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    queue = deque((root, "") for root in roots)
    seen: set[tuple[str, str]] = set()
    edges: set[tuple[str, str]] = set()
    environment: dict[str, str] = {
        key: str(value) for key, value in default_environment().items()
    }
    while queue:
        name, extra = queue.popleft()
        if (name, extra) in seen:
            continue
        wheel = wheels.get(name)
        if wheel is None:
            raise WheelhouseError(f"unlocked dependency: {name}")
        if extra and extra not in wheel.provides_extras:
            raise WheelhouseError("dependency requests undeclared extra")
        seen.add((name, extra))
        for raw in wheel.requires_dist:
            requirement = Requirement(raw)
            environment["extra"] = extra
            if requirement.marker is not None and not requirement.marker.evaluate(
                environment=environment
            ):
                continue
            dependency = canonicalize_name(requirement.name)
            target = wheels.get(dependency)
            if target is None:
                raise WheelhouseError(f"unlocked dependency: {dependency}")
            if not requirement.specifier.contains(target.version):
                raise WheelhouseError("locked dependency version violates requirement")
            if requirement.url is not None:
                raise WheelhouseError("unlocked direct-URL dependency")
            edges.add((name, dependency))
            queue.append((dependency, ""))
            for selected_extra in requirement.extras:
                queue.append((dependency, canonicalize_name(selected_extra)))
    if {name for name, _ in seen} != set(wheels):
        raise WheelhouseError("wheelhouse has unrelated or unreachable wheels")
    return tuple(sorted(edges))


def inspect_closed_wheelhouse(
    directory: Path,
    *,
    pins: tuple[WheelPin, ...],
    roots: tuple[str, ...],
) -> WheelhouseInspection:
    """Inspect every pinned wheel and its complete active transitive closure.

    Inputs are caller-supplied expectations, NOT signed provenance or a permit
    to install/launch. Never trust a pin merely because it matches wheel bytes.
    """
    if not isinstance(directory, Path) or not directory.is_dir():
        raise WheelhouseError("wheelhouse directory missing")
    if _reparse(directory):
        raise WheelhouseError("wheelhouse directory is a reparse point")
    if (
        type(pins) is not tuple
        or not 1 <= len(pins) <= _MAX_WHEELS
        or any(not isinstance(pin, WheelPin) for pin in pins)
    ):
        raise WheelhouseError("invalid closed wheel pin set")
    if type(roots) is not tuple or not 1 <= len(roots) <= _MAX_WHEELS:
        raise WheelhouseError("invalid wheelhouse roots")
    if any(not isinstance(name, str) or not _DIST.fullmatch(name) for name in roots):
        raise WheelhouseError("invalid root distribution")
    normalized_roots = tuple(canonicalize_name(root) for root in roots)
    if len(set(normalized_roots)) != len(normalized_roots):
        raise WheelhouseError("duplicate root distribution")
    filenames = [pin.filename for pin in pins]
    if len(set(name.lower() for name in filenames)) != len(filenames):
        raise WheelhouseError("duplicate pinned wheel filenames")
    expected = set(filenames)
    try:
        actual = {item.name for item in directory.iterdir()}
    except OSError as error:
        raise WheelhouseError("wheelhouse directory unreadable") from error
    if actual != expected:
        raise WheelhouseError("wheelhouse has unpinned or missing files")
    wheels: dict[str, InspectedWheel] = {}
    for pin in pins:
        observed = _inspect(directory / pin.filename, pin)
        if observed.distribution in wheels:
            raise WheelhouseError("duplicate normalized distribution in wheelhouse")
        wheels[observed.distribution] = observed
    for root in normalized_roots:
        if root not in wheels:
            raise WheelhouseError("requested root wheel is absent")
    edges = _closure(wheels, normalized_roots)
    return WheelhouseInspection(
        normalized_roots,
        tuple(sorted(wheels.values(), key=lambda item: item.distribution)),
        edges,
    )


__all__ = (
    "InspectedWheel",
    "WheelPin",
    "WheelhouseError",
    "WheelhouseInspection",
    "inspect_closed_wheelhouse",
)
