"""Typed, side-effect-free access to exact release tooling qualification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Final, cast
from urllib.parse import urlparse

_RECORD_TYPE: Final = "paper_data_suite_release_tooling"
_CONTRACT_VERSION: Final = "1"
_RESOURCE_PARTS: Final = ("data", "release_tooling_v1.json")
_ALLOWED_TOOL_IDS: Final = frozenset({"pip"})
_VERSION_RE: Final = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z]+)*(?:[.-][0-9A-Za-z]+)*$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_WHEEL_RE: Final = re.compile(r"^[A-Za-z0-9_.+-]+\.whl$")


class ReleaseToolingError(ValueError):
    """Raised when bundled release-tooling data violates the v1 contract."""


@dataclass(frozen=True, slots=True)
class QualifiedReleaseTool:
    """One exact third-party tool qualified for the managed release environment."""

    tool_id: str
    distribution: str
    version: str
    requires_python: str
    requires_dist: tuple[str, ...]
    wheel: str
    sha256: str
    url: str


@dataclass(frozen=True, slots=True)
class ReleaseToolingContract:
    """Immutable release-tooling v1 contract."""

    record_type: str
    contract_version: str
    tools: tuple[QualifiedReleaseTool, ...]


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseToolingError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReleaseToolingError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseToolingError(f"{label} must be a non-empty string")
    return value


def _expect_keys(
    value: dict[str, object],
    *,
    required: frozenset[str],
    label: str,
) -> None:
    keys = frozenset(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required)
    if missing:
        raise ReleaseToolingError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ReleaseToolingError(f"{label} has unknown fields: {', '.join(unknown)}")


def _parse_tool(value: object) -> QualifiedReleaseTool:
    data = _expect_object(value, "release tool")
    _expect_keys(
        data,
        required=frozenset(
            {
                "tool_id",
                "distribution",
                "version",
                "requires_python",
                "requires_dist",
                "wheel",
                "sha256",
                "url",
            }
        ),
        label="release tool",
    )

    tool_id = _expect_string(data["tool_id"], "tool_id")
    distribution = _expect_string(data["distribution"], "distribution")
    version = _expect_string(data["version"], "version")
    requires_python = _expect_string(data["requires_python"], "requires_python")
    wheel = _expect_string(data["wheel"], "wheel")
    sha256 = _expect_string(data["sha256"], "sha256")
    url = _expect_string(data["url"], "url")

    if tool_id not in _ALLOWED_TOOL_IDS:
        raise ReleaseToolingError(f"unsupported release tool: {tool_id!r}")
    if tool_id == "pip" and distribution != "pip":
        raise ReleaseToolingError("pip tool distribution must be 'pip'")
    if _VERSION_RE.fullmatch(version) is None:
        raise ReleaseToolingError("release tool version is invalid")
    if _WHEEL_RE.fullmatch(wheel) is None:
        raise ReleaseToolingError("release tool wheel filename is invalid")
    if not wheel.startswith(f"{distribution.replace('-', '_')}-{version}-"):
        raise ReleaseToolingError(
            "release tool wheel does not match distribution/version identity"
        )
    if _SHA256_RE.fullmatch(sha256) is None:
        raise ReleaseToolingError(
            "release tool sha256 must be 64 lowercase hexadecimal characters"
        )

    raw_requires_dist = data["requires_dist"]
    if not isinstance(raw_requires_dist, list):
        raise ReleaseToolingError("requires_dist must be an array")
    requires_dist = tuple(
        _expect_string(item, f"requires_dist[{index}]")
        for index, item in enumerate(raw_requires_dist)
    )

    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "files.pythonhosted.org"
        or not parsed.path.endswith("/" + wheel)
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseToolingError(
            "release tool URL must be an exact files.pythonhosted.org HTTPS wheel URL"
        )

    return QualifiedReleaseTool(
        tool_id=tool_id,
        distribution=distribution,
        version=version,
        requires_python=requires_python,
        requires_dist=requires_dist,
        wheel=wheel,
        sha256=sha256,
        url=url,
    )


def parse_release_tooling_contract(text: str) -> ReleaseToolingContract:
    """Parse release-tooling JSON and enforce the v1 contract."""
    try:
        raw = json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except ReleaseToolingError:
        raise
    except json.JSONDecodeError as error:
        raise ReleaseToolingError(
            f"invalid release-tooling JSON: {error.msg}"
        ) from error

    data = _expect_object(raw, "release tooling")
    _expect_keys(
        data,
        required=frozenset({"record_type", "contract_version", "tools"}),
        label="release tooling",
    )

    record_type = _expect_string(data["record_type"], "record_type")
    contract_version = _expect_string(data["contract_version"], "contract_version")
    if record_type != _RECORD_TYPE:
        raise ReleaseToolingError(f"record_type must be {_RECORD_TYPE!r}")
    if contract_version != _CONTRACT_VERSION:
        raise ReleaseToolingError(
            f"unsupported release-tooling contract version: {contract_version!r}"
        )

    raw_tools = data["tools"]
    if not isinstance(raw_tools, list) or not raw_tools:
        raise ReleaseToolingError("tools must be a non-empty array")
    tools = tuple(_parse_tool(item) for item in raw_tools)
    tool_ids = tuple(item.tool_id for item in tools)
    if len(tool_ids) != len(set(tool_ids)):
        raise ReleaseToolingError("duplicate release tool_id")
    if tool_ids != tuple(sorted(tool_ids)):
        raise ReleaseToolingError("release tools must be sorted by tool_id")

    return ReleaseToolingContract(record_type, contract_version, tools)


def release_tooling_contract_bytes() -> bytes:
    """Return exact bundled release-tooling resource bytes."""
    resource = resources.files("paper_data_suite").joinpath(*_RESOURCE_PARTS)
    return resource.read_bytes()


def release_tooling_contract_sha256() -> str:
    """Return SHA-256 for exact bundled release-tooling bytes."""
    return hashlib.sha256(release_tooling_contract_bytes()).hexdigest()


def load_release_tooling_contract() -> ReleaseToolingContract:
    """Load bundled release-tooling v1 without probing the environment."""
    raw = release_tooling_contract_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReleaseToolingError(
            "release-tooling contract must be valid UTF-8"
        ) from error
    return parse_release_tooling_contract(text)


__all__ = (
    "QualifiedReleaseTool",
    "ReleaseToolingContract",
    "ReleaseToolingError",
    "load_release_tooling_contract",
    "parse_release_tooling_contract",
    "release_tooling_contract_bytes",
    "release_tooling_contract_sha256",
)
