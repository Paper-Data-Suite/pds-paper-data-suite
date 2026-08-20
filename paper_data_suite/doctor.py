"""Typed, read-only diagnostic primitives for the Paper Data Suite shell."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from paper_data_suite.bootstrap import normalize_distribution_name
from paper_data_suite.compatibility import (
    ComponentCompatibility,
    ExternalPrerequisite,
    ReleaseCompatibilityManifest,
    load_release_compatibility_manifest,
    release_compatibility_manifest_sha256,
)
from paper_data_suite.component_inspection import (
    DistributionVersionLookup,
    EntryPointInventoryLookup,
    EntryPointObservation,
)
from paper_data_suite.component_inspection import (
    component_is_suite_qualified as _qualified_component,
)
from paper_data_suite.component_inspection import (
    installed_entry_point_inventory as _installed_entry_point_inventory,
)
from paper_data_suite.component_inspection import (
    lookup_distribution_version as _lookup_distribution_version,
)
from paper_data_suite.component_inspection import (
    normalize_entry_point_owner as _normalized_owner,
)
from paper_data_suite.environment_inspection import (
    ENVIRONMENT_MARKER_FILENAME,
    EnvironmentInspectionError,
    parse_environment_marker,
)

CommandLookup = Callable[[str], str | None]
ManifestDigestLookup = Callable[[], str]
ModuleImporter = Callable[[str], object]


class CommandRunner(Protocol):
    """Bounded command-execution shape used by read-only diagnostics."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


