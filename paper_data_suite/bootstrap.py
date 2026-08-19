"""Pure, immutable planning for verified Paper Data Suite bootstrap."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from paper_data_suite.artifact_verification import (
    ArtifactVerificationError,
    normalize_sha256,
)
from paper_data_suite.compatibility import (
    ComponentCompatibility,
    ExternalPrerequisite,
    ReleaseCompatibilityManifest,
)

EnvironmentPlanAction: TypeAlias = Literal[
    "create_environment",
    "keep_environment",
    "blocked_environment",
]
PackagePlanAction: TypeAlias = Literal[
    "keep_exact",
    "install_missing",
    "skip_unselected_optional",
    "blocked_incompatible",
]
BootstrapBlockerCode: TypeAlias = Literal[
    "unsupported_python",
    "invalid_environment",
    "unmarked_environment",
    "environment_suite_mismatch",
    "environment_manifest_mismatch",
    "invalid_environment_marker",
    "incompatible_pds_version",
    "incompatible_pds_installation",
]
BootstrapWarningCode: TypeAlias = Literal[
    "external_prerequisite_not_managed",
]

_DISTRIBUTION_NORMALIZER_RE = re.compile(r"[-_.]+")
_PYTHON_VERSION_RE = re.compile(r"^([0-9]+)\.([0-9]+)(?:\.[0-9]+.*)?$")


class BootstrapPlanningError(ValueError):
    """Raised when caller-supplied planning input is internally invalid."""


@dataclass(frozen=True, slots=True)
class InstalledDistribution:
    """One installed distribution identity observed in a target environment."""

    distribution: str
    version: str
    editable: bool = False


@dataclass(frozen=True, slots=True)
class EnvironmentMarkerIdentity:
    """Compatibility identity read from a suite-owned environment marker."""

    suite_version: str
    compatibility_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """Side-effect-free snapshot used to plan one target environment."""

    path: str
    exists: bool
    is_virtual_environment: bool
    python_version: str
    marker: EnvironmentMarkerIdentity | None
    marker_error: str | None = None
    installed_distributions: tuple[InstalledDistribution, ...] = ()


@dataclass(frozen=True, slots=True)
class EnvironmentPlan:
    """Planned handling of one target environment."""

    path: str
    action: EnvironmentPlanAction
    python_version: str
    python_minor: str
    python_qualified: bool
    exists: bool


@dataclass(frozen=True, slots=True)
class PackagePlan:
    """One exact PDS package comparison against the target suite."""

    component_id: str
    display_name: str
    distribution: str
    desired_version: str
    installed_version: str | None
    required: bool
    selected: bool
    action: PackagePlanAction
    reason: str


@dataclass(frozen=True, slots=True)
class BootstrapBlocker:
    """One condition that prevents safe application of a plan."""

    code: BootstrapBlockerCode
    message: str
    component_id: str | None = None
    distribution: str | None = None


@dataclass(frozen=True, slots=True)
class BootstrapWarning:
    """One non-blocking condition requiring teacher/release awareness."""

    code: BootstrapWarningCode
    message: str


@dataclass(frozen=True, slots=True)
class ExternalPrerequisitePlan:
    """One manifest-declared external prerequisite required by selections."""

    prerequisite_id: str
    kind: str
    commands: tuple[str, ...]
    platforms: tuple[str, ...]
    purpose: str
    required_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    """Deterministic plan for one authenticated suite composition."""

    suite_version: str
    compatibility_manifest_sha256: str
    environment: EnvironmentPlan
    packages: tuple[PackagePlan, ...]
    external_prerequisites: tuple[ExternalPrerequisitePlan, ...]
    blockers: tuple[BootstrapBlocker, ...]
    warnings: tuple[BootstrapWarning, ...]

    @property
    def can_apply(self) -> bool:
        """Whether policy permits applying this plan."""
        return not self.blockers

    @property
    def changes_required(self) -> bool:
        """Whether a safe apply would create/install anything."""
        if self.environment.action == "create_environment":
            return True
        return any(item.action == "install_missing" for item in self.packages)


def normalize_distribution_name(value: str) -> str:
    """Normalize a Python distribution name for metadata comparison."""
    stripped = value.strip()
    if not stripped:
        raise BootstrapPlanningError("distribution name must not be empty")
    return _DISTRIBUTION_NORMALIZER_RE.sub("-", stripped).lower()


def python_minor_from_version(value: str) -> str:
    """Extract MAJOR.MINOR from a concrete interpreter version."""
    match = _PYTHON_VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise BootstrapPlanningError(
            "python_version must begin with MAJOR.MINOR"
        )
    return f"{int(match.group(1))}.{int(match.group(2))}"


def _normalized_manifest_sha256(value: str) -> str:
    try:
        return normalize_sha256(value)
    except ArtifactVerificationError as error:
        raise BootstrapPlanningError(str(error)) from error


def _installed_map(
    installed: Sequence[InstalledDistribution],
) -> dict[str, InstalledDistribution]:
    result: dict[str, InstalledDistribution] = {}
    for item in installed:
        name = normalize_distribution_name(item.distribution)
        if not item.version.strip():
            raise BootstrapPlanningError(
                f"installed version for {item.distribution!r} must not be empty"
            )
        if name in result:
            raise BootstrapPlanningError(
                f"duplicate installed distribution identity: {item.distribution!r}"
            )
        result[name] = item
    return result


def _selected_optional_ids(
    manifest: ReleaseCompatibilityManifest,
    selected_component_ids: Sequence[str],
) -> frozenset[str]:
    raw = tuple(selected_component_ids)
    if len(set(raw)) != len(raw):
        raise BootstrapPlanningError(
            "selected optional component IDs must not contain duplicates"
        )

    optional_ids = frozenset(
        item.component_id for item in manifest.components if not item.required
    )
    for component_id in raw:
        if component_id == "core":
            raise BootstrapPlanningError(
                "core is required and must not be selected as optional"
            )
        if component_id not in optional_ids:
            raise BootstrapPlanningError(
                f"unsupported optional component ID: {component_id!r}"
            )
    return frozenset(raw)


def _package_plan(
    *,
    component_id: str,
    display_name: str,
    distribution: str,
    desired_version: str,
    installed: Mapping[str, InstalledDistribution],
    required: bool,
    selected: bool,
) -> tuple[PackagePlan, BootstrapBlocker | None]:
    normalized = normalize_distribution_name(distribution)
    observed = installed.get(normalized)
    installed_version = observed.version if observed is not None else None

    if observed is None:
        if required or selected:
            reason = (
                "required PDS package is missing"
                if required
                else "selected optional PDS package is missing"
            )
            return (
                PackagePlan(
                    component_id=component_id,
                    display_name=display_name,
                    distribution=distribution,
                    desired_version=desired_version,
                    installed_version=None,
                    required=required,
                    selected=selected,
                    action="install_missing",
                    reason=reason,
                ),
                None,
            )

        return (
            PackagePlan(
                component_id=component_id,
                display_name=display_name,
                distribution=distribution,
                desired_version=desired_version,
                installed_version=None,
                required=required,
                selected=selected,
                action="skip_unselected_optional",
                reason="optional PDS component was not selected",
            ),
            None,
        )

    if observed.editable:
        blocker = BootstrapBlocker(
            code="incompatible_pds_installation",
            component_id=component_id,
            distribution=distribution,
            message=(
                f"{distribution} {installed_version} is installed editable or "
                "source-linked; exact released-wheel installation is required"
            ),
        )
        return (
            PackagePlan(
                component_id=component_id,
                display_name=display_name,
                distribution=distribution,
                desired_version=desired_version,
                installed_version=installed_version,
                required=required,
                selected=selected,
                action="blocked_incompatible",
                reason=blocker.message,
            ),
            blocker,
        )

    if installed_version == desired_version:
        return (
            PackagePlan(
                component_id=component_id,
                display_name=display_name,
                distribution=distribution,
                desired_version=desired_version,
                installed_version=installed_version,
                required=required,
                selected=selected,
                action="keep_exact",
                reason="exact suite-qualified version is already installed",
            ),
            None,
        )

    blocker = BootstrapBlocker(
        code="incompatible_pds_version",
        component_id=component_id,
        distribution=distribution,
        message=(
            f"{distribution} {installed_version} is installed but this suite "
            f"qualifies exactly {desired_version}; automatic replacement is forbidden"
        ),
    )
    return (
        PackagePlan(
            component_id=component_id,
            display_name=display_name,
            distribution=distribution,
            desired_version=desired_version,
            installed_version=installed_version,
            required=required,
            selected=selected,
            action="blocked_incompatible",
            reason=blocker.message,
        ),
        blocker,
    )


def _environment_blockers(
    *,
    manifest: ReleaseCompatibilityManifest,
    manifest_sha256: str,
    snapshot: EnvironmentSnapshot,
    python_minor: str,
) -> tuple[BootstrapBlocker, ...]:
    blockers: list[BootstrapBlocker] = []

    if python_minor not in manifest.python.tested_minors:
        blockers.append(
            BootstrapBlocker(
                code="unsupported_python",
                message=(
                    f"Python {python_minor} is not suite-qualified; expected one of "
                    + ", ".join(manifest.python.tested_minors)
                ),
            )
        )

    if not snapshot.exists:
        if (
            snapshot.marker is not None
            or snapshot.marker_error is not None
            or snapshot.installed_distributions
        ):
            raise BootstrapPlanningError(
                "nonexistent environment snapshot cannot contain marker/packages"
            )
        return tuple(blockers)

    if not snapshot.is_virtual_environment:
        blockers.append(
            BootstrapBlocker(
                code="invalid_environment",
                message="existing target is not a validated virtual environment",
            )
        )

    if snapshot.marker_error is not None:
        blockers.append(
            BootstrapBlocker(
                code="invalid_environment_marker",
                message=(
                    "existing target has an invalid Paper Data Suite environment "
                    f"marker: {snapshot.marker_error}"
                ),
            )
        )
        return tuple(blockers)

    marker = snapshot.marker
    if marker is None:
        blockers.append(
            BootstrapBlocker(
                code="unmarked_environment",
                message=(
                    "existing target has no Paper Data Suite environment marker; "
                    "automatic adoption is forbidden"
                ),
            )
        )
        return tuple(blockers)

    marker_digest: str | None
    try:
        marker_digest = normalize_sha256(
            marker.compatibility_manifest_sha256
        )
    except ArtifactVerificationError:
        marker_digest = None
        blockers.append(
            BootstrapBlocker(
                code="invalid_environment_marker",
                message=(
                    "environment marker contains an invalid compatibility "
                    "manifest SHA-256"
                ),
            )
        )

    if marker.suite_version != manifest.suite.version:
        blockers.append(
            BootstrapBlocker(
                code="environment_suite_mismatch",
                message=(
                    f"environment marker targets suite {marker.suite_version}, "
                    f"not {manifest.suite.version}"
                ),
            )
        )
    if marker_digest is not None and marker_digest != manifest_sha256:
        blockers.append(
            BootstrapBlocker(
                code="environment_manifest_mismatch",
                message=(
                    "environment marker compatibility manifest identity "
                    "does not match the target suite"
                ),
            )
        )
    return tuple(blockers)


def _external_prerequisites(
    components: Sequence[ComponentCompatibility],
) -> tuple[ExternalPrerequisitePlan, ...]:
    by_id: dict[str, tuple[ExternalPrerequisite, set[str]]] = {}
    for component in components:
        for prerequisite in component.external_prerequisites:
            current = by_id.get(prerequisite.prerequisite_id)
            if current is None:
                by_id[prerequisite.prerequisite_id] = (
                    prerequisite,
                    {component.component_id},
                )
                continue

            existing, required_by = current
            if existing != prerequisite:
                raise BootstrapPlanningError(
                    "same external prerequisite ID has conflicting definitions: "
                    f"{prerequisite.prerequisite_id!r}"
                )
            required_by.add(component.component_id)

    result = tuple(
        ExternalPrerequisitePlan(
            prerequisite_id=prerequisite.prerequisite_id,
            kind=prerequisite.kind,
            commands=prerequisite.commands,
            platforms=prerequisite.platforms,
            purpose=prerequisite.purpose,
            required_by=tuple(sorted(required_by)),
        )
        for prerequisite, required_by in (
            by_id[key] for key in sorted(by_id)
        )
    )
    return result


def build_bootstrap_plan(
    manifest: ReleaseCompatibilityManifest,
    *,
    compatibility_manifest_sha256: str,
    environment: EnvironmentSnapshot,
    selected_component_ids: Sequence[str] = (),
) -> BootstrapPlan:
    """Compare one environment snapshot to one authenticated suite manifest."""
    manifest_sha256 = _normalized_manifest_sha256(
        compatibility_manifest_sha256
    )
    python_minor = python_minor_from_version(environment.python_version)
    selected_ids = _selected_optional_ids(
        manifest,
        selected_component_ids,
    )
    installed = _installed_map(environment.installed_distributions)

    environment_blockers = list(
        _environment_blockers(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            snapshot=environment,
            python_minor=python_minor,
        )
    )

    package_plans: list[PackagePlan] = []
    package_blockers: list[BootstrapBlocker] = []

    core = next(
        (item for item in manifest.components if item.component_id == "core"),
        None,
    )
    if core is None or not core.required:
        raise BootstrapPlanningError(
            "compatibility manifest must contain required core component"
        )

    core_plan, blocker = _package_plan(
        component_id=core.component_id,
        display_name=core.display_name,
        distribution=core.distribution,
        desired_version=core.version,
        installed=installed,
        required=True,
        selected=True,
    )
    package_plans.append(core_plan)
    if blocker is not None:
        package_blockers.append(blocker)

    suite_plan, blocker = _package_plan(
        component_id="suite",
        display_name="Paper Data Suite",
        distribution=manifest.suite.distribution,
        desired_version=manifest.suite.version,
        installed=installed,
        required=True,
        selected=True,
    )
    package_plans.append(suite_plan)
    if blocker is not None:
        package_blockers.append(blocker)

    selected_components: list[ComponentCompatibility] = []
    for component in manifest.components:
        if component.component_id == "core":
            continue
        selected = component.component_id in selected_ids
        package_plan, blocker = _package_plan(
            component_id=component.component_id,
            display_name=component.display_name,
            distribution=component.distribution,
            desired_version=component.version,
            installed=installed,
            required=component.required,
            selected=selected,
        )
        package_plans.append(package_plan)
        if blocker is not None:
            package_blockers.append(blocker)
        if selected:
            selected_components.append(component)

    prerequisites = _external_prerequisites(selected_components)
    warnings = tuple(
        BootstrapWarning(
            code="external_prerequisite_not_managed",
            message=(
                f"external prerequisite {item.prerequisite_id} is required by "
                f"{', '.join(item.required_by)} and is not installed by bootstrap"
            ),
        )
        for item in prerequisites
    )

    blockers = tuple(environment_blockers + package_blockers)
    environment_action: EnvironmentPlanAction
    if environment_blockers:
        environment_action = "blocked_environment"
    elif environment.exists:
        environment_action = "keep_environment"
    else:
        environment_action = "create_environment"

    return BootstrapPlan(
        suite_version=manifest.suite.version,
        compatibility_manifest_sha256=manifest_sha256,
        environment=EnvironmentPlan(
            path=environment.path,
            action=environment_action,
            python_version=environment.python_version,
            python_minor=python_minor,
            python_qualified=python_minor in manifest.python.tested_minors,
            exists=environment.exists,
        ),
        packages=tuple(package_plans),
        external_prerequisites=prerequisites,
        blockers=blockers,
        warnings=warnings,
    )
