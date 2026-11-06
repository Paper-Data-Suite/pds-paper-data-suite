"""Nonmutating, offline installed-environment compatibility observations.

Slice 144: pure decision core and an importlib.metadata adapter. This module
DOES NOT authorize launch, establish official wheel provenance, authenticate
RECORD bytes, or certify cross-module integration. A later slice must verify
launcher confinement before enabling normal `pds launch`.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from importlib import metadata
from pathlib import Path
from typing import Final

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS

# This bound is the CURRENT Suite 0.1.x public requirement, not the immutable
# v0.1.0 exact-qualification pin (Core 0.6.3). Revisit when Suite requires
# another major Core public-contract generation.
CORE_RUNTIME_RANGE: Final = ">=0.6.3,<0.7"
_MAX_DISTRIBUTIONS: Final = 4_000
_MAX_REQUIRES: Final = 256
_MAX_ENTRYPOINTS: Final = 256
_MAX_DEPENDENCY_NODES: Final = 4_000


class Readiness(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    NOT_INSTALLED = "NOT_INSTALLED"
    INCOMPATIBLE = "INCOMPATIBLE"


class HistoricalEvidence(str, Enum):
    HISTORICAL_VERSION_MATCH = "HISTORICAL_VERSION_MATCH"
    NOT_PREVIOUSLY_INTEGRATION_TESTED = "NOT_PREVIOUSLY_INTEGRATION_TESTED"


class Provenance(str, Enum):
    UNVERIFIED = "PROVENANCE_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class ConsoleDeclaration:
    name: str
    target: str
    group: str = "console_scripts"


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    """Trust-neutral metadata; never treated as proof of official origin."""

    distribution: str
    version: str
    requires_python: str | None = None
    requires_dist: tuple[str, ...] = ()
    entry_points: tuple[ConsoleDeclaration, ...] = ()
    inside_environment: bool = True
    editable: bool = False
    wheel_metadata_present: bool = True


@dataclass(frozen=True, slots=True)
class ComponentAssessment:
    component_id: str
    distribution: str
    installed_version: str | None
    readiness: Readiness
    historical_evidence: HistoricalEvidence
    provenance: Provenance
    reason_codes: tuple[str, ...]

    @property
    def locally_compatible(self) -> bool:
        """Metadata-level compatibility only; not permission to execute."""
        return self.readiness is Readiness.COMPATIBLE


@dataclass(frozen=True, slots=True)
class LocalCompatibilityReport:
    components: tuple[ComponentAssessment, ...]

    def for_component(self, component_id: str) -> ComponentAssessment | None:
        return next(
            (item for item in self.components if item.component_id == component_id),
            None,
        )


class LocalInspectionError(RuntimeError):
    """Unsafe or unreadable installed-package observation."""


def _normal_name(value: str) -> str:
    if not value.strip():
        raise LocalInspectionError("empty distribution identity")
    return canonicalize_name(value)


def _version(value: str) -> Version:
    try:
        return Version(value)
    except InvalidVersion as error:
        raise LocalInspectionError("invalid installed version") from error


def _requires_python(specifier: str | None, python_version: Version) -> bool:
    if not specifier:
        return True
    try:
        return SpecifierSet(specifier).contains(python_version, prereleases=True)
    except InvalidSpecifier:
        return False


def _dependency_closure(
    root: InstalledPackage,
    installed: dict[str, InstalledPackage],
    duplicates: set[str],
    python_version: Version,
) -> set[str]:
    """Evaluate base and requested-extra dependencies without importing packages.

    Extra requirements from third-party dependencies are included only if the
    requiring edge selects that extra. No inference of optional Suite features.
    """
    problems: set[str] = set()
    done: set[tuple[str, tuple[str, ...]]] = set()
    pending: list[tuple[InstalledPackage, tuple[str, ...]]] = [(root, ("",))]
    # Convert marker metadata to a concrete string mapping for packaging's
    # evaluation contract (typeshed describes default Environment values as
    # object even though the marker environment supplies strings here).
    marker_environment: dict[str, str] = {
        key: str(value) for key, value in default_environment().items()
    }
    parts = python_version.release
    marker_environment["python_version"] = f"{parts[0]}.{parts[1]}"
    marker_environment["python_full_version"] = str(python_version)

    while pending:
        package, extras = pending.pop()
        state = (_normal_name(package.distribution), extras)
        if state in done:
            continue
        done.add(state)
        if len(done) > _MAX_DEPENDENCY_NODES:
            problems.add("dependency_graph_too_large")
            break
        if len(package.requires_dist) > _MAX_REQUIRES:
            problems.add("dependency_metadata_too_large")
            continue
        for raw_requirement in package.requires_dist:
            try:
                requirement = Requirement(raw_requirement)
            except (InvalidRequirement, ValueError):
                problems.add("dependency_requirement_invalid")
                continue
            try:
                applies = requirement.marker is None or any(
                    requirement.marker.evaluate({**marker_environment, "extra": extra})
                    for extra in extras
                )
            except (ValueError, KeyError):
                problems.add("dependency_marker_invalid")
                continue
            if not applies:
                continue
            if requirement.url is not None:
                problems.add("direct_url_dependency_unsupported")
                continue
            dependency_name = _normal_name(requirement.name)
            if dependency_name in duplicates:
                problems.add("dependency_ambiguous")
                continue
            dependency = installed.get(dependency_name)
            if dependency is None:
                problems.add("dependency_missing")
                continue
            if not dependency.inside_environment:
                problems.add("dependency_outside_environment")
                continue
            try:
                compatible = requirement.specifier.contains(
                    _version(dependency.version)
                )
            except LocalInspectionError:
                compatible = False
            if not compatible:
                problems.add("dependency_version_incompatible")
                continue
            if not _requires_python(dependency.requires_python, python_version):
                problems.add("dependency_python_incompatible")
                continue
            requested_extras = tuple(sorted(requirement.extras)) or ("",)
            pending.append((dependency, requested_extras))
    return problems


def assess_local_environment(
    packages: Sequence[InstalledPackage],
    *,
    python_version: str,
) -> LocalCompatibilityReport:
    """Pure, deterministic decision; NEVER use alone as a launch authority."""
    interpreter = _version(python_version)
    if len(interpreter.release) < 2:
        raise LocalInspectionError("interpreter version lacks major/minor")
    if len(packages) > _MAX_DISTRIBUTIONS:
        raise LocalInspectionError("installed distribution count exceeds bound")

    installed: dict[str, InstalledPackage] = {}
    duplicates: set[str] = set()
    for package in packages:
        name = _normal_name(package.distribution)
        if name in installed:
            duplicates.add(name)
        else:
            installed[name] = package
    declarations: dict[str, list[tuple[str, str, str]]] = {}
    for package in packages:
        owner = _normal_name(package.distribution)
        if len(package.entry_points) > _MAX_ENTRYPOINTS:
            raise LocalInspectionError("entry point inventory exceeds bound")
        for entry in package.entry_points:
            if entry.group == "console_scripts":
                declarations.setdefault(entry.name.casefold(), []).append(
                    (owner, entry.target, entry.name)
                )

    core_id = _normal_name("pds-core")
    core_state: Readiness | None = None
    assessments: list[ComponentAssessment] = []
    for component in APPROVED_COMPONENTS:
        distribution = _normal_name(component.distribution)
        found = installed.get(distribution)
        historical = (
            HistoricalEvidence.HISTORICAL_VERSION_MATCH
            if found is not None and found.version == component.historical_version
            else HistoricalEvidence.NOT_PREVIOUSLY_INTEGRATION_TESTED
        )
        if found is None:
            assessments.append(
                ComponentAssessment(
                    component.component_id,
                    component.distribution,
                    None,
                    Readiness.NOT_INSTALLED,
                    historical,
                    Provenance.UNVERIFIED,
                    ("distribution_missing",),
                )
            )
            if distribution == core_id:
                core_state = Readiness.NOT_INSTALLED
            continue
        problems: set[str] = set()
        if distribution in duplicates:
            problems.add("distribution_duplicate")
        if not found.inside_environment:
            problems.add("distribution_outside_environment")
        if found.editable:
            problems.add("editable_pds_install")
        if not found.wheel_metadata_present:
            problems.add("wheel_metadata_missing")
        try:
            package_version = _version(found.version)
            if (
                package_version.is_prerelease
                or package_version.is_devrelease
                or package_version.local is not None
            ):
                problems.add("nonstable_version_not_approved")
        except LocalInspectionError:
            problems.add("version_invalid")
        if found.requires_python is None:
            problems.add("python_requirement_missing")
        elif not _requires_python(found.requires_python, interpreter):
            problems.add("python_incompatible")
        if distribution == core_id:
            try:
                core_range_ok = SpecifierSet(CORE_RUNTIME_RANGE).contains(
                    _version(found.version)
                )
            except LocalInspectionError:
                core_range_ok = False
            if not core_range_ok:
                problems.add("suite_core_range_incompatible")
        elif core_state is not Readiness.COMPATIBLE:
            problems.add("core_not_compatible")
        problems.update(_dependency_closure(found, installed, duplicates, interpreter))

        for expected in component.console_scripts:
            matches = declarations.get(expected.name.casefold(), [])
            if not matches:
                problems.add("console_script_missing")
            elif len(matches) != 1:
                problems.add("console_script_ambiguous")
            else:
                owner, target, declared_name = matches[0]
                if declared_name != expected.name:
                    problems.add("console_script_name_mismatch")
                if owner != distribution:
                    problems.add("console_script_foreign_owner")
                if target != expected.target:
                    problems.add("console_script_target_mismatch")
        readiness = Readiness.INCOMPATIBLE if problems else Readiness.COMPATIBLE
        if distribution == core_id:
            core_state = readiness
        assessments.append(
            ComponentAssessment(
                component.component_id,
                component.distribution,
                found.version,
                readiness,
                historical,
                Provenance.UNVERIFIED,
                tuple(sorted(problems)) or ("local_metadata_compatible",),
            )
        )
    return LocalCompatibilityReport(tuple(assessments))


def _inside(path: Path, environment_root: Path) -> bool:
    try:
        root = environment_root.resolve(strict=False)
        resolved = path.resolve(strict=False)
        return os.path.commonpath((root, resolved)) == str(root)
    except (OSError, ValueError):
        return False


def _is_editable(dist: metadata.Distribution) -> bool:
    raw = dist.read_text("direct_url.json")
    if raw is None:
        return False
    if len(raw) > 40_000:
        return True
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return True
    if not isinstance(parsed, dict):
        return True
    info = parsed.get("dir_info")
    return isinstance(info, dict) and info.get("editable") is True


def observe_active_packages() -> tuple[InstalledPackage, ...]:
    """Only interrogate package metadata from the active Python interpreter."""
    observed: list[InstalledPackage] = []
    try:
        for dist in metadata.distributions():
            if len(observed) >= _MAX_DISTRIBUTIONS:
                raise LocalInspectionError("installed distribution count exceeds bound")
            name = dist.metadata["Name"]
            if not isinstance(name, str) or not name:
                raise LocalInspectionError("installed distribution missing Name")
            requirements = tuple(dist.requires or ())
            if len(requirements) > _MAX_REQUIRES:
                raise LocalInspectionError("dependency metadata exceeds bound")
            eps = tuple(
                ConsoleDeclaration(item.name, item.value, item.group)
                for item in dist.entry_points
            )
            if len(eps) > _MAX_ENTRYPOINTS:
                raise LocalInspectionError("entry point metadata exceeds bound")
            observed.append(
                InstalledPackage(
                    distribution=name,
                    version=dist.version,
                    requires_python=dist.metadata["Requires-Python"],
                    requires_dist=requirements,
                    entry_points=eps,
                    inside_environment=_inside(
                        Path(str(dist.locate_file(""))), Path(sys.prefix)
                    ),
                    editable=_is_editable(dist),
                    wheel_metadata_present=dist.read_text("WHEEL") is not None,
                )
            )
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        raise LocalInspectionError("unable to inspect installed metadata") from error
    return tuple(observed)


def inspect_local_compatibility() -> LocalCompatibilityReport:
    """Read-only adapter; no network, installation, provider import, or workspace."""
    return assess_local_environment(
        observe_active_packages(),
        python_version=".".join(str(value) for value in sys.version_info[:3]),
    )
