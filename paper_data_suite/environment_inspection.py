"""Read-only inspection of dedicated Windows Paper Data Suite environments."""

from __future__ import annotations

import json
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Final, cast

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    normalize_sha256,
)
from paper_data_suite.bootstrap import (
    BootstrapPlanningError,
    EnvironmentMarkerIdentity,
    EnvironmentSnapshot,
    InstalledDistribution,
    normalize_distribution_name,
)

ENVIRONMENT_MARKER_FILENAME: Final = ".pds-suite-environment.json"
_MARKER_RECORD_TYPE: Final = "paper_data_suite_environment"
_MARKER_CONTRACT_VERSION: Final = "1"


class EnvironmentInspectionError(RuntimeError):
    """Raised when an environment path cannot be inspected safely as data."""


def _expect_marker_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EnvironmentInspectionError("environment marker must be a JSON object")
    return cast(dict[str, object], value)


def parse_environment_marker(text: str) -> EnvironmentMarkerIdentity:
    """Parse the bounded v1 suite environment marker without side effects."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise EnvironmentInspectionError(
            f"environment marker is invalid JSON: {error.msg}"
        ) from error

    data = _expect_marker_object(raw)
    expected_keys = {
        "record_type",
        "contract_version",
        "suite_version",
        "compatibility_manifest_sha256",
    }
    actual_keys = set(data)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise EnvironmentInspectionError(
            "environment marker fields are invalid (" + "; ".join(details) + ")"
        )

    if data["record_type"] != _MARKER_RECORD_TYPE:
        raise EnvironmentInspectionError(
            f"environment marker record_type must be {_MARKER_RECORD_TYPE!r}"
        )
    if data["contract_version"] != _MARKER_CONTRACT_VERSION:
        raise EnvironmentInspectionError(
            "unsupported environment marker contract_version"
        )

    suite_version = data["suite_version"]
    digest = data["compatibility_manifest_sha256"]
    if not isinstance(suite_version, str) or not suite_version:
        raise EnvironmentInspectionError(
            "environment marker suite_version must be a non-empty string"
        )
    if not isinstance(digest, str):
        raise EnvironmentInspectionError(
            "environment marker compatibility_manifest_sha256 must be a string"
        )
    try:
        normalized_digest = normalize_sha256(digest)
    except ArtifactVerificationError as error:
        raise EnvironmentInspectionError(str(error)) from error

    return EnvironmentMarkerIdentity(
        suite_version=suite_version,
        compatibility_manifest_sha256=normalized_digest,
    )


def _read_pyvenv_version(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    values: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip().lower()
        if normalized_key in values:
            return None
        values[normalized_key] = value.strip()
    version = values.get("version")
    return version if version else None


def _distribution_is_editable(distribution: metadata.Distribution) -> bool:
    direct_url = distribution.read_text("direct_url.json")
    if direct_url is None:
        return False
    try:
        value = json.loads(direct_url.lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise EnvironmentInspectionError(
            "installed distribution direct_url.json is invalid JSON"
        ) from error
    if not isinstance(value, dict):
        raise EnvironmentInspectionError(
            "installed distribution direct_url.json must be an object"
        )
    dir_info = value.get("dir_info")
    if dir_info is None:
        return False
    if not isinstance(dir_info, dict):
        raise EnvironmentInspectionError(
            "installed distribution direct_url.json dir_info must be an object"
        )
    editable = dir_info.get("editable", False)
    if not isinstance(editable, bool):
        raise EnvironmentInspectionError(
            "installed distribution editable flag must be boolean"
        )
    return editable


def _installed_distributions(
    site_packages: Path,
    tracked_distributions: frozenset[str],
) -> tuple[InstalledDistribution, ...]:
    observed: list[InstalledDistribution] = []
    try:
        distributions = metadata.distributions(path=[str(site_packages)])
        for distribution in distributions:
            name = distribution.metadata["Name"]
            version = distribution.version
            if not name or not version:
                continue
            normalized_name = normalize_distribution_name(str(name))
            observed.append(
                InstalledDistribution(
                    distribution=str(name),
                    version=str(version),
                    editable=(
                        _distribution_is_editable(distribution)
                        if normalized_name in tracked_distributions
                        else False
                    ),
                )
            )
    except (OSError, metadata.PackageNotFoundError) as error:
        raise EnvironmentInspectionError(
            f"installed distribution metadata could not be read: {site_packages}"
        ) from error

    try:
        return tuple(
            sorted(
                observed,
                key=lambda item: normalize_distribution_name(item.distribution),
            )
        )
    except BootstrapPlanningError as error:
        raise EnvironmentInspectionError(str(error)) from error


def environment_marker_text(identity: EnvironmentMarkerIdentity) -> str:
    """Serialize the bounded environment marker deterministically."""
    try:
        digest = normalize_sha256(identity.compatibility_manifest_sha256)
    except ArtifactVerificationError as error:
        raise EnvironmentInspectionError(str(error)) from error
    if not identity.suite_version:
        raise EnvironmentInspectionError(
            "environment marker suite_version must be a non-empty string"
        )
    payload = {
        "compatibility_manifest_sha256": digest,
        "contract_version": _MARKER_CONTRACT_VERSION,
        "record_type": _MARKER_RECORD_TYPE,
        "suite_version": identity.suite_version,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_environment_marker(
    environment_root: Path,
    identity: EnvironmentMarkerIdentity,
) -> Path:
    """Atomically finalize one validated Windows PDS environment marker."""
    root = environment_root.expanduser().resolve()
    pyvenv_config = root / "pyvenv.cfg"
    python_executable = root / "Scripts" / "python.exe"
    site_packages = root / "Lib" / "site-packages"
    if not (
        root.is_dir()
        and pyvenv_config.is_file()
        and python_executable.is_file()
        and site_packages.is_dir()
    ):
        raise EnvironmentInspectionError(
            "cannot write marker outside an existing Windows virtual environment"
        )

    target = root / ENVIRONMENT_MARKER_FILENAME
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=root,
            prefix=f".{ENVIRONMENT_MARKER_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(environment_marker_text(identity))
            temporary_path = Path(temporary.name)
        if temporary_path is None:
            raise EnvironmentInspectionError(
                f"could not create environment marker: {target}"
            )
        temporary_path.replace(target)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise EnvironmentInspectionError(
            f"could not write environment marker: {target}"
        ) from error
    return target

def inspect_windows_environment(
    path: Path,
    *,
    seed_python_version: str,
    tracked_distributions: frozenset[str] = frozenset(),
) -> EnvironmentSnapshot:
    """Inspect a Windows venv path as filesystem metadata without executing it."""
    target = path.expanduser().resolve()
    if not target.exists():
        return EnvironmentSnapshot(
            path=str(target),
            exists=False,
            is_virtual_environment=False,
            python_version=seed_python_version,
            marker=None,
        )

    marker: EnvironmentMarkerIdentity | None = None
    marker_error: str | None = None
    if target.is_dir():
        marker_path = target / ENVIRONMENT_MARKER_FILENAME
        if marker_path.is_file():
            try:
                marker = parse_environment_marker(
                    marker_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, EnvironmentInspectionError) as error:
                marker_error = str(error)

    pyvenv_config = target / "pyvenv.cfg"
    python_executable = target / "Scripts" / "python.exe"
    site_packages = target / "Lib" / "site-packages"
    configured_version = (
        _read_pyvenv_version(pyvenv_config) if pyvenv_config.is_file() else None
    )
    is_venv = (
        target.is_dir()
        and pyvenv_config.is_file()
        and python_executable.is_file()
        and site_packages.is_dir()
        and configured_version is not None
    )
    installed = (
        _installed_distributions(site_packages, tracked_distributions)
        if is_venv
        else ()
    )

    return EnvironmentSnapshot(
        path=str(target),
        exists=True,
        is_virtual_environment=is_venv,
        python_version=configured_version or seed_python_version,
        marker=marker,
        marker_error=marker_error,
        installed_distributions=installed,
    )
