"""Read-only suite application discovery and launch-eligibility classification."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from importlib import metadata
from pathlib import Path

from paper_data_suite.compatibility import (
    ComponentCompatibility,
    ReleaseCompatibilityManifest,
    load_release_compatibility_manifest,
)
from paper_data_suite.component_inspection import (
    DistributionVersionLookup,
    EntryPointInventoryLookup,
    EntryPointMatchStatus,
    EntryPointObservation,
    installed_entry_point_inventory,
    lookup_distribution_version,
    match_entry_point_metadata,
)


class ApplicationInventoryError(RuntimeError):
    """Raised when installed software metadata cannot be inspected safely."""


class ApplicationLaunchStatus(str, Enum):
    """Suite-level launch eligibility for one manifest-qualified application."""

    AVAILABLE = "AVAILABLE"
    NOT_INSTALLED = "NOT_INSTALLED"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ApplicationObservation:
    """One deterministic application row derived from the suite release contract."""

    component_id: str
    display_name: str
    purpose: str
    distribution: str
    qualified_version: str
    installed_version: str | None
    console_script_name: str
    console_script_target: str
    status: ApplicationLaunchStatus
    reason: str
    remediation: str | None = None
    launcher_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ApplicationInventory:
    """Immutable application inventory in manifest order."""

    applications: tuple[ApplicationObservation, ...]

    def for_component(self, component_id: str) -> ApplicationObservation | None:
        """Return one known launchable application by stable component ID."""
        return next(
            (
                application
                for application in self.applications
                if application.component_id == component_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class _RuntimeQualification:
    python_qualified: bool
    python_minor: str
    suite_expected_version: str
    suite_version: str | None
    core: ComponentCompatibility
    core_version: str | None


_REPAIR_GUIDANCE = (
    "Use the verified Paper Data Suite bootstrap/update workflow to restore the "
    "suite-qualified environment."
)


def _lookup_version_or_error(
    distribution: str,
    *,
    version_lookup: DistributionVersionLookup,
) -> str | None:
    try:
        return lookup_distribution_version(distribution, version_lookup)
    except (OSError, TypeError, ValueError) as error:
        message = str(error)[:300] or error.__class__.__name__
        raise ApplicationInventoryError(
            f"could not inspect distribution {distribution!r}: {message}"
        ) from error


def _shared_core(manifest: ReleaseCompatibilityManifest) -> ComponentCompatibility:
    candidates = tuple(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    if len(candidates) != 1:
        raise ApplicationInventoryError(
            "suite manifest does not identify exactly one shared Core component"
        )
    return candidates[0]


def _runtime_qualification(
    manifest: ReleaseCompatibilityManifest,
    *,
    python_version: tuple[int, int, int],
    version_lookup: DistributionVersionLookup,
) -> _RuntimeQualification:
    python_minor = f"{python_version[0]}.{python_version[1]}"
    core = _shared_core(manifest)
    return _RuntimeQualification(
        python_qualified=python_minor in manifest.python.tested_minors,
        python_minor=python_minor,
        suite_expected_version=manifest.suite.version,
        suite_version=_lookup_version_or_error(
            manifest.suite.distribution,
            version_lookup=version_lookup,
        ),
        core=core,
        core_version=_lookup_version_or_error(
            core.distribution,
            version_lookup=version_lookup,
        ),
    )


def _console_expectation(component: ComponentCompatibility) -> tuple[str, str]:
    expectations = tuple(
        expectation
        for expectation in component.entry_points
        if expectation.group == "console_scripts"
    )
    if len(expectations) != 1:
        raise ApplicationInventoryError(
            f"launchable component {component.component_id!r} does not declare "
            "exactly one console-script launch boundary"
        )
    expectation = expectations[0]
    return expectation.name, expectation.target


def _entry_point_failure_reason(
    status: EntryPointMatchStatus,
    *,
    console_name: str,
    component: ComponentCompatibility,
) -> str:
    identity = f"console_scripts:{console_name}"
    if status is EntryPointMatchStatus.MISSING:
        return f"Expected launch entry point {identity} is missing."
    if status is EntryPointMatchStatus.OWNER_MISMATCH:
        return (
            f"Launch entry point {identity} is not owned by "
            f"{component.distribution}."
        )
    if status is EntryPointMatchStatus.DUPLICATE:
        return (
            f"Launch entry point {identity} has duplicate definitions in "
            f"{component.distribution}."
        )
    if status is EntryPointMatchStatus.TARGET_MISMATCH:
        return f"Launch entry point {identity} has an unexpected target."
    if status is EntryPointMatchStatus.CONFLICT:
        return f"Launch entry point {identity} conflicts with another distribution."
    raise AssertionError(f"unexpected entry-point failure status: {status}")


def _observation(
    component: ComponentCompatibility,
    *,
    runtime: _RuntimeQualification,
    installed_version: str | None,
    inventory: tuple[EntryPointObservation, ...],
) -> ApplicationObservation:
    purpose = component.purpose
    if purpose is None:
        raise ApplicationInventoryError(
            f"launchable component {component.component_id!r} has no teacher purpose"
        )
    console_name, console_target = _console_expectation(component)

    def result(
        status: ApplicationLaunchStatus,
        reason: str,
        remediation: str | None = None,
    ) -> ApplicationObservation:
        return ApplicationObservation(
            component_id=component.component_id,
            display_name=component.display_name,
            purpose=purpose,
            distribution=component.distribution,
            qualified_version=component.version,
            installed_version=installed_version,
            console_script_name=console_name,
            console_script_target=console_target,
            status=status,
            reason=reason,
            remediation=remediation,
        )

    if installed_version is None:
        return result(
            ApplicationLaunchStatus.NOT_INSTALLED,
            (
                f"{component.display_name} is supported by this suite release but "
                "is not installed."
            ),
            (
                "Use the verified Paper Data Suite bootstrap workflow if you want "
                f"to install {component.display_name}."
            ),
        )

    if installed_version != component.version:
        return result(
            ApplicationLaunchStatus.INCOMPATIBLE,
            (
                f"Installed {component.distribution} {installed_version} does not "
                f"match suite-qualified {component.version}."
            ),
            _REPAIR_GUIDANCE,
        )

    if not runtime.python_qualified:
        return result(
            ApplicationLaunchStatus.INCOMPATIBLE,
            (
                f"Python {runtime.python_minor} is not a suite-qualified interpreter "
                "minor."
            ),
            _REPAIR_GUIDANCE,
        )

    if runtime.suite_version != runtime.suite_expected_version:
        observed = runtime.suite_version or "not installed"
        return result(
            ApplicationLaunchStatus.INCOMPATIBLE,
            (
                f"Running suite metadata reports {observed}; expected "
                f"{runtime.suite_expected_version}."
            ),
            _REPAIR_GUIDANCE,
        )

    if runtime.core_version != runtime.core.version:
        observed = runtime.core_version or "not installed"
        return result(
            ApplicationLaunchStatus.INCOMPATIBLE,
            (
                f"Installed {runtime.core.distribution} is {observed}; this suite "
                f"qualifies exactly {runtime.core.version}."
            ),
            _REPAIR_GUIDANCE,
        )

    match = match_entry_point_metadata(
        component,
        group="console_scripts",
        name=console_name,
        target=console_target,
        inventory=inventory,
    )
    if match.status is not EntryPointMatchStatus.MATCH:
        return result(
            ApplicationLaunchStatus.INCOMPATIBLE,
            _entry_point_failure_reason(
                match.status,
                console_name=console_name,
                component=component,
            ),
            _REPAIR_GUIDANCE,
        )

    return result(
        ApplicationLaunchStatus.AVAILABLE,
        (
            f"{component.display_name} {component.version} has a suite-qualified "
            "public menu entry point."
        ),
    )


def collect_application_inventory(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    python_version: tuple[int, int, int] | None = None,
    version_lookup: DistributionVersionLookup = metadata.version,
    entry_point_inventory_lookup: EntryPointInventoryLookup = (
        installed_entry_point_inventory
    ),
) -> ApplicationInventory:
    """Inspect manifest-qualified applications without loading or launching them."""
    active_manifest = manifest or load_release_compatibility_manifest()
    observed_python = python_version or (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    runtime = _runtime_qualification(
        active_manifest,
        python_version=observed_python,
        version_lookup=version_lookup,
    )

    try:
        entry_points = tuple(entry_point_inventory_lookup())
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        message = str(error)[:300] or error.__class__.__name__
        raise ApplicationInventoryError(
            f"installed entry-point metadata could not be inventoried: {message}"
        ) from error

    applications: list[ApplicationObservation] = []
    for component in active_manifest.components:
        if "launchable_application" not in component.capabilities:
            continue
        installed_version = _lookup_version_or_error(
            component.distribution,
            version_lookup=version_lookup,
        )
        applications.append(
            _observation(
                component,
                runtime=runtime,
                installed_version=installed_version,
                inventory=entry_points,
            )
        )
    return ApplicationInventory(tuple(applications))


__all__ = (
    "ApplicationInventory",
    "ApplicationInventoryError",
    "ApplicationLaunchStatus",
    "ApplicationObservation",
    "collect_application_inventory",
)
