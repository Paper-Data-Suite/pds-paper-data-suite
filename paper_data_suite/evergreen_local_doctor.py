"""Version-tolerant, read-only operational doctor for manually installed wheels.

The original exact-release doctor collectors remain available for historical
release acceptance. This collector reports active installed-wheel observations
without granting provenance, installation, or integration authority.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from importlib import import_module, metadata
from pathlib import Path

from paper_data_suite._version import __version__
from paper_data_suite.compatibility import (
    load_release_compatibility_manifest,
    release_compatibility_manifest_sha256,
)
from paper_data_suite.doctor import (
    _CORE_PUBLIC_CONTRACTS,
    DiagnosticCheck,
    DiagnosticStatus,
    DoctorReport,
    _default_command_runner,
    _environment_marker_check,
    _python_check,
    _python_dependency_check,
    collect_core_provider_diagnostics,
    collect_workspace_registry_diagnostics,
    combine_reports,
)
from paper_data_suite.evergreen_local_compatibility import (
    HistoricalEvidence,
    LocalCompatibilityReport,
    LocalInspectionError,
    Readiness,
    inspect_local_compatibility,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS


def collect_local_package_diagnostics(
    report: LocalCompatibilityReport,
) -> DoctorReport:
    """Project fixed-registry package assessments into truthful diagnostic rows."""
    checks: list[DiagnosticCheck] = []
    for approved in APPROVED_COMPONENTS:
        row = report.for_component(approved.component_id)
        if row is None or row.distribution != approved.distribution:
            raise LocalInspectionError("approved component assessment is missing")
        version = row.installed_version or "not installed"
        if row.readiness is Readiness.NOT_INSTALLED:
            checks.append(
                DiagnosticCheck(
                    section="Packages",
                    code=(
                        "package.required_missing" if approved.component_id == "core"
                        else "package.optional_missing"
                    ),
                    status=(
                        DiagnosticStatus.FAIL if approved.component_id == "core"
                        else DiagnosticStatus.SKIP
                    ),
                    component_id=approved.component_id,
                    summary=f"{approved.display_name} is not installed.",
                    remediation=(
                        "Install a compatible official wheel manually; "
                        "Suite does not install packages automatically."
                    ) if approved.component_id == "core" else None,
                )
            )
            continue
        if row.readiness is Readiness.INCOMPATIBLE:
            checks.append(
                DiagnosticCheck(
                    section="Packages",
                    code="package.incompatible",
                    status=DiagnosticStatus.FAIL,
                    component_id=approved.component_id,
                    summary=(
                        f"{approved.display_name} {version} is incompatible "
                        "with the active Python environment."
                    ),
                    detail="Reasons: " + ", ".join(row.reason_codes) + ".",
                    remediation=(
                        "Repair the dependency, Python, ownership, or package "
                        "metadata issue; do not silently downgrade packages."
                    ),
                )
            )
            continue
        checks.append(
            DiagnosticCheck(
                section="Packages",
                code="package.locally_compatible",
                status=DiagnosticStatus.PASS,
                component_id=approved.component_id,
                summary=(
                    f"{approved.display_name} {version}: installed metadata, "
                    "Python, Core range, and declared launcher contracts compatible."
                ),
            )
        )
        if row.historical_evidence is (
            HistoricalEvidence.NOT_PREVIOUSLY_INTEGRATION_TESTED
        ):
            checks.append(
                DiagnosticCheck(
                    section="Modules",
                    code="integration.not_previously_tested",
                    status=DiagnosticStatus.WARN,
                    component_id=approved.component_id,
                    summary=(
                        f"{approved.display_name} {version} is not in the exact "
                        "historically integration-tested composition."
                    ),
                    detail="Only individually supported integrations may be used.",
                )
            )
        checks.append(
            DiagnosticCheck(
                section="Packages",
                code="package.provenance_unverified",
                status=DiagnosticStatus.WARN,
                component_id=approved.component_id,
                summary=(
                    f"{approved.display_name} {version}: official wheel provenance "
                    "is unverified by local package metadata."
                ),
                detail=(
                    "A matching distribution name and dependencies are not "
                    "cryptographic authentication or installation receipts."
                ),
            )
        )
    return DoctorReport(tuple(checks))


def _suite_identity_check() -> DiagnosticCheck:
    try:
        installed_version = metadata.version("paper-data-suite")
    except metadata.PackageNotFoundError:
        return DiagnosticCheck(
            section="Suite", code="suite.not_installed",
            status=DiagnosticStatus.FAIL,
            summary="The running Suite has no installed distribution metadata.",
        )
    if installed_version != __version__:
        return DiagnosticCheck(
            section="Suite", code="suite.runtime_identity_mismatch",
            status=DiagnosticStatus.FAIL,
            summary=(
                f"Installed Suite {installed_version} does not match "
                f"the running package {__version__}."
            ),
        )
    return DiagnosticCheck(
        section="Suite", code="suite.running_version",
        status=DiagnosticStatus.PASS,
        summary=f"Running Suite {installed_version}; historical pins are archival.",
    )


def _core_public_contract_checks(
    *, module_importer: Callable[[str], object] = import_module,
) -> DoctorReport:
    checks: list[DiagnosticCheck] = []
    for module_name, name, purpose in _CORE_PUBLIC_CONTRACTS:
        try:
            module = module_importer(module_name)
            available = callable(getattr(module, name, None))
        except Exception:
            available = False
        checks.append(
            DiagnosticCheck(
                section="Core",
                code=(
                    "core.contract_available" if available
                    else "core.contract_missing"
                ),
                status=(
                    DiagnosticStatus.PASS if available else DiagnosticStatus.FAIL
                ),
                component_id="core",
                summary=(
                    f"Core {purpose} public contract "
                    + ("is available." if available else "is unavailable.")
                ),
                detail=f"Public callable: {module_name}.{name}.",
                remediation=(
                    None
                    if available
                    else "Install a Core wheel exposing the required public interface."
                ),
            )
        )
    return DoctorReport(tuple(checks))


def _external_command_checks(
    report: LocalCompatibilityReport,
    *, command_lookup: Callable[[str], str | None] = shutil.which,
) -> DoctorReport:
    """Report paper-rasterization capability without blocking unrelated launchers."""
    active_names: list[str] = []
    for name in ("scoreform", "quillan"):
        row = report.for_component(name)
        if row is not None and row.readiness is Readiness.COMPATIBLE:
            active_names.append(name)
    active = tuple(active_names)
    if not active or not sys.platform.startswith(("win", "linux")):
        return DoctorReport(())
    found = command_lookup("pdftoppm")
    return DoctorReport((
        DiagnosticCheck(
            section="External prerequisites",
            code=(
                "external.pdftoppm_available" if found
                else "external.pdftoppm_missing"
            ),
            status=DiagnosticStatus.PASS if found else DiagnosticStatus.WARN,
            summary=(
                "Poppler pdftoppm is available for PDF paper workflows."
                if found else "Poppler pdftoppm is missing for some paper workflows."
            ),
            detail="Consumers: " + ", ".join(active) + ".",
            remediation=(
                None
                if found
                else (
                    "Install/configure Poppler for paper workflows; launcher "
                    "eligibility is assessed separately."
                )
            ),
        ),
    ))


def collect_version_tolerant_doctor_diagnostics(
    *,
    workspace: str | Path | None = None,
    report: LocalCompatibilityReport | None = None,
) -> DoctorReport:
    """Inspect the ACTIVE environment; do not mutate packages or classroom data.

    Explicitly avoids historical release-tooling exact pins and does not treat
    stale historical environment markers as evidence of a bad manual install.
    """
    observed = report if report is not None else inspect_local_compatibility()
    manifest = load_release_compatibility_manifest()
    python = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    marker = _environment_marker_check(
        manifest,
        environment_root=Path(sys.prefix),
        manifest_digest_lookup=release_compatibility_manifest_sha256,
    )
    if marker.code == "suite.marker_mismatch":
        marker = DiagnosticCheck(
            section="Suite", code="suite.historical_marker_stale",
            status=DiagnosticStatus.WARN,
            summary=(
                "Historical environment marker differs from the installed "
                "composition; manual-wheel compatibility is checked separately."
            ),
            detail="Do not edit or replace the marker during diagnosis.",
        )
    core = observed.for_component("core")
    compatible_core = core is not None and core.readiness is Readiness.COMPATIBLE
    common = DoctorReport((
        _python_check(
            manifest, python_version=python, python_executable=sys.executable
        ),
        _suite_identity_check(),
        marker,
        _python_dependency_check(
            python_executable=sys.executable,
            command_runner=_default_command_runner,
            timeout_seconds=20.0,
        ),
    ))
    package_checks = collect_local_package_diagnostics(observed)
    if not compatible_core:
        return combine_reports(
            common, package_checks, _external_command_checks(observed),
            DoctorReport((DiagnosticCheck(
                section="Core", code="core.contracts_unavailable",
                status=DiagnosticStatus.SKIP,
                summary=(
                    "Core public contracts cannot be checked without "
                    "compatible Core."
                ),
            ),)),
        )
    return combine_reports(
        common, package_checks,
        _core_public_contract_checks(),
        _external_command_checks(observed),
        collect_workspace_registry_diagnostics(
            manifest, workspace=workspace, allow_compatible_core=True,
        ),
        collect_core_provider_diagnostics(
            manifest, allow_compatible_core=True,
        ),
    )
