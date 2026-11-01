"""Issue #49 Slice 111: non-executable Windows administrator install phase plan.

The teacher process may inspect incomplete deployment obligations but cannot
authorize an administrator, provision directories, register services, initialize
witnesses, activate receipts or execute this plan. An independent privileged
installer must establish every proof from OS-owned state and authenticated
artifacts, not from this locally constructible review.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Final

from paper_data_suite.evergreen_windows_service_install_boundary import (
    ServiceInstallBoundaryError,
    ServiceInstallBoundaryReview,
    inspect_windows_service_install_boundary,
)

_SERVICE: Final = "PaperDataSuiteService"
_NO_AUTHORITY: Final = "NO_ADMIN_INSTALL_SERVICE_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY"
_PROOF_CODES: Final = (
    "INDEPENDENT_INSTALLER_IDENTITY",
    "CANONICAL_OS_DEPLOYMENT_PATHS",
    "SCM_SERVICE_OBJECT_DACL",
    "SERVICE_TOKEN_AND_SID",
    "EXECUTABLE_BYTES_AND_CUSTODY",
    "PROTECTED_RECEIPT_AND_CAS_HEAD",
    "TEACHER_NEGATIVE_SECURITY_TESTS",
)
_DIR_PURPOSES: Final = (
    "APPLICATION_BINARIES",
    "PROTECTED_STATE_ROOT",
    "ACTIVE_RECEIPTS",
    "SERVICE_TRANSACTION_STATE",
)

# Strict, ordered handoff. These are NOT shell commands or permission grants.
_PHASE_SPECS: Final = (
    (
        "ADMINISTRATOR_AUTHENTICATION_AND_CONSENT",
        "INDEPENDENT_ADMINISTRATOR",
        (),
        "Independent privileged actor, explicit consent, exact signed artifacts, "
        "dependency closure and recovery plan",
    ),
    (
        "PROTECTED_DIRECTORY_PROVISIONING",
        "INDEPENDENT_INSTALLER",
        ("ADMINISTRATOR_AUTHENTICATION_AND_CONSENT",),
        "OS-anchored roots, race-safe handles, protected DACLs, verified ownership "
        "and no ordinary-user write access",
    ),
    (
        "SERVICE_REGISTRATION_AND_SCM_CUSTODY",
        "INDEPENDENT_INSTALLER",
        ("PROTECTED_DIRECTORY_PROVISIONING",),
        "Dedicated service configuration with audited service-object DACL, "
        "controlled lifecycle and selected SID mode",
    ),
    (
        "EXECUTABLE_AND_EFFECTIVE_TOKEN_ATTESTATION",
        "INDEPENDENT_VALIDATOR",
        ("SERVICE_REGISTRATION_AND_SCM_CUSTODY",),
        "Authenticated installed executable bytes, service token, SID, privileges, "
        "file ownership, and impersonation checks",
    ),
    (
        "PROTECTED_HEAD_AND_RECOVERY_INITIALIZATION",
        "INDEPENDENT_SERVICE_OPERATOR",
        ("EXECUTABLE_AND_EFFECTIVE_TOKEN_ATTESTATION",),
        "Durable protected receipt/CAS head and journal, independently witnessed "
        "state and crash recovery evidence",
    ),
    (
        "NON_ADMINISTRATOR_NEGATIVE_ACCEPTANCE",
        "INDEPENDENT_VALIDATOR",
        ("PROTECTED_HEAD_AND_RECOVERY_INITIALIZATION",),
        "Teacher credentials cannot edit binaries, service configuration, "
        "active receipts, or service transaction state",
    ),
    (
        "INDEPENDENT_ACTIVATION_RELEASE_GATE",
        "INDEPENDENT_SERVICE_OPERATOR",
        ("NON_ADMINISTRATOR_NEGATIVE_ACCEPTANCE",),
        "Independently authenticated completion and rollback-safe activation; "
        "never accept this review as a grant",
    ),
)


class AdminInstallPlanError(ValueError):
    """Invalid diagnostics or impossible non-executable plan."""


@dataclass(frozen=True, slots=True)
class AdminInstallPhase:
    """Human/operator requirement, not an instruction to execute code."""

    ordinal: int
    code: str
    responsible_party: str
    requires_completed: tuple[str, ...]
    required_independent_evidence: str
    status: str = "INDEPENDENT_ADMINISTRATIVE_ACTION_PENDING"
    authorized_for_execution: bool = False


@dataclass(frozen=True, slots=True)
class AdminInstallPlanReview:
    """Deterministic planning view. It cannot carry a privileged approval."""

    status: str
    service_name: str
    directory_observation: str
    service_observation: str
    missing_directory_purposes: tuple[str, ...]
    blockers: tuple[str, ...]
    required_proof_codes: tuple[str, ...]
    phases: tuple[AdminInstallPhase, ...]
    authenticated_installer: bool = False
    authorized_to_create_directories: bool = False
    authorized_to_register_service: bool = False
    authorized_to_modify_receipts: bool = False
    authorized_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def prepare_admin_install_plan(
    boundary: ServiceInstallBoundaryReview,
) -> AdminInstallPlanReview:
    """Compile an immutable human handoff; never promote observed state.

    Even a valid input is locally forgeable. Real installers MUST ignore this
    return value for privileged authorization and reauthenticate OS evidence.
    """
    if type(boundary) is not ServiceInstallBoundaryReview:
        raise AdminInstallPlanError("invalid boundary observation type")
    if (
        type(boundary.production_authority) is not bool
        or boundary.production_authority
        or type(boundary.active_receipt_authority) is not bool
        or boundary.active_receipt_authority
        or type(boundary.service_identity_verified) is not bool
        or boundary.service_identity_verified
        or type(boundary.executable_integrity_verified) is not bool
        or boundary.executable_integrity_verified
        or type(boundary.protected_receipt_head_verified) is not bool
        or boundary.protected_receipt_head_verified
        or boundary.service_name != _SERVICE
        or boundary.authority
        != "NO_INSTALL_SERVICE_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY"
    ):
        raise AdminInstallPlanError(
            "boundary asserts identity or installation authority"
        )
    if (
        boundary.directory_observation
        not in (
            "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED",
            "PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        )
        or boundary.service_observation
        not in ("SERVICE_NOT_INSTALLED", "SERVICE_METADATA_OBSERVED_UNVERIFIED")
        or boundary.status
        not in (
            "PROTECTED_SERVICE_INSTALLATION_REQUIRED",
            "INSTALLED_METADATA_ONLY_SECURITY_PROOFS_REQUIRED",
        )
    ):
        raise AdminInstallPlanError("unrecognized deployment observation")
    purposes = boundary.missing_directory_purposes
    if (
        type(purposes) is not tuple
        or len(purposes) > len(_DIR_PURPOSES)
        or any(type(p) is not str or p not in _DIR_PURPOSES for p in purposes)
        or len(set(purposes)) != len(purposes)
        or tuple(p for p in _DIR_PURPOSES if p in purposes) != purposes
        or bool(purposes)
        != (
            boundary.directory_observation
            == "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED"
        )
    ):
        raise AdminInstallPlanError("directory purposes inconsistent with inventory")
    missing_service = boundary.service_observation == "SERVICE_NOT_INSTALLED"
    expected_blockers = (
        (("PROTECTED_DEPLOYMENT_DIRECTORIES_ABSENT",) if purposes else ())
        + (("INDEPENDENT_WINDOWS_SERVICE_NOT_INSTALLED",) if missing_service else ())
        + ("ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",)
    )
    if boundary.blockers != expected_blockers or boundary.status != (
        "PROTECTED_SERVICE_INSTALLATION_REQUIRED"
        if purposes or missing_service
        else "INSTALLED_METADATA_ONLY_SECURITY_PROOFS_REQUIRED"
    ):
        raise AdminInstallPlanError("deployment blockers and state disagree")
    proofs = boundary.independent_proofs
    if (
        type(proofs) is not tuple
        or len(proofs) != len(_PROOF_CODES)
        or tuple(proof.code for proof in proofs) != _PROOF_CODES
        or any(
            proof.status != "INDEPENDENT_PROOF_REQUIRED"
            or type(proof.responsible_party) is not str
            or not proof.responsible_party
            or type(proof.required_evidence) is not str
            or not proof.required_evidence
            for proof in proofs
        )
    ):
        raise AdminInstallPlanError("independent proof requirements inconsistent")
    phases = tuple(
        AdminInstallPhase(i, code, responsible, dependency, evidence)
        for i, (code, responsible, dependency, evidence) in enumerate(
            _PHASE_SPECS, start=1
        )
    )
    # Sequence is checked explicitly; dependencies cannot refer forward.
    seen: set[str] = set()
    for phase in phases:
        if phase.code in seen or not set(phase.requires_completed).issubset(seen):
            raise AdminInstallPlanError("invalid phase dependency order")
        seen.add(phase.code)
    return AdminInstallPlanReview(
        status=(
            "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED"
            if purposes or missing_service
            else "ADMINISTRATIVE_PROOFS_OUTSTANDING_METADATA_ONLY"
        ),
        service_name=_SERVICE,
        directory_observation=boundary.directory_observation,
        service_observation=boundary.service_observation,
        missing_directory_purposes=purposes,
        blockers=expected_blockers,
        required_proof_codes=_PROOF_CODES,
        phases=phases,
    )


def inspect_windows_admin_install_plan() -> AdminInstallPlanReview:
    """Read-only Windows diagnostics + fixed plan; no external operations."""
    if os.name != "nt":
        raise AdminInstallPlanError("Windows is required")
    try:
        boundary = inspect_windows_service_install_boundary()
    except ServiceInstallBoundaryError as error:
        raise AdminInstallPlanError("service install boundary unavailable") from error
    return prepare_admin_install_plan(boundary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        review = inspect_windows_admin_install_plan()
    except AdminInstallPlanError as error:
        print(f"REFUSED: {error}. {_NO_AUTHORITY}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(review), indent=2))
    print(_NO_AUTHORITY)
    return 2 if review.status == "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
