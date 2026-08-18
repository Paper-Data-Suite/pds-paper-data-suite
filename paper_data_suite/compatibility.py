"""Typed, side-effect-free access to the bundled suite compatibility manifest."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Final, cast

from paper_data_suite._version import __version__

_RECORD_TYPE: Final = "paper_data_suite_release_compatibility_manifest"
_CONTRACT_VERSION: Final = "1"
_SUITE_DISTRIBUTION: Final = "paper-data-suite"
_RESOURCE_PARTS: Final = ("data", "release_compatibility_v1.json")

_ALLOWED_RELEASE_STATUS: Final = frozenset({"development", "release"})
_ALLOWED_COMPATIBILITY_STATUS: Final = frozenset({"supported"})
_ALLOWED_COMPONENT_IDS: Final = frozenset(
    {"core", "scoreform", "quillan", "concord", "meridian", "vitrine", "portia"}
)
_ALLOWED_CAPABILITIES: Final = frozenset(
    {
        "shared_core",
        "launchable_application",
        "routing_module",
        "publication_producer",
        "publication_consumer",
    }
)
_ALLOWED_ENTRY_POINT_GROUPS: Final = (
    "console_scripts",
    "paper_data_suite.modules",
    "paper_data_suite.publication_producers",
)
_ALLOWED_PREREQUISITE_KINDS: Final = frozenset({"command"})
_ALLOWED_PLATFORMS: Final = frozenset({"windows", "linux", "macos"})
_COMPONENT_ID_RE: Final = re.compile(r"^[a-z][a-z0-9_]*$")
_PREREQUISITE_ID_RE: Final = re.compile(r"^[a-z][a-z0-9_-]*$")
_DISTRIBUTION_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_IMPORT_NAME_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_REPOSITORY_RE: Final = re.compile(
    r"^Paper-Data-Suite/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
_VERSION_RE: Final = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z]+)*(?:[.-][0-9A-Za-z]+)*$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_WHEEL_RE: Final = re.compile(r"^[A-Za-z0-9_.+-]+\.whl$")
_ENTRY_POINT_NAME_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENTRY_POINT_TARGET_RE: Final = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$"
)
_MINOR_RE: Final = re.compile(r"^([0-9]+)\.([0-9]+)$")
_SPECIFIER_TOKEN_RE: Final = re.compile(
    r"^(>=|<=|==|!=|>|<)([0-9]+)\.([0-9]+)$"
)


class CompatibilityManifestError(ValueError):
    """Raised when compatibility data violates the v1 contract."""


@dataclass(frozen=True, slots=True)
class SuiteCompatibility:
    """Identity of the suite release that owns the manifest."""

    distribution: str
    version: str
    release_status: str


@dataclass(frozen=True, slots=True)
class PythonCompatibility:
    """Suite-qualified Python interpreter range."""

    specifier: str
    tested_minors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    """Exact published wheel identity authenticated by the suite."""

    tag: str
    wheel: str
    sha256: str


@dataclass(frozen=True, slots=True)
class EntryPointExpectation:
    """One exact public entry point expected in a released wheel."""

    group: str
    name: str
    target: str


@dataclass(frozen=True, slots=True)
class ExternalPrerequisite:
    """One non-Python prerequisite for later environment diagnostics."""

    prerequisite_id: str
    kind: str
    required: bool
    commands: tuple[str, ...]
    platforms: tuple[str, ...]
    purpose: str


@dataclass(frozen=True, slots=True)
class ComponentCompatibility:
    """Exact suite qualification row for one PDS-owned component."""

    component_id: str
    display_name: str
    repository: str
    distribution: str
    import_name: str
    required: bool
    compatibility_status: str
    version: str
    requires_python: str
    release: ReleaseArtifact
    capabilities: tuple[str, ...]
    entry_points: tuple[EntryPointExpectation, ...]
    external_prerequisites: tuple[ExternalPrerequisite, ...]


@dataclass(frozen=True, slots=True)
class ReleaseCompatibilityManifest:
    """Immutable typed representation of release compatibility v1."""

    record_type: str
    contract_version: str
    suite: SuiteCompatibility
    python: PythonCompatibility
    components: tuple[ComponentCompatibility, ...]


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CompatibilityManifestError(
                f"duplicate JSON object key: {key!r}"
            )
        result[key] = value
    return result


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CompatibilityManifestError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _expect_keys(
    value: Mapping[str, object],
    *,
    required: frozenset[str],
    label: str,
) -> None:
    keys = frozenset(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required)
    if missing:
        raise CompatibilityManifestError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise CompatibilityManifestError(
            f"{label} has unknown fields: {', '.join(unknown)}"
        )


def _expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompatibilityManifestError(
            f"{label} must be a non-empty string"
        )
    return value


def _expect_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CompatibilityManifestError(f"{label} must be a boolean")
    return value


def _expect_array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CompatibilityManifestError(f"{label} must be an array")
    return cast(list[object], value)


def _parse_minor(value: str, label: str) -> tuple[int, int]:
    match = _MINOR_RE.fullmatch(value)
    if match is None:
        raise CompatibilityManifestError(
            f"{label} must use MAJOR.MINOR form"
        )
    return int(match.group(1)), int(match.group(2))


def _parse_specifier(
    value: str, label: str
) -> tuple[tuple[str, tuple[int, int]], ...]:
    tokens: list[tuple[str, tuple[int, int]]] = []
    for raw_token in value.split(","):
        token = raw_token.strip()
        match = _SPECIFIER_TOKEN_RE.fullmatch(token)
        if match is None:
            raise CompatibilityManifestError(
                f"{label} has unsupported Python specifier token: {token!r}"
            )
        tokens.append(
            (
                match.group(1),
                (int(match.group(2)), int(match.group(3))),
            )
        )
    if not tokens:
        raise CompatibilityManifestError(f"{label} cannot be empty")
    return tuple(tokens)


def _version_satisfies(
    version: tuple[int, int],
    specifiers: Sequence[tuple[str, tuple[int, int]]],
) -> bool:
    for operator, expected in specifiers:
        if operator == ">=" and not version >= expected:
            return False
        if operator == ">" and not version > expected:
            return False
        if operator == "<=" and not version <= expected:
            return False
        if operator == "<" and not version < expected:
            return False
        if operator == "==" and not version == expected:
            return False
        if operator == "!=" and not version != expected:
            return False
    return True


def _parse_suite(value: object) -> SuiteCompatibility:
    data = _expect_object(value, "suite")
    required = frozenset({"distribution", "version", "release_status"})
    _expect_keys(data, required=required, label="suite")

    distribution = _expect_string(data["distribution"], "suite.distribution")
    version = _expect_string(data["version"], "suite.version")
    release_status = _expect_string(
        data["release_status"], "suite.release_status"
    )

    if distribution != _SUITE_DISTRIBUTION:
        raise CompatibilityManifestError(
            f"suite.distribution must be {_SUITE_DISTRIBUTION!r}"
        )
    if version != __version__:
        raise CompatibilityManifestError(
            "manifest suite.version disagrees with package __version__"
        )
    if release_status not in _ALLOWED_RELEASE_STATUS:
        raise CompatibilityManifestError(
            f"unsupported suite.release_status: {release_status!r}"
        )
    if ".dev" in version and release_status != "development":
        raise CompatibilityManifestError(
            "development suite version must use release_status='development'"
        )

    return SuiteCompatibility(distribution, version, release_status)


def _parse_python(value: object) -> PythonCompatibility:
    data = _expect_object(value, "python")
    required = frozenset({"specifier", "tested_minors"})
    _expect_keys(data, required=required, label="python")

    specifier = _expect_string(data["specifier"], "python.specifier")
    parsed_specifier = _parse_specifier(specifier, "python.specifier")
    raw_minors = _expect_array(data["tested_minors"], "python.tested_minors")
    tested = tuple(
        _expect_string(item, f"python.tested_minors[{index}]")
        for index, item in enumerate(raw_minors)
    )
    if not tested:
        raise CompatibilityManifestError(
            "python.tested_minors cannot be empty"
        )
    if len(tested) != len(set(tested)):
        raise CompatibilityManifestError(
            "python.tested_minors contains duplicates"
        )

    parsed_minors = tuple(
        _parse_minor(item, f"python.tested_minors[{index}]")
        for index, item in enumerate(tested)
    )
    if parsed_minors != tuple(sorted(parsed_minors)):
        raise CompatibilityManifestError(
            "python.tested_minors must be in ascending order"
        )
    outside = [
        value
        for value, parsed in zip(tested, parsed_minors, strict=True)
        if not _version_satisfies(parsed, parsed_specifier)
    ]
    if outside:
        raise CompatibilityManifestError(
            "tested Python minors outside suite specifier: "
            + ", ".join(outside)
        )

    return PythonCompatibility(specifier, tested)


def _parse_release(
    value: object,
    *,
    distribution: str,
    version: str,
) -> ReleaseArtifact:
    data = _expect_object(value, f"component {distribution!r} release")
    required = frozenset({"tag", "wheel", "sha256"})
    _expect_keys(
        data,
        required=required,
        label=f"component {distribution!r} release",
    )

    tag = _expect_string(data["tag"], "release.tag")
    wheel = _expect_string(data["wheel"], "release.wheel")
    sha256 = _expect_string(data["sha256"], "release.sha256")

    if tag != f"v{version}":
        raise CompatibilityManifestError(
            f"release.tag {tag!r} must equal version-qualified tag v{version}"
        )
    if _WHEEL_RE.fullmatch(wheel) is None:
        raise CompatibilityManifestError("release.wheel is not a safe wheel filename")
    normalized_distribution = distribution.replace("-", "_").replace(".", "_")
    if not wheel.startswith(f"{normalized_distribution}-{version}-"):
        raise CompatibilityManifestError(
            "release.wheel does not match distribution/version identity"
        )
    if _SHA256_RE.fullmatch(sha256) is None:
        raise CompatibilityManifestError(
            "release.sha256 must be 64 lowercase hexadecimal characters"
        )

    return ReleaseArtifact(tag, wheel, sha256)


def _parse_entry_points(
    value: object,
    component_id: str,
) -> tuple[EntryPointExpectation, ...]:
    data = _expect_object(value, f"component {component_id!r} entry_points")
    _expect_keys(
        data,
        required=frozenset(_ALLOWED_ENTRY_POINT_GROUPS),
        label=f"component {component_id!r} entry_points",
    )

    expectations: list[EntryPointExpectation] = []
    for group in _ALLOWED_ENTRY_POINT_GROUPS:
        group_data = _expect_object(
            data[group], f"component {component_id!r} entry_points.{group}"
        )
        for name in sorted(group_data):
            target = group_data[name]
            if _ENTRY_POINT_NAME_RE.fullmatch(name) is None:
                raise CompatibilityManifestError(
                    f"invalid entry-point name {name!r} in group {group!r}"
                )
            parsed_target = _expect_string(
                target,
                f"component {component_id!r} entry point {group}:{name}",
            )
            if _ENTRY_POINT_TARGET_RE.fullmatch(parsed_target) is None:
                raise CompatibilityManifestError(
                    f"invalid entry-point target: {parsed_target!r}"
                )
            expectations.append(
                EntryPointExpectation(group, name, parsed_target)
            )

    return tuple(expectations)


def _parse_prerequisites(
    value: object, component_id: str
) -> tuple[ExternalPrerequisite, ...]:
    raw_items = _expect_array(
        value, f"component {component_id!r} external_prerequisites"
    )
    result: list[ExternalPrerequisite] = []
    seen_ids: set[str] = set()

    required_fields = frozenset(
        {"id", "kind", "required", "commands", "platforms", "purpose"}
    )
    for index, item in enumerate(raw_items):
        data = _expect_object(
            item,
            f"component {component_id!r} external_prerequisites[{index}]",
        )
        _expect_keys(
            data,
            required=required_fields,
            label=(
                f"component {component_id!r} "
                f"external_prerequisites[{index}]"
            ),
        )

        prerequisite_id = _expect_string(data["id"], "prerequisite.id")
        if not _PREREQUISITE_ID_RE.fullmatch(prerequisite_id):
            raise CompatibilityManifestError(
                f"invalid prerequisite id: {prerequisite_id!r}"
            )
        if prerequisite_id in seen_ids:
            raise CompatibilityManifestError(
                f"duplicate prerequisite id in {component_id}: {prerequisite_id}"
            )
        seen_ids.add(prerequisite_id)

        kind = _expect_string(data["kind"], "prerequisite.kind")
        if kind not in _ALLOWED_PREREQUISITE_KINDS:
            raise CompatibilityManifestError(
                f"unsupported prerequisite kind: {kind!r}"
            )
        required = _expect_bool(data["required"], "prerequisite.required")

        raw_commands = _expect_array(data["commands"], "prerequisite.commands")
        commands = tuple(
            _expect_string(command, "prerequisite command")
            for command in raw_commands
        )
        if not commands or len(commands) != len(set(commands)):
            raise CompatibilityManifestError(
                "prerequisite commands must be unique and non-empty"
            )
        if tuple(sorted(commands)) != commands:
            raise CompatibilityManifestError(
                "prerequisite commands must be sorted"
            )
        if any(
            "/" in command
            or "\\" in command
            or "://" in command
            or any(character.isspace() for character in command)
            for command in commands
        ):
            raise CompatibilityManifestError(
                "prerequisite commands must be bare executable names"
            )

        raw_platforms = _expect_array(
            data["platforms"], "prerequisite.platforms"
        )
        platforms = tuple(
            _expect_string(platform, "prerequisite platform")
            for platform in raw_platforms
        )
        if not platforms or len(platforms) != len(set(platforms)):
            raise CompatibilityManifestError(
                "prerequisite platforms must be unique and non-empty"
            )
        if tuple(sorted(platforms)) != platforms:
            raise CompatibilityManifestError(
                "prerequisite platforms must be sorted"
            )
        unknown_platforms = sorted(set(platforms) - _ALLOWED_PLATFORMS)
        if unknown_platforms:
            raise CompatibilityManifestError(
                "unsupported prerequisite platforms: "
                + ", ".join(unknown_platforms)
            )

        purpose = _expect_string(data["purpose"], "prerequisite.purpose")
        if "://" in purpose:
            raise CompatibilityManifestError(
                "prerequisite purpose must not contain a URL"
            )

        result.append(
            ExternalPrerequisite(
                prerequisite_id,
                kind,
                required,
                commands,
                platforms,
                purpose,
            )
        )

    prerequisite_ids = tuple(item.prerequisite_id for item in result)
    if prerequisite_ids != tuple(sorted(prerequisite_ids)):
        raise CompatibilityManifestError(
            f"component {component_id!r} prerequisites must be sorted by id"
        )

    return tuple(result)


def _parse_component(
    value: object,
    suite_python: PythonCompatibility,
) -> ComponentCompatibility:
    data = _expect_object(value, "component")
    required_fields = frozenset(
        {
            "component_id",
            "display_name",
            "repository",
            "distribution",
            "import_name",
            "required",
            "compatibility_status",
            "version",
            "requires_python",
            "release",
            "capabilities",
            "entry_points",
            "external_prerequisites",
        }
    )
    _expect_keys(data, required=required_fields, label="component")

    component_id = _expect_string(data["component_id"], "component.component_id")
    if _COMPONENT_ID_RE.fullmatch(component_id) is None:
        raise CompatibilityManifestError(
            f"invalid component_id: {component_id!r}"
        )
    if component_id not in _ALLOWED_COMPONENT_IDS:
        raise CompatibilityManifestError(
            f"unsupported PDS component_id: {component_id!r}"
        )

    display_name = _expect_string(data["display_name"], "component.display_name")
    repository = _expect_string(data["repository"], "component.repository")
    if _REPOSITORY_RE.fullmatch(repository) is None:
        raise CompatibilityManifestError(
            "component repository must be an official Paper-Data-Suite repo: "
            f"{repository!r}"
        )

    distribution = _expect_string(data["distribution"], "component.distribution")
    if _DISTRIBUTION_RE.fullmatch(distribution) is None:
        raise CompatibilityManifestError(
            f"invalid distribution name: {distribution!r}"
        )
    if distribution == _SUITE_DISTRIBUTION:
        raise CompatibilityManifestError(
            "suite wheel must not appear as a subordinate component row"
        )

    import_name = _expect_string(data["import_name"], "component.import_name")
    if _IMPORT_NAME_RE.fullmatch(import_name) is None:
        raise CompatibilityManifestError(
            f"invalid import_name: {import_name!r}"
        )

    required = _expect_bool(data["required"], "component.required")
    compatibility_status = _expect_string(
        data["compatibility_status"], "component.compatibility_status"
    )
    if compatibility_status not in _ALLOWED_COMPATIBILITY_STATUS:
        raise CompatibilityManifestError(
            f"unsupported compatibility_status: {compatibility_status!r}"
        )

    version = _expect_string(data["version"], "component.version")
    if _VERSION_RE.fullmatch(version) is None:
        raise CompatibilityManifestError(
            f"invalid component version: {version!r}"
        )
    if ".dev" in version:
        raise CompatibilityManifestError(
            f"supported component cannot use development version: {version!r}"
        )

    requires_python = _expect_string(
        data["requires_python"], "component.requires_python"
    )
    component_python = _parse_specifier(
        requires_python, "component.requires_python"
    )
    unsupported_suite_minors = [
        minor
        for minor in suite_python.tested_minors
        if not _version_satisfies(
            _parse_minor(minor, "suite tested minor"), component_python
        )
    ]
    if unsupported_suite_minors:
        raise CompatibilityManifestError(
            f"component {component_id} excludes suite-tested Python minors: "
            + ", ".join(unsupported_suite_minors)
        )

    release = _parse_release(
        data["release"], distribution=distribution, version=version
    )

    raw_capabilities = _expect_array(
        data["capabilities"], f"component {component_id!r} capabilities"
    )
    capabilities = tuple(
        _expect_string(item, f"component {component_id!r} capability")
        for item in raw_capabilities
    )
    if len(capabilities) != len(set(capabilities)):
        raise CompatibilityManifestError(
            f"component {component_id!r} capabilities contain duplicates"
        )
    if tuple(sorted(capabilities)) != capabilities:
        raise CompatibilityManifestError(
            f"component {component_id!r} capabilities must be sorted"
        )
    unknown_capabilities = sorted(set(capabilities) - _ALLOWED_CAPABILITIES)
    if unknown_capabilities:
        raise CompatibilityManifestError(
            "unsupported capabilities: " + ", ".join(unknown_capabilities)
        )

    entry_points = _parse_entry_points(data["entry_points"], component_id)
    external_prerequisites = _parse_prerequisites(
        data["external_prerequisites"], component_id
    )

    routing_entries = tuple(
        item for item in entry_points if item.group == "paper_data_suite.modules"
    )
    producer_entries = tuple(
        item
        for item in entry_points
        if item.group == "paper_data_suite.publication_producers"
    )
    console_entries = tuple(
        item for item in entry_points if item.group == "console_scripts"
    )

    if ("routing_module" in capabilities) != bool(routing_entries):
        raise CompatibilityManifestError(
            f"component {component_id!r} routing capability/entry points disagree"
        )
    if ("publication_producer" in capabilities) != bool(producer_entries):
        raise CompatibilityManifestError(
            f"component {component_id!r} producer capability/entry points disagree"
        )
    if "launchable_application" in capabilities and not console_entries:
        raise CompatibilityManifestError(
            f"launchable component {component_id!r} must expose a console script"
        )
    if component_id == "core":
        if "shared_core" not in capabilities:
            raise CompatibilityManifestError("Core must declare shared_core")
        if distribution != "pds-core":
            raise CompatibilityManifestError("Core distribution must be pds-core")
        if not required:
            raise CompatibilityManifestError("Core must be required")
    else:
        if "shared_core" in capabilities:
            raise CompatibilityManifestError(
                f"sibling component {component_id!r} cannot declare shared_core"
            )
        if required:
            raise CompatibilityManifestError(
                f"sibling component {component_id!r} cannot be required"
            )

    return ComponentCompatibility(
        component_id,
        display_name,
        repository,
        distribution,
        import_name,
        required,
        compatibility_status,
        version,
        requires_python,
        release,
        capabilities,
        entry_points,
        external_prerequisites,
    )


def parse_release_compatibility_manifest(
    text: str,
) -> ReleaseCompatibilityManifest:
    """Parse manifest JSON into immutable v1 models and enforce all invariants."""
    try:
        raw = json.loads(text, object_pairs_hook=_duplicate_rejecting_object)
    except CompatibilityManifestError:
        raise
    except json.JSONDecodeError as error:
        raise CompatibilityManifestError(
            f"invalid compatibility manifest JSON: {error.msg}"
        ) from error

    data = _expect_object(raw, "manifest")
    required = frozenset(
        {"record_type", "contract_version", "suite", "python", "components"}
    )
    _expect_keys(data, required=required, label="manifest")

    record_type = _expect_string(data["record_type"], "record_type")
    if record_type != _RECORD_TYPE:
        raise CompatibilityManifestError(
            f"record_type must be {_RECORD_TYPE!r}"
        )

    contract_version = _expect_string(
        data["contract_version"], "contract_version"
    )
    if contract_version != _CONTRACT_VERSION:
        raise CompatibilityManifestError(
            f"unsupported compatibility contract version: {contract_version!r}"
        )

    suite = _parse_suite(data["suite"])
    python = _parse_python(data["python"])
    raw_components = _expect_array(data["components"], "components")
    if not raw_components:
        raise CompatibilityManifestError("components cannot be empty")
    components = tuple(
        _parse_component(item, python) for item in raw_components
    )

    component_ids = tuple(item.component_id for item in components)
    if len(component_ids) != len(set(component_ids)):
        raise CompatibilityManifestError("duplicate component_id")

    distributions = tuple(item.distribution for item in components)
    if len(distributions) != len(set(distributions)):
        raise CompatibilityManifestError("duplicate component distribution")

    if component_ids != tuple(sorted(component_ids)):
        raise CompatibilityManifestError(
            "components must be sorted by component_id"
        )

    core_rows = tuple(item for item in components if item.component_id == "core")
    if len(core_rows) != 1:
        raise CompatibilityManifestError(
            "manifest must contain exactly one Core component row"
        )

    return ReleaseCompatibilityManifest(
        record_type,
        contract_version,
        suite,
        python,
        components,
    )


def load_release_compatibility_manifest() -> ReleaseCompatibilityManifest:
    """Load the bundled active compatibility manifest without environment probing."""
    resource = resources.files("paper_data_suite").joinpath(*_RESOURCE_PARTS)
    return parse_release_compatibility_manifest(resource.read_text(encoding="utf-8"))


__all__ = (
    "CompatibilityManifestError",
    "ComponentCompatibility",
    "EntryPointExpectation",
    "ExternalPrerequisite",
    "PythonCompatibility",
    "ReleaseArtifact",
    "ReleaseCompatibilityManifest",
    "SuiteCompatibility",
    "load_release_compatibility_manifest",
    "parse_release_compatibility_manifest",
)
