"""Suite #18 Slice 6A: exact official-wheel and installed Core-profile gates.

This is an explicit *qualification* tool, never a teacher intake command.
It only writes synthetic files inside a caller-selected temporary workspace.
It cannot grant live-producer admission or authorize automatic replay.
"""

from __future__ import annotations

import configparser
import hashlib
import re
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Final


class WheelQualificationError(ValueError):
    """An exact published wheel/profile prerequisite was not established."""


class _CasePreservingConfigParser(configparser.ConfigParser):
    """Match published entry-point names without silently folding case."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True, slots=True)
class OfficialWheel:
    distribution: str
    version: str
    filename: str
    sha256: str
    module: str | None = None
    entrypoint: str | None = None


# SHA-256 values are release asset digests as published by GitHub; they are
# independent of Suite #49's older release_compatibility_v1.json manifest.
OFFICIAL_WHEELS: Final[tuple[OfficialWheel, ...]] = (
    OfficialWheel(
        "pds-core", "0.6.6", "pds_core-0.6.6-py3-none-any.whl",
        "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301",
    ),
    OfficialWheel(
        "scoreform", "0.13.0", "scoreform-0.13.0-py3-none-any.whl",
        "4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7",
        "scoreform", "scoreform.pds_module:get_module_profile",
    ),
    OfficialWheel(
        "quillan", "0.10.6", "quillan-0.10.6-py3-none-any.whl",
        "7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb",
        "quillan", "quillan.pds_module:get_module_profile",
    ),
)

_ENTRY_POINT_GROUP: Final[str] = "paper_data_suite.modules"
_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_MAX_WHEEL_BYTES: Final[int] = 12 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED: Final[int] = 80 * 1024 * 1024


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _safe_zip_members(archive: zipfile.ZipFile) -> tuple[str, ...]:
    entries = archive.infolist()
    names = tuple(entry.filename for entry in entries)
    if not entries or len(set(names)) != len(names):
        raise WheelQualificationError("wheel has empty or duplicate member list")
    if sum(entry.file_size for entry in entries) > _MAX_TOTAL_UNCOMPRESSED:
        raise WheelQualificationError("wheel exceeds uncompressed size limit")
    for entry in entries:
        name = entry.filename
        pure = PurePosixPath(name)
        if (
            name.startswith("/")
            or "\\" in name
            or any(part in ("", ".", "..") for part in pure.parts)
            or entry.flag_bits & 1
        ):
            raise WheelQualificationError("wheel contains an unsafe member")
    return names


def verify_official_wheel(
    wheelhouse: Path,
    specification: OfficialWheel,
) -> Path:
    """Verify one exact release wheel; do not import or install its contents."""
    if not isinstance(wheelhouse, Path) or not wheelhouse.is_dir():
        raise WheelQualificationError("an existing wheelhouse directory is required")
    if not isinstance(specification, OfficialWheel):
        raise WheelQualificationError("an official wheel specification is required")
    if not _SHA.fullmatch(specification.sha256):
        raise WheelQualificationError("invalid expected SHA-256")
    path = wheelhouse / specification.filename
    if path.is_symlink() or not path.is_file():
        raise WheelQualificationError("required official wheel is missing")
    size = path.stat().st_size
    if size < 1 or size > _MAX_WHEEL_BYTES:
        raise WheelQualificationError("official wheel has invalid size")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != specification.sha256:
        raise WheelQualificationError("official wheel SHA-256 mismatch")
    try:
        with zipfile.ZipFile(path) as archive:
            names = _safe_zip_members(archive)
            root = (
                f"{specification.filename.split('-')[0]}-"
                f"{specification.version}.dist-info/"
            )
            metadata_name = root + "METADATA"
            wheel_name = root + "WHEEL"
            if metadata_name not in names or wheel_name not in names:
                raise WheelQualificationError("wheel metadata is missing")
            info = Parser().parsestr(
                archive.read(metadata_name).decode("utf-8")
            )
            if (
                _normalize_distribution(info.get("Name", ""))
                != _normalize_distribution(specification.distribution)
                or info.get("Version") != specification.version
            ):
                raise WheelQualificationError("wheel identity metadata mismatch")
            if specification.module is not None:
                entry_name = root + "entry_points.txt"
                if entry_name not in names:
                    raise WheelQualificationError("producer entry points missing")
                parser = _CasePreservingConfigParser(interpolation=None)
                parser.read_string(archive.read(entry_name).decode("utf-8"))
                if (
                    not parser.has_section(_ENTRY_POINT_GROUP)
                    or parser.get(
                        _ENTRY_POINT_GROUP, specification.module, fallback=""
                    ) != specification.entrypoint
                ):
                    raise WheelQualificationError("producer entry point mismatch")
            invalid_member = archive.testzip()
            if invalid_member is not None:
                raise WheelQualificationError("wheel CRC integrity mismatch")
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise WheelQualificationError("official wheel is unreadable") from error
    return path


def verify_official_wheelhouse(wheelhouse: Path) -> tuple[Path, ...]:
    """Refuse any mismatched Core, ScoreForm or Quillan release artifact."""
    return tuple(
        verify_official_wheel(wheelhouse, specification)
        for specification in OFFICIAL_WHEELS
    )


def _installed_entry_points() -> dict[str, tuple[str, str]]:
    providers: dict[str, tuple[str, str]] = {}
    for item in metadata.entry_points(group=_ENTRY_POINT_GROUP):
        if item.name in providers:
            raise WheelQualificationError("duplicate installed module entry point")
        owner = getattr(item, "dist", None)
        if owner is None:
            raise WheelQualificationError("module entry point has unknown owner")
        dist_name = owner.metadata.get("Name", "")
        providers[item.name] = (
            _normalize_distribution(dist_name), item.value
        )
    return providers


def qualify_installed_profiles() -> tuple[str, ...]:
    """Run actual Core and producer factories only in an isolated test venv.

    This authenticates metadata identities, NOT that the binaries were in fact
    installed from the separately verified wheelhouse. The isolated installer
    script must install those exact artifacts before invoking this function.
    """
    from pds_core.module_profiles import (
        CORE_ROUTING_CONTRACT_VERSION,
        build_module_registry,
    )

    for specification in OFFICIAL_WHEELS:
        try:
            actual = metadata.version(specification.distribution)
        except metadata.PackageNotFoundError as error:
            raise WheelQualificationError(
                "required installed distribution missing"
            ) from error
        if actual != specification.version:
            raise WheelQualificationError("installed version mismatch")
    expected = {
        item.module: (
            _normalize_distribution(item.distribution), item.entrypoint
        )
        for item in OFFICIAL_WHEELS
        if item.module is not None
    }
    if _installed_entry_points() != expected:
        raise WheelQualificationError(
            "installed entry-point owners or declarations differ"
        )
    try:
        registry = build_module_registry(discover_installed=True)
        if registry.module_ids() != tuple(sorted(expected)):
            raise WheelQualificationError("Core registry membership differs")
        for name in sorted(expected):
            profile = registry.require(name)
            if name != profile.module_id or not callable(profile.route_handler):
                raise WheelQualificationError("invalid installed producer handler")
            if (
                CORE_ROUTING_CONTRACT_VERSION
                not in profile.supported_core_routing_contract_versions
                or "PDS2" not in profile.supported_qr_schemas
                or "1" not in profile.supported_route_registration_schema_versions
                or "active" not in profile.dispatchable_route_statuses
            ):
                raise WheelQualificationError(
                    "producer profile incompatible with published Core routing"
                )
    except WheelQualificationError:
        raise
    except Exception as error:
        raise WheelQualificationError(
            "Core refused installed module-profile registry"
        ) from error
    return tuple(sorted(expected))


__all__ = [
    "OfficialWheel", "OFFICIAL_WHEELS", "WheelQualificationError",
    "verify_official_wheel", "verify_official_wheelhouse",
    "qualify_installed_profiles",
]