class DiagnosticStatus(str, Enum):
    """Bounded outcome for one doctor diagnostic check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One deterministic, privacy-bounded diagnostic result."""

    section: str
    code: str
    status: DiagnosticStatus
    summary: str
    component_id: str | None = None
    detail: str | None = None
    remediation: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("section", self.section),
            ("code", self.code),
            ("summary", self.summary),
        ):
            if not value or not value.strip():
                raise ValueError(f"diagnostic {label} must be a non-empty string")
        if self.component_id is not None and not self.component_id.strip():
            raise ValueError("diagnostic component_id cannot be blank")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("diagnostic detail cannot be blank")
        if self.remediation is not None and not self.remediation.strip():
            raise ValueError("diagnostic remediation cannot be blank")


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Immutable ordered collection of doctor diagnostic checks."""

    checks: tuple[DiagnosticCheck, ...]

    @property
    def failure_count(self) -> int:
        """Return the number of blocking diagnostic failures."""
        return sum(check.status is DiagnosticStatus.FAIL for check in self.checks)

    @property
    def warning_count(self) -> int:
        """Return the number of non-blocking diagnostic warnings."""
        return sum(check.status is DiagnosticStatus.WARN for check in self.checks)

    @property
    def exit_code(self) -> int:
        """Return the CLI exit status implied by this completed report."""
        return 1 if self.failure_count else 0

    def for_section(self, section: str) -> tuple[DiagnosticCheck, ...]:
        """Return checks in their original order for one section."""
        return tuple(check for check in self.checks if check.section == section)


def combine_reports(*reports: DoctorReport) -> DoctorReport:
    """Combine already ordered diagnostic reports without changing their checks."""
    return DoctorReport(tuple(check for report in reports for check in report.checks))


def _python_check(
    manifest: ReleaseCompatibilityManifest,
    *,
    python_version: tuple[int, int, int],
    python_executable: str,
) -> DiagnosticCheck:
    major, minor, micro = python_version
    observed_minor = f"{major}.{minor}"
    observed_version = f"{major}.{minor}.{micro}"
    qualified = observed_minor in manifest.python.tested_minors
    if qualified:
        return DiagnosticCheck(
            section="Runtime",
            code="python.qualified",
            status=DiagnosticStatus.PASS,
            summary=f"Python {observed_version} is suite-qualified.",
            detail=f"Interpreter: {python_executable}",
        )

    qualified_text = ", ".join(manifest.python.tested_minors)
    return DiagnosticCheck(
        section="Runtime",
        code="python.unsupported",
        status=DiagnosticStatus.FAIL,
        summary=f"Python {observed_version} is not suite-qualified.",
        detail=(
            f"Interpreter: {python_executable}; qualified minors: {qualified_text}."
        ),
        remediation=(
            "Run this Paper Data Suite release with a qualified Python minor "
            f"({qualified_text}), then rerun `pds doctor`."
        ),
    )


def _suite_package_check(
    manifest: ReleaseCompatibilityManifest,
    *,
    version_lookup: DistributionVersionLookup,
) -> DiagnosticCheck:
    distribution = manifest.suite.distribution
    expected = manifest.suite.version
    observed = _lookup_distribution_version(distribution, version_lookup)
    if observed is None:
        return DiagnosticCheck(
            section="Suite",
            code="suite.distribution_missing",
            status=DiagnosticStatus.FAIL,
            summary=f"{distribution} distribution metadata is unavailable.",
            detail=f"Expected suite version: {expected}.",
            remediation=(
                "Reinstall this Paper Data Suite release through the verified suite "
                "bootstrap/update workflow, then rerun `pds doctor`."
            ),
        )
    if observed != expected:
        return DiagnosticCheck(
            section="Suite",
            code="suite.version_mismatch",
            status=DiagnosticStatus.FAIL,
            summary=(
                f"{distribution} {observed} does not match the bundled suite "
                f"manifest version {expected}."
            ),
            remediation=(
                f"Install the suite-qualified {distribution} {expected} release, "
                "then rerun `pds doctor`."
            ),
        )
    return DiagnosticCheck(
        section="Suite",
        code="suite.version_match",
        status=DiagnosticStatus.PASS,
        summary=f"{distribution} {observed} matches the bundled suite manifest.",
    )


def _component_package_check(
    component: ComponentCompatibility,
    *,
    version_lookup: DistributionVersionLookup,
) -> DiagnosticCheck:
    observed = _lookup_distribution_version(component.distribution, version_lookup)
    if observed is None:
        if component.required:
            return DiagnosticCheck(
                section="Packages",
                code="package.required_missing",
                status=DiagnosticStatus.FAIL,
                component_id=component.component_id,
                summary=(
                    f"{component.display_name} is required but "
                    f"{component.distribution} is not installed."
                ),
                detail=f"Required version: {component.version}.",
                remediation=(
                    f"Install the suite-qualified {component.distribution} "
                    f"{component.version} release, then rerun `pds doctor`."
                ),
            )
        return DiagnosticCheck(
            section="Packages",
            code="package.optional_absent",
            status=DiagnosticStatus.SKIP,
            component_id=component.component_id,
            summary=f"{component.display_name} is optional and is not installed.",
            detail=f"Suite-qualified version when installed: {component.version}.",
        )

    if observed != component.version:
        return DiagnosticCheck(
            section="Packages",
            code="package.version_mismatch",
            status=DiagnosticStatus.FAIL,
            component_id=component.component_id,
            summary=(
                f"{component.display_name} has {component.distribution} {observed}; "
                f"the suite qualifies exactly {component.version}."
            ),
            remediation=(
                f"Install the suite-qualified {component.distribution} "
                f"{component.version} release, then rerun `pds doctor`."
            ),
        )

    return DiagnosticCheck(
        section="Packages",
        code="package.version_match",
        status=DiagnosticStatus.PASS,
        component_id=component.component_id,
        summary=(
            f"{component.display_name} {component.distribution} {observed} "
            "matches the suite manifest."
        ),
    )


def collect_runtime_package_diagnostics(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    python_version: tuple[int, int, int] | None = None,
    python_executable: str | None = None,
    version_lookup: DistributionVersionLookup = metadata.version,
) -> DoctorReport:
    """Collect deterministic runtime and package diagnostics.

    The check uses only the running interpreter and installed distribution metadata.
    """
    active_manifest = manifest or load_release_compatibility_manifest()
    observed_python = python_version or (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    observed_executable = python_executable or sys.executable

    checks: list[DiagnosticCheck] = [
        _python_check(
            active_manifest,
            python_version=observed_python,
            python_executable=observed_executable,
        ),
        _suite_package_check(active_manifest, version_lookup=version_lookup),
    ]
    checks.extend(
        _component_package_check(component, version_lookup=version_lookup)
        for component in active_manifest.components
    )
    return DoctorReport(tuple(checks))


def _environment_marker_check(
    manifest: ReleaseCompatibilityManifest,
    *,
    environment_root: Path,
    manifest_digest_lookup: ManifestDigestLookup,
) -> DiagnosticCheck:
    marker_path = environment_root / ENVIRONMENT_MARKER_FILENAME
    if not marker_path.exists():
        return DiagnosticCheck(
            section="Suite",
            code="suite.marker_missing",
            status=DiagnosticStatus.WARN,
            summary="Suite environment ownership marker is not present.",
            detail=f"Expected marker: {marker_path}",
            remediation=(
                "For a managed installation, use the verified suite bootstrap/update "
                "workflow. Development and manual environments may continue without "
                "a marker."
            ),
        )
    if not marker_path.is_file():
        return DiagnosticCheck(
            section="Suite",
            code="suite.marker_unreadable",
            status=DiagnosticStatus.FAIL,
            summary="Suite environment ownership marker is not a regular file.",
            detail=f"Marker path: {marker_path}",
            remediation=(
                "Restore this environment through the verified suite bootstrap/update "
                "workflow, then rerun `pds doctor`."
            ),
        )

    try:
        marker = parse_environment_marker(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, EnvironmentInspectionError) as error:
        return DiagnosticCheck(
            section="Suite",
            code="suite.marker_invalid",
            status=DiagnosticStatus.FAIL,
            summary="Suite environment ownership marker is invalid.",
            detail=str(error),
            remediation=(
                "Restore this environment through the verified suite bootstrap/update "
                "workflow; do not hand-edit the marker. Then rerun `pds doctor`."
            ),
        )

    expected_digest = manifest_digest_lookup()
    mismatches: list[str] = []
    if marker.suite_version != manifest.suite.version:
        mismatches.append(
            f"suite version {marker.suite_version!r} != {manifest.suite.version!r}"
        )
    if marker.compatibility_manifest_sha256 != expected_digest:
        mismatches.append("compatibility manifest digest does not match this suite")
    if mismatches:
        return DiagnosticCheck(
            section="Suite",
            code="suite.marker_mismatch",
            status=DiagnosticStatus.FAIL,
            summary=(
                "Suite environment ownership marker belongs to another composition."
            ),
            detail="; ".join(mismatches) + ".",
            remediation=(
                "Use the verified suite update workflow to reconcile the environment "
                "with this release, then rerun `pds doctor`."
            ),
        )

    return DiagnosticCheck(
        section="Suite",
        code="suite.marker_match",
        status=DiagnosticStatus.PASS,
        summary="Suite environment ownership marker matches this release.",
        detail=f"Marker: {marker_path}",
    )


def _bounded_command_output(result: subprocess.CompletedProcess[str]) -> str | None:
    lines = [
        line.strip()
        for text in (result.stdout, result.stderr)
        for line in text.splitlines()
        if line.strip()
    ]
    if not lines:
        return None
    bounded = " | ".join(lines[:4])
    if len(bounded) > 500:
        return bounded[:497] + "..."
    return bounded


def _default_command_runner(
    args: Sequence[str],
    *,
    capture_output: bool,
    text: bool,
    check: bool,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=capture_output,
        text=text,
        check=check,
        timeout=timeout,
    )


def _python_dependency_check(
    *,
    python_executable: str,
    command_runner: CommandRunner,
    timeout_seconds: float,
) -> DiagnosticCheck:
    command = (python_executable, "-m", "pip", "check")
    try:
        result = command_runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return DiagnosticCheck(
            section="Dependencies",
            code="dependencies.pip_check_timeout",
            status=DiagnosticStatus.FAIL,
            summary="Python dependency consistency check timed out.",
            detail=f"Timeout: {timeout_seconds:g} seconds.",
            remediation=(
                "Verify that pip is healthy in this environment, then rerun "
                "`pds doctor`."
            ),
        )
    except OSError as error:
        return DiagnosticCheck(
            section="Dependencies",
            code="dependencies.pip_check_unavailable",
            status=DiagnosticStatus.FAIL,
            summary="Python dependency consistency check could not be started.",
            detail=str(error),
            remediation=(
                "Verify the current Python environment and its pip installation, then "
                "rerun `pds doctor`."
            ),
        )

    detail = _bounded_command_output(result)
    if result.returncode == 0:
        return DiagnosticCheck(
            section="Dependencies",
            code="dependencies.consistent",
            status=DiagnosticStatus.PASS,
            summary="Installed Python package dependencies are consistent.",
            detail=detail,
        )
    return DiagnosticCheck(
        section="Dependencies",
        code="dependencies.inconsistent",
        status=DiagnosticStatus.FAIL,
        summary="Installed Python package dependencies are inconsistent.",
        detail=detail or f"pip check exited with status {result.returncode}.",
        remediation=(
            "Repair the installed suite environment through the verified bootstrap/"
            "update workflow, then rerun `pds doctor`."
        ),
    )


def _platform_name(platform: str) -> str:
    normalized = platform.lower()
    if normalized.startswith(("win32", "cygwin", "msys")):
        return "windows"
    if normalized.startswith("linux"):
        return "linux"
    if normalized == "darwin":
        return "macos"
    return normalized


@dataclass(frozen=True, slots=True)
class _PrerequisiteUse:
    prerequisite: ExternalPrerequisite
    consumers: tuple[ComponentCompatibility, ...]


def _applicable_prerequisites(
    manifest: ReleaseCompatibilityManifest,
    *,
    platform: str,
) -> tuple[_PrerequisiteUse, ...]:
    by_id: dict[str, tuple[ExternalPrerequisite, list[ComponentCompatibility]]] = {}
    for component in manifest.components:
        for prerequisite in component.external_prerequisites:
            if platform not in prerequisite.platforms:
                continue
            existing = by_id.get(prerequisite.prerequisite_id)
            if existing is None:
                by_id[prerequisite.prerequisite_id] = (prerequisite, [component])
                continue
            canonical, consumers = existing
            if prerequisite != canonical:
                # Keep both definitions visible to the caller through duplicate uses.
                conflict_id = f"{prerequisite.prerequisite_id}:{component.component_id}"
                by_id[conflict_id] = (prerequisite, [component])
                continue
            consumers.append(component)

    return tuple(
        _PrerequisiteUse(prerequisite, tuple(consumers))
        for _, (prerequisite, consumers) in sorted(by_id.items())
    )


def _qualified_installed_consumers(
    use: _PrerequisiteUse,
    *,
    version_lookup: DistributionVersionLookup,
) -> tuple[ComponentCompatibility, ...]:
    return tuple(
        component
        for component in use.consumers
        if _lookup_distribution_version(component.distribution, version_lookup)
        == component.version
    )


def _external_prerequisite_check(
    use: _PrerequisiteUse,
    *,
    version_lookup: DistributionVersionLookup,
    command_lookup: CommandLookup,
) -> DiagnosticCheck:
    prerequisite = use.prerequisite
    active_consumers = _qualified_installed_consumers(
        use,
        version_lookup=version_lookup,
    )
    consumer_names = ", ".join(
        component.display_name for component in active_consumers
    )
    commands = ", ".join(prerequisite.commands)

    if not active_consumers:
        return DiagnosticCheck(
            section="External prerequisites",
            code="external.not_required",
            status=DiagnosticStatus.SKIP,
            summary=(
                f"{prerequisite.prerequisite_id} is not required by an installed "
                "suite-qualified component."
            ),
            detail=f"Accepted command names: {commands}.",
        )

    found: tuple[tuple[str, str], ...] = tuple(
        (command, path)
        for command in prerequisite.commands
        if (path := command_lookup(command)) is not None
    )
    if found:
        command, path = found[0]
        return DiagnosticCheck(
            section="External prerequisites",
            code="external.command_available",
            status=DiagnosticStatus.PASS,
            summary=f"{command} is available for {consumer_names}.",
            detail=f"{prerequisite.purpose}; resolved command: {path}",
        )

    status = DiagnosticStatus.FAIL if prerequisite.required else DiagnosticStatus.WARN
    return DiagnosticCheck(
        section="External prerequisites",
        code="external.command_missing",
        status=status,
        summary=(
            f"Required command for {consumer_names} was not found."
            if prerequisite.required
            else f"Optional command for {consumer_names} was not found."
        ),
        detail=f"{prerequisite.purpose}; accepted command names: {commands}.",
        remediation=(
            f"Install or expose {commands} on PATH for this environment, then rerun "
            "`pds doctor`."
        ),
    )


def collect_environment_dependency_diagnostics(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    environment_root: Path | None = None,
    python_executable: str | None = None,
    platform: str | None = None,
    version_lookup: DistributionVersionLookup = metadata.version,
    manifest_digest_lookup: ManifestDigestLookup = (
        release_compatibility_manifest_sha256
    ),
    command_lookup: CommandLookup = shutil.which,
    command_runner: CommandRunner = _default_command_runner,
    pip_check_timeout_seconds: float = 20.0,
) -> DoctorReport:
    """Check environment ownership, Python dependencies, and external commands.

    All checks are read-only. External prerequisites are activated only by components
    installed at the exact version qualified by the bundled suite manifest.
    """
    active_manifest = manifest or load_release_compatibility_manifest()
    root = (environment_root or Path(sys.prefix)).expanduser().resolve()
    executable = python_executable or sys.executable
    active_platform = _platform_name(platform or sys.platform)

    checks: list[DiagnosticCheck] = [
        _environment_marker_check(
            active_manifest,
            environment_root=root,
            manifest_digest_lookup=manifest_digest_lookup,
        ),
        _python_dependency_check(
            python_executable=executable,
            command_runner=command_runner,
            timeout_seconds=pip_check_timeout_seconds,
        ),
    ]
    checks.extend(
        _external_prerequisite_check(
            use,
            version_lookup=version_lookup,
            command_lookup=command_lookup,
        )
        for use in _applicable_prerequisites(
            active_manifest,
            platform=active_platform,
        )
    )
    return DoctorReport(tuple(checks))


_CORE_PUBLIC_CONTRACTS: tuple[tuple[str, str, str], ...] = (
    ("pds_core.workspace", "inspect_workspace_root", "workspace inspection"),
    ("pds_core.school_years", "get_active_school_year", "active school year"),
    (
        "pds_core.registry_audit",
        "get_academic_registry_status",
        "academic registry status",
    ),
)


def _entry_point_component_skip(
    component: ComponentCompatibility,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        section="Entry points",
        code="entry_point.component_unqualified",
        status=DiagnosticStatus.SKIP,
        component_id=component.component_id,
        summary=(
            f"{component.display_name} entry points were not checked because the "
            "suite-qualified package version is not installed."
        ),
    )


def _entry_point_check(
    component: ComponentCompatibility,
    expectation_group: str,
    expectation_name: str,
    expectation_target: str,
    *,
    inventory: Sequence[EntryPointObservation],
) -> DiagnosticCheck:
    expected_owner = normalize_distribution_name(component.distribution)
    same_identity = tuple(
        item
        for item in inventory
        if item.group == expectation_group and item.name == expectation_name
    )
    owned = tuple(
        item
        for item in same_identity
        if _normalized_owner(item.distribution) == expected_owner
    )
    foreign = tuple(
        item
        for item in same_identity
        if _normalized_owner(item.distribution) != expected_owner
    )
    identity = f"{expectation_group}:{expectation_name}"

    if not owned:
        if foreign:
            owners = ", ".join(
                sorted({item.distribution for item in foreign}, key=str.lower)
            )
            return DiagnosticCheck(
                section="Entry points",
                code="entry_point.owner_mismatch",
                status=DiagnosticStatus.FAIL,
                component_id=component.component_id,
                summary=(
                    f"{identity} is not owned by the suite-qualified "
                    f"{component.distribution} distribution."
                ),
                detail=f"Observed owner(s): {owners}.",
                remediation=(
                    f"Reinstall {component.distribution} {component.version} through "
                    "the verified suite workflow, then rerun `pds doctor`."
                ),
            )
        return DiagnosticCheck(
            section="Entry points",
            code="entry_point.missing",
            status=DiagnosticStatus.FAIL,
            component_id=component.component_id,
            summary=f"Expected public entry point {identity} is missing.",
            detail=(
                f"Expected owner: {component.distribution}; target: "
                f"{expectation_target}."
            ),
            remediation=(
                f"Reinstall {component.distribution} {component.version} through the "
                "verified suite workflow, then rerun `pds doctor`."
            ),
        )

    if len(owned) != 1:
        targets = ", ".join(sorted(item.target for item in owned))
        return DiagnosticCheck(
            section="Entry points",
            code="entry_point.duplicate",
            status=DiagnosticStatus.FAIL,
            component_id=component.component_id,
            summary=(
                f"{identity} has duplicate definitions in "
                f"{component.distribution}."
            ),
            detail=f"Observed targets: {targets}.",
            remediation=(
                f"Reinstall {component.distribution} {component.version} into a clean "
                "suite environment, then rerun `pds doctor`."
            ),
        )

    observed = owned[0]
    if observed.target != expectation_target:
        return DiagnosticCheck(
            section="Entry points",
            code="entry_point.target_mismatch",
            status=DiagnosticStatus.FAIL,
            component_id=component.component_id,
            summary=f"{identity} has an unexpected target.",
            detail=(
                f"Expected {expectation_target}; observed {observed.target}; owner "
                f"{observed.distribution} {observed.distribution_version}."
            ),
            remediation=(
                f"Reinstall {component.distribution} {component.version} through the "
                "verified suite workflow, then rerun `pds doctor`."
            ),
        )

    if foreign:
        conflicts = ", ".join(
            sorted(
                {
                    f"{item.distribution} {item.distribution_version} -> {item.target}"
                    for item in foreign
                },
                key=str.lower,
            )
        )
        return DiagnosticCheck(
            section="Entry points",
            code="entry_point.conflict",
            status=DiagnosticStatus.FAIL,
            component_id=component.component_id,
            summary=(
                f"{identity} has a conflicting definition from another package."
            ),
            detail=f"Conflicting definition(s): {conflicts}.",
            remediation=(
                "Remove or reconcile the conflicting Python package through the "
                "managed suite environment workflow, then rerun `pds doctor`."
            ),
        )

    return DiagnosticCheck(
        section="Entry points",
        code="entry_point.match",
        status=DiagnosticStatus.PASS,
        component_id=component.component_id,
        summary=(
            f"{identity} matches {component.distribution} {component.version}."
        ),
        detail=f"Target: {expectation_target}.",
    )


def _core_component(
    manifest: ReleaseCompatibilityManifest,
) -> ComponentCompatibility | None:
    candidates = tuple(
        component
        for component in manifest.components
        if "shared_core" in component.capabilities
    )
    return candidates[0] if len(candidates) == 1 else None


def _core_contract_diagnostics(
    manifest: ReleaseCompatibilityManifest,
    *,
    version_lookup: DistributionVersionLookup,
    module_importer: ModuleImporter,
) -> tuple[DiagnosticCheck, ...]:
    component = _core_component(manifest)
    if component is None:
        return (
            DiagnosticCheck(
                section="Core",
                code="core.manifest_contract_missing",
                status=DiagnosticStatus.FAIL,
                summary=(
                    "The suite manifest does not identify exactly one shared Core "
                    "component."
                ),
                remediation=(
                    "Restore the authenticated compatibility manifest for this suite "
                    "release, then rerun `pds doctor`."
                ),
            ),
        )

    if not _qualified_component(component, version_lookup=version_lookup):
        return (
            DiagnosticCheck(
                section="Core",
                code="core.contracts_skipped",
                status=DiagnosticStatus.SKIP,
                component_id=component.component_id,
                summary=(
                    "Core public contracts were not imported because the exact "
                    "suite-qualified Core package is not installed."
                ),
            ),
        )

    checks: list[DiagnosticCheck] = []
    for module_name, attribute_name, purpose in _CORE_PUBLIC_CONTRACTS:
        try:
            module = module_importer(module_name)
        except (ImportError, OSError, RuntimeError) as error:
            checks.append(
                DiagnosticCheck(
                    section="Core",
                    code="core.contract_import_failed",
                    status=DiagnosticStatus.FAIL,
                    component_id=component.component_id,
                    summary=f"Core {purpose} contract could not be imported.",
                    detail=str(error)[:500] or "Import failed without a message.",
                    remediation=(
                        f"Reinstall {component.distribution} {component.version} "
                        "through the verified suite workflow, then rerun `pds doctor`."
                    ),
                )
            )
            continue

        contract = getattr(module, attribute_name, None)
        if not callable(contract):
            checks.append(
                DiagnosticCheck(
                    section="Core",
                    code="core.contract_missing",
                    status=DiagnosticStatus.FAIL,
                    component_id=component.component_id,
                    summary=f"Core {purpose} public contract is unavailable.",
                    detail=f"Expected callable: {module_name}.{attribute_name}.",
                    remediation=(
                        f"Reinstall {component.distribution} {component.version} "
                        "through the verified suite workflow, then rerun `pds doctor`."
                    ),
                )
            )
            continue

        checks.append(
            DiagnosticCheck(
                section="Core",
                code="core.contract_available",
                status=DiagnosticStatus.PASS,
                component_id=component.component_id,
                summary=f"Core {purpose} public contract is available.",
                detail=f"Callable: {module_name}.{attribute_name}.",
            )
        )
    return tuple(checks)


def collect_entry_point_core_diagnostics(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
    entry_point_inventory_lookup: EntryPointInventoryLookup = (
        _installed_entry_point_inventory
    ),
    module_importer: ModuleImporter = import_module,
) -> DoctorReport:
    """Check exact public entry-point metadata and existing Core contracts.

    Entry-point targets are never loaded. Provider-profile discovery is intentionally
    not performed here: failure-isolated provider inventory remains Core-owned.
    """
    active_manifest = manifest or load_release_compatibility_manifest()
    checks: list[DiagnosticCheck] = []

    try:
        inventory = tuple(entry_point_inventory_lookup())
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        inventory = ()
        checks.append(
            DiagnosticCheck(
                section="Entry points",
                code="entry_point.inventory_unavailable",
                status=DiagnosticStatus.FAIL,
                summary="Installed entry-point metadata could not be inventoried.",
                detail=(
                    str(error)[:500] or "Metadata inventory failed without a message."
                ),
                remediation=(
                    "Repair the installed Python environment through the verified "
                    "suite workflow, then rerun `pds doctor`."
                ),
            )
        )

    if not checks:
        for component in active_manifest.components:
            if not component.entry_points:
                continue
            if not _qualified_component(component, version_lookup=version_lookup):
                checks.append(_entry_point_component_skip(component))
                continue
            for expectation in component.entry_points:
                checks.append(
                    _entry_point_check(
                        component,
                        expectation.group,
                        expectation.name,
                        expectation.target,
                        inventory=inventory,
                    )
                )

    checks.extend(
        _core_contract_diagnostics(
            active_manifest,
            version_lookup=version_lookup,
            module_importer=module_importer,
        )
    )
    return DoctorReport(tuple(checks))


class WorkspaceStatusLike(Protocol):
    """Public Core workspace status fields consumed by suite diagnostics."""

    root: Path
    source: str
    exists: bool
    is_dir: bool
    is_writable: bool


class WorkspaceInspector(Protocol):
    """Public Core workspace-inspection callable shape."""

    def __call__(
        self,
        explicit_root: str | Path | None = None,
    ) -> WorkspaceStatusLike: ...


class SchoolYearLookup(Protocol):
    """Public Core active-school-year callable shape."""

    def __call__(self, workspace_root: str | Path) -> str | None: ...


class RegistryFindingLike(Protocol):
    """Privacy-bounded Core registry finding fields used for summaries."""

    severity: str
    code: str


class RegistryStatusLike(Protocol):
    """Public Core registry-status fields consumed by suite diagnostics."""

    canonical_valid: bool
    contracts_compatible: bool | None
    catalog_state: str
    catalog_sources_current: bool | None
    lock_count: int
    temporary_artifact_count: int
    findings: Sequence[RegistryFindingLike]


class RegistryStatusLookup(Protocol):
    """Public Core registry-status callable shape."""

    def __call__(
        self,
        workspace_root: str | Path,
        *,
        verify_manifests: bool = False,
    ) -> RegistryStatusLike: ...


@dataclass(frozen=True, slots=True)
class _CoreWorkspaceServices:
    inspect_workspace_root: WorkspaceInspector
    get_active_school_year: SchoolYearLookup
    get_academic_registry_status: RegistryStatusLookup


class _CoreWorkspaceServiceError(RuntimeError):
    """Raised when a required public Core workspace service cannot be loaded."""


def _load_core_workspace_services(
    module_importer: ModuleImporter,
) -> _CoreWorkspaceServices:
    loaded: dict[tuple[str, str], object] = {}
    for module_name, attribute_name, _purpose in _CORE_PUBLIC_CONTRACTS:
        try:
            module = module_importer(module_name)
        except Exception as error:
            raise _CoreWorkspaceServiceError(
                f"could not import {module_name}: {error}"
            ) from error
        value = getattr(module, attribute_name, None)
        if not callable(value):
            raise _CoreWorkspaceServiceError(
                f"public Core callable is unavailable: {module_name}.{attribute_name}"
            )
        loaded[(module_name, attribute_name)] = value

    return _CoreWorkspaceServices(
        inspect_workspace_root=cast(
            WorkspaceInspector,
            loaded[("pds_core.workspace", "inspect_workspace_root")],
        ),
        get_active_school_year=cast(
            SchoolYearLookup,
            loaded[("pds_core.school_years", "get_active_school_year")],
        ),
        get_academic_registry_status=cast(
            RegistryStatusLookup,
            loaded[("pds_core.registry_audit", "get_academic_registry_status")],
        ),
    )


def _dependent_workspace_skip(section: str, code: str, summary: str) -> DiagnosticCheck:
    return DiagnosticCheck(
        section=section,
        code=code,
        status=DiagnosticStatus.SKIP,
        summary=summary,
    )


def _workspace_status_check(
    status: WorkspaceStatusLike,
) -> tuple[DiagnosticCheck, Path | None]:
    try:
        root = Path(status.root)
        source = status.source
        exists = status.exists
        is_dir = status.is_dir
        is_writable = status.is_writable
    except (AttributeError, TypeError, ValueError) as error:
        return (
            DiagnosticCheck(
                section="Workspace",
                code="workspace.status_invalid",
                status=DiagnosticStatus.FAIL,
                summary="Core returned an invalid workspace status result.",
                detail=str(error)[:500] or "Workspace status shape is invalid.",
                remediation=(
                    "Repair the suite-qualified Core installation, then rerun "
                    "`pds doctor`."
                ),
            ),
            None,
        )

    if not isinstance(source, str) or not source.strip():
        return (
            DiagnosticCheck(
                section="Workspace",
                code="workspace.status_invalid",
                status=DiagnosticStatus.FAIL,
                summary="Core returned an invalid workspace selection source.",
                remediation=(
                    "Repair the suite-qualified Core installation, then rerun "
                    "`pds doctor`."
                ),
            ),
            None,
        )
    if not all(isinstance(value, bool) for value in (exists, is_dir, is_writable)):
        return (
            DiagnosticCheck(
                section="Workspace",
                code="workspace.status_invalid",
                status=DiagnosticStatus.FAIL,
                summary="Core returned invalid workspace access flags.",
                remediation=(
                    "Repair the suite-qualified Core installation, then rerun "
                    "`pds doctor`."
                ),
            ),
            None,
        )

    detail = f"Path: {root}; selection source: {source}."
    if not exists:
        return (
            DiagnosticCheck(
                section="Workspace",
                code="workspace.not_configured",
                status=DiagnosticStatus.WARN,
                summary=(
                    "No accessible workspace currently exists at the resolved path."
                ),
                detail=detail,
                remediation=(
                    "Complete Paper Data Suite workspace setup, then rerun "
                    "`pds doctor`."
                ),
            ),
            None,
        )
    if not is_dir:
        return (
            DiagnosticCheck(
                section="Workspace",
                code="workspace.not_directory",
                status=DiagnosticStatus.FAIL,
                summary="The resolved workspace path is not a directory.",
                detail=detail,
                remediation=(
                    "Select or restore a valid Paper Data Suite workspace directory, "
                    "then rerun `pds doctor`."
                ),
            ),
            None,
        )
    if not is_writable:
        return (
            DiagnosticCheck(
                section="Workspace",
                code="workspace.not_writable",
                status=DiagnosticStatus.FAIL,
                summary="The resolved workspace is not writable according to Core.",
                detail=detail,
                remediation=(
                    "Restore write access to the workspace or select an accessible "
                    "workspace, then rerun `pds doctor`."
                ),
            ),
            None,
        )

    return (
        DiagnosticCheck(
            section="Workspace",
            code="workspace.accessible",
            status=DiagnosticStatus.PASS,
            summary="The resolved workspace exists and is writable.",
            detail=detail,
        ),
        root,
    )


def _school_year_check(
    root: Path,
    lookup: SchoolYearLookup,
) -> DiagnosticCheck:
    try:
        school_year = lookup(root)
    except Exception as error:
        return DiagnosticCheck(
            section="Workspace",
            code="school_year.state_invalid",
            status=DiagnosticStatus.FAIL,
            summary="Core could not read the active school-year state.",
            detail=str(error)[:500] or "School-year lookup failed without a message.",
            remediation=(
                "Review the Core school-year state through its supported workflow, "
                "then rerun `pds doctor`."
            ),
        )

    if school_year is None:
        return DiagnosticCheck(
            section="Workspace",
            code="school_year.not_active",
            status=DiagnosticStatus.WARN,
            summary="No active school year is configured for this workspace.",
            remediation=(
                "Complete the Paper Data Suite school-year setup workflow, then "
                "rerun `pds doctor`."
            ),
        )
    if not isinstance(school_year, str) or not school_year.strip():
        return DiagnosticCheck(
            section="Workspace",
            code="school_year.state_invalid",
            status=DiagnosticStatus.FAIL,
            summary="Core returned an invalid active school-year value.",
            remediation=(
                "Review the Core school-year state through its supported workflow, "
                "then rerun `pds doctor`."
            ),
        )
    return DiagnosticCheck(
        section="Workspace",
        code="school_year.active",
        status=DiagnosticStatus.PASS,
        summary=f"Active school year: {school_year}.",
    )


def _finding_summary(findings: Sequence[RegistryFindingLike]) -> tuple[int, int, str]:
    errors = 0
    warnings = 0
    codes: list[str] = []
    for finding in findings:
        severity = getattr(finding, "severity", None)
        code = getattr(finding, "code", None)
        if severity == "error":
            errors += 1
        elif severity == "warning":
            warnings += 1
        if isinstance(code, str) and code and code not in codes:
            codes.append(code)
    bounded_codes = ", ".join(codes[:5])
    if len(codes) > 5:
        bounded_codes += f", +{len(codes) - 5} more"
    return errors, warnings, bounded_codes


def _registry_status_checks(status: RegistryStatusLike) -> tuple[DiagnosticCheck, ...]:
    try:
        canonical_valid = status.canonical_valid
        contracts_compatible = status.contracts_compatible
        catalog_state = status.catalog_state
        catalog_sources_current = status.catalog_sources_current
        lock_count = status.lock_count
        temporary_artifact_count = status.temporary_artifact_count
        findings = tuple(status.findings)
    except (AttributeError, TypeError, ValueError) as error:
        return (
            DiagnosticCheck(
                section="Core registry",
                code="registry.status_invalid",
                status=DiagnosticStatus.FAIL,
                summary="Core returned an invalid academic-registry status result.",
                detail=str(error)[:500] or "Registry status shape is invalid.",
                remediation=(
                    "Repair the suite-qualified Core installation, then rerun "
                    "`pds doctor`."
                ),
            ),
        )

    checks: list[DiagnosticCheck] = []
    if canonical_valid is True:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.canonical_valid",
                status=DiagnosticStatus.PASS,
                summary="Core reports canonical academic-registry state as valid.",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.canonical_invalid",
                status=DiagnosticStatus.FAIL,
                summary="Core reports invalid canonical academic-registry state.",
                remediation=(
                    "Review the reported Core registry condition using Core's "
                    "supported audit/maintenance workflow."
                ),
            )
        )

    if contracts_compatible is None:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.contracts_not_reported",
                status=DiagnosticStatus.SKIP,
                summary="Core did not report registry contract compatibility.",
            )
        )
    elif contracts_compatible is True:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.contracts_compatible",
                status=DiagnosticStatus.PASS,
                summary="Core reports registry contracts as compatible.",
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.contracts_incompatible",
                status=DiagnosticStatus.FAIL,
                summary="Core reports incompatible registry contracts.",
                remediation=(
                    "Review the reported Core registry condition using Core's "
                    "supported audit/maintenance workflow."
                ),
            )
        )

    if catalog_state == "ready" and catalog_sources_current is True:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.catalog_ready",
                status=DiagnosticStatus.PASS,
                summary="Core reports the academic catalog as ready and current.",
            )
        )
    elif catalog_state in {"missing", "absent", "not_built"}:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.catalog_missing",
                status=DiagnosticStatus.WARN,
                summary="Core reports that the academic catalog is not built.",
                remediation=(
                    "Use Core's supported catalog workflow when catalog-backed "
                    "features are needed; `pds doctor` will not build it."
                ),
            )
        )
    else:
        currency = (
            "unknown"
            if catalog_sources_current is None
            else ("current" if catalog_sources_current else "stale")
        )
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.catalog_unhealthy",
                status=DiagnosticStatus.FAIL,
                summary="Core reports an unhealthy or stale academic catalog.",
                detail=f"Catalog state: {catalog_state}; source currency: {currency}.",
                remediation=(
                    "Review the Core registry/catalog condition using Core's "
                    "supported audit/maintenance workflow."
                ),
            )
        )

    if isinstance(lock_count, int) and isinstance(temporary_artifact_count, int):
        if lock_count == 0 and temporary_artifact_count == 0:
            checks.append(
                DiagnosticCheck(
                    section="Core registry",
                    code="registry.coordination_clear",
                    status=DiagnosticStatus.PASS,
                    summary=(
                        "Core reports no coordination locks or temporary artifacts."
                    ),
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    section="Core registry",
                    code="registry.coordination_present",
                    status=DiagnosticStatus.WARN,
                    summary="Core reports coordination state that requires attention.",
                    detail=(
                        f"Locks: {lock_count}; temporary artifacts: "
                        f"{temporary_artifact_count}."
                    ),
                    remediation=(
                        "Review this state with Core's supported audit/maintenance "
                        "workflow; `pds doctor` will not clear locks or artifacts."
                    ),
                )
            )
    else:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.status_invalid",
                status=DiagnosticStatus.FAIL,
                summary="Core returned invalid registry coordination counts.",
                remediation=(
                    "Repair the suite-qualified Core installation, then rerun "
                    "`pds doctor`."
                ),
            )
        )

    errors, warnings, codes = _finding_summary(findings)
    if errors:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.findings_error",
                status=DiagnosticStatus.FAIL,
                summary=f"Core reports {errors} registry error finding(s).",
                detail=(
                    f"Warning findings: {warnings}; finding codes: {codes or 'none'}."
                ),
                remediation=(
                    "Review the reported Core registry findings using Core's "
                    "supported audit/maintenance workflow."
                ),
            )
        )
    elif warnings:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.findings_warning",
                status=DiagnosticStatus.WARN,
                summary=f"Core reports {warnings} registry warning finding(s).",
                detail=f"Finding codes: {codes or 'none'}.",
                remediation=(
                    "Review the reported Core registry findings before relying on "
                    "affected workflows."
                ),
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                section="Core registry",
                code="registry.findings_clear",
                status=DiagnosticStatus.PASS,
                summary="Core reports no blocking or warning registry findings.",
            )
        )

    return tuple(checks)


def _registry_check(
    root: Path,
    lookup: RegistryStatusLookup,
) -> tuple[DiagnosticCheck, ...]:
    try:
        status = lookup(root, verify_manifests=False)
    except Exception as error:
        return (
            DiagnosticCheck(
                section="Core registry",
                code="registry.inspection_failed",
                status=DiagnosticStatus.FAIL,
                summary="Core academic-registry health inspection failed.",
                detail=(
                    str(error)[:500]
                    or "Registry inspection failed without a message."
                ),
                remediation=(
                    "Review the workspace with Core's supported registry audit "
                    "workflow, then rerun `pds doctor`."
                ),
            ),
        )
    return _registry_status_checks(status)


def collect_workspace_registry_diagnostics(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    workspace: str | Path | None = None,
    version_lookup: DistributionVersionLookup = metadata.version,
    module_importer: ModuleImporter = import_module,
    services: _CoreWorkspaceServices | None = None,
) -> DoctorReport:
    """Collect read-only Core workspace, school-year, and registry diagnostics.

    The optional workspace path is invocation-scoped input only. This function never
    saves, creates, initializes, repairs, or otherwise mutates a Core workspace.
    """
    active_manifest = manifest or load_release_compatibility_manifest()
    core = _core_component(active_manifest)
    if core is None:
        return DoctorReport(
            (
                DiagnosticCheck(
                    section="Workspace",
                    code="workspace.core_manifest_invalid",
                    status=DiagnosticStatus.FAIL,
                    summary=(
                        "Workspace diagnostics cannot identify exactly one shared "
                        "Core component in the suite manifest."
                    ),
                ),
                _dependent_workspace_skip(
                    "Workspace",
                    "school_year.skipped",
                    (
                        "Active school-year diagnostics require an accessible Core "
                        "workspace."
                    ),
                ),
                _dependent_workspace_skip(
                    "Core registry",
                    "registry.skipped",
                    "Registry diagnostics require an accessible Core workspace.",
                ),
            )
        )
    if not _qualified_component(core, version_lookup=version_lookup):
        return DoctorReport(
            (
                _dependent_workspace_skip(
                    "Workspace",
                    "workspace.core_unqualified",
                    (
                        "Workspace diagnostics require the exact suite-qualified "
                        "Core package."
                    ),
                ),
                _dependent_workspace_skip(
                    "Workspace",
                    "school_year.core_unqualified",
                    (
                        "School-year diagnostics require the exact suite-qualified "
                        "Core package."
                    ),
                ),
                _dependent_workspace_skip(
                    "Core registry",
                    "registry.core_unqualified",
                    (
                        "Registry diagnostics require the exact suite-qualified "
                        "Core package."
                    ),
                ),
            )
        )

    try:
        active_services = services or _load_core_workspace_services(module_importer)
    except _CoreWorkspaceServiceError as error:
        return DoctorReport(
            (
                DiagnosticCheck(
                    section="Workspace",
                    code="workspace.core_service_unavailable",
                    status=DiagnosticStatus.FAIL,
                    component_id=core.component_id,
                    summary="Required public Core workspace services are unavailable.",
                    detail=str(error)[:500],
                    remediation=(
                        f"Reinstall {core.distribution} {core.version} through the "
                        "verified suite workflow, then rerun `pds doctor`."
                    ),
                ),
                _dependent_workspace_skip(
                    "Workspace",
                    "school_year.skipped",
                    "Active school-year diagnostics require Core workspace services.",
                ),
                _dependent_workspace_skip(
                    "Core registry",
                    "registry.skipped",
                    "Registry diagnostics require Core workspace services.",
                ),
            )
        )

    try:
        workspace_status = active_services.inspect_workspace_root(workspace)
    except Exception as error:
        return DoctorReport(
            (
                DiagnosticCheck(
                    section="Workspace",
                    code="workspace.inspection_failed",
                    status=DiagnosticStatus.FAIL,
                    component_id=core.component_id,
                    summary="Core could not inspect the resolved workspace.",
                    detail=(
                        str(error)[:500]
                        or "Workspace inspection failed without a message."
                    ),
                    remediation=(
                        "Review the workspace selection with Core's supported "
                        "configuration workflow, then rerun `pds doctor`."
                    ),
                ),
                _dependent_workspace_skip(
                    "Workspace",
                    "school_year.skipped",
                    "Active school-year diagnostics require an accessible workspace.",
                ),
                _dependent_workspace_skip(
                    "Core registry",
                    "registry.skipped",
                    "Registry diagnostics require an accessible workspace.",
                ),
            )
        )

    workspace_check, root = _workspace_status_check(workspace_status)
    if root is None:
        return DoctorReport(
            (
                workspace_check,
                _dependent_workspace_skip(
                    "Workspace",
                    "school_year.skipped",
                    "Active school-year diagnostics require an accessible workspace.",
                ),
                _dependent_workspace_skip(
                    "Core registry",
                    "registry.skipped",
                    "Registry diagnostics require an accessible workspace.",
                ),
            )
        )

    return DoctorReport(
        (
            workspace_check,
            _school_year_check(root, active_services.get_active_school_year),
            *_registry_check(root, active_services.get_academic_registry_status),
        )
    )

_SECTION_ORDER: tuple[str, ...] = (
    "Runtime",
    "Suite",
    "Packages",
    "Dependencies",
    "Entry points",
    "Core",
    "External prerequisites",
    "Workspace",
    "Core registry",
    "Providers",
    "Modules",
)


def collect_reduced_provider_diagnostics(
    manifest: ReleaseCompatibilityManifest | None = None,
    *,
    version_lookup: DistributionVersionLookup = metadata.version,
) -> DoctorReport:
    """Report reduced provider diagnostic fidelity for the current Core contract.

    Failure-isolated routing/publication provider diagnostics and shared module
    readiness are Core-owned additive contracts. Until the suite-qualified Core
    release exposes those contracts, doctor reports the limitation explicitly
    rather than reimplementing strict Core discovery or inspecting module internals.
    """
    active_manifest = manifest or load_release_compatibility_manifest()
    core = _core_component(active_manifest)
    if core is None:
        detail = (
            "The suite manifest does not identify exactly one shared Core "
            "component."
        )
    elif not _qualified_component(core, version_lookup=version_lookup):
        detail = (
            "The exact suite-qualified Core package is not installed, so deeper "
            "provider contract diagnostics are unavailable."
        )
    else:
        detail = (
            "The suite-qualified Core contract does not yet expose the optional "
            "failure-isolated provider diagnostic surface."
        )

    return DoctorReport(
        (
            DiagnosticCheck(
                section="Providers",
                code="providers.reduced_fidelity",
                status=DiagnosticStatus.SKIP,
                summary=(
                    "Routing/publication provider compatibility has reduced "
                    "diagnostic fidelity."
                ),
                detail=detail,
            ),
            DiagnosticCheck(
                section="Modules",
                code="module.readiness_unavailable",
                status=DiagnosticStatus.SKIP,
                summary="Shared module-reported readiness is not available.",
                detail=(
                    "No suite-qualified public module-operations readiness contract "
                    "is available to doctor; module-private state is not inspected."
                ),
            ),
        )
    )


def collect_doctor_diagnostics(
    *,
    workspace: str | Path | None = None,
) -> DoctorReport:
    """Collect the complete diagnostic report supported by this suite release."""
    manifest = load_release_compatibility_manifest()
    return combine_reports(
        collect_runtime_package_diagnostics(manifest),
        collect_environment_dependency_diagnostics(manifest),
        collect_entry_point_core_diagnostics(manifest),
        collect_workspace_registry_diagnostics(manifest, workspace=workspace),
        collect_reduced_provider_diagnostics(manifest),
    )


def _report_sections(report: DoctorReport) -> tuple[str, ...]:
    present = {check.section for check in report.checks}
    known = tuple(section for section in _SECTION_ORDER if section in present)
    extras = tuple(sorted(present - set(_SECTION_ORDER)))
    return (*known, *extras)


def _overall_summary(report: DoctorReport) -> str:
    failures = report.failure_count
    warnings = report.warning_count
    if failures:
        blocker_label = "blocker" if failures == 1 else "blockers"
        warning_label = "warning" if warnings == 1 else "warnings"
        return f"FAIL  {failures} {blocker_label}, {warnings} {warning_label}."
    if warnings:
        warning_label = "warning" if warnings == 1 else "warnings"
        return f"WARN  No blockers; {warnings} {warning_label}."
    return "PASS  No blocking problems detected."


def render_doctor_report(report: DoctorReport) -> str:
    """Render one deterministic teacher-facing plain-text doctor report."""
    lines = ["Paper Data Suite doctor", ""]
    for section in _report_sections(report):
        lines.append(section)
        for check in report.for_section(section):
            lines.append(f"  {check.status.value:<4}  {check.summary}")
            if check.detail is not None:
                lines.append(f"        {check.detail}")
            if check.remediation is not None:
                lines.append(f"        Fix: {check.remediation}")
        lines.append("")
    lines.extend(("Overall", f"  {_overall_summary(report)}", ""))
    return "\n".join(lines)
