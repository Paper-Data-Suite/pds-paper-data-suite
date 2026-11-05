"""Project approved local compatibility into Suite's existing launcher interface.

Normal `pds modules`/`pds launch` use this read-only metadata observation.
No signed catalog, student workspace, package installer or provider import is
accessed here. The result is LOCAL launch eligibility, not wheel provenance or
cross-module integration certification.
"""

from __future__ import annotations

from dataclasses import replace

from paper_data_suite.application_launching import (
    LauncherResolver,
    resolve_application_launchers,
    resolve_current_environment_launcher,
)
from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
    ApplicationObservation,
)
from paper_data_suite.evergreen_local_compatibility import (
    HistoricalEvidence,
    LocalCompatibilityReport,
    LocalInspectionError,
    Readiness,
    inspect_local_compatibility,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS

_PURPOSES = {
    "scoreform": "Printable answer sheets and OMR scoring.",
    "quillan": "Standards-based writing evidence capture and review.",
    "concord": "Paper-first collaborative classroom workflows.",
    "meridian": "Gradebook and evidence-informed reporting.",
    "vitrine": "Portfolio curation and snapshot review.",
    "portia": "Teacher-controlled student support records.",
}


def collect_local_launch_inventory(
    *,
    report: LocalCompatibilityReport | None = None,
    launcher_resolver: LauncherResolver = resolve_current_environment_launcher,
) -> ApplicationInventory:
    """Check only registered module launchers in the active interpreter.

    An observed compatible module may be launched without its v0.1.0 manifest
    version, but this DOES NOT establish that its wheel is an official release.
    Any unqualified routing/publication/provider integration remains separately
    gated by its owning public contract.
    """
    observed = report if report is not None else inspect_local_compatibility()
    rows: list[ApplicationObservation] = []
    for approved in APPROVED_COMPONENTS:
        if not approved.launchable:
            continue
        if len(approved.console_scripts) != 1:
            raise LocalInspectionError(
                "registered application console boundary invalid"
            )
        assessment = observed.for_component(approved.component_id)
        if assessment is None or assessment.component_id != approved.component_id:
            raise LocalInspectionError("missing approved application observation")
        if assessment.distribution != approved.distribution:
            raise LocalInspectionError("approved application distribution mismatch")
        if assessment.readiness is Readiness.COMPATIBLE:
            status = ApplicationLaunchStatus.AVAILABLE
            remediation = None
        elif assessment.readiness is Readiness.NOT_INSTALLED:
            status = ApplicationLaunchStatus.NOT_INSTALLED
            remediation = "Install an official module wheel into this environment."
        else:
            status = ApplicationLaunchStatus.INCOMPATIBLE
            remediation = (
                "Repair the listed dependency, metadata, or entry-point problem "
                "in this Python environment; do not downgrade automatically."
            )
        historic = (
            "historical version matches; exact integration not established"
            if assessment.historical_evidence
            is HistoricalEvidence.HISTORICAL_VERSION_MATCH
            else "not previously integration-tested in the historical manifest"
        )
        reason = (
            "; ".join(assessment.reason_codes)
            + f"; {historic}; wheel provenance unverified"
        )
        console = approved.console_scripts[0]
        rows.append(
            ApplicationObservation(
                component_id=approved.component_id,
                display_name=approved.display_name,
                purpose=_PURPOSES[approved.component_id],
                distribution=approved.distribution,
                qualified_version=approved.historical_version or "not listed",
                installed_version=assessment.installed_version,
                console_script_name=console.name,
                console_script_target=console.target,
                status=status,
                reason=reason,
                remediation=remediation,
            )
        )

    resolved = resolve_application_launchers(
        ApplicationInventory(tuple(rows)), launcher_resolver=launcher_resolver
    )
    amended: list[ApplicationObservation] = []
    for row in resolved.applications:
        if row.status is ApplicationLaunchStatus.AVAILABLE:
            version = row.installed_version or "unknown"
            amended.append(
                replace(
                    row,
                    reason=(
                        f"{row.display_name} {version}: local dependencies, "
                        "console ownership and current-environment launcher "
                        "satisfied; wheel provenance unverified; "
                        "integration qualification is separate"
                    ),
                )
            )
        elif row.status is ApplicationLaunchStatus.UNAVAILABLE:
            amended.append(
                replace(
                    row,
                    reason=(
                        "Local metadata checks passed, but the approved "
                        f"launcher could not be resolved: {row.reason}"
                    ),
                )
            )
        else:
            amended.append(row)
    return ApplicationInventory(tuple(amended))
