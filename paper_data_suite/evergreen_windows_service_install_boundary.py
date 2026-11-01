"""Issue #49 Slice 110: reconcile protected installer/service proof obligations.

Observational only. Neither an ACL audit nor SCM metadata is an authorization
credential. This module does not provision a service or directory, elevate,
accept approval assertions, access active receipts, or execute a launcher.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Final

from paper_data_suite.evergreen_windows_deployment_preflight import (
    DeploymentPreflightError,
)
from paper_data_suite.evergreen_windows_provisioning_contract import (
    ProvisioningRequirement,
    ProvisioningReview,
    inspect_windows_provisioning,
)
from paper_data_suite.evergreen_windows_service_identity_preflight import (
    ServiceIdentityObservation,
    ServiceIdentityPreflightError,
    audit_windows_service_identity,
)

_SERVICE: Final = "PaperDataSuiteService"
_DIR_PURPOSES: Final = (
    "APPLICATION_BINARIES",
    "PROTECTED_STATE_ROOT",
    "ACTIVE_RECEIPTS",
    "SERVICE_TRANSACTION_STATE",
)
_NO_AUTHORITY: Final = "NO_INSTALL_SERVICE_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY"
_OBLIGATIONS: Final = (
    (
        "INDEPENDENT_INSTALLER_IDENTITY",
        "ADMINISTRATOR",
        "Privileged installer identity, explicit consent, and "
        "authenticated artifact policy",
    ),
    (
        "CANONICAL_OS_DEPLOYMENT_PATHS",
        "ADMINISTRATOR",
        "OS-anchored canonical roots, race-safe access, "
        "and protected parent/child ACLs",
    ),
    (
        "SCM_SERVICE_OBJECT_DACL",
        "ADMINISTRATOR",
        "Effective SCM permissions prohibit ordinary-user configuration, "
        "deletion, and security changes",
    ),
    (
        "SERVICE_TOKEN_AND_SID",
        "SERVICE_OPERATOR",
        "Service SID type, process token, privileges, account isolation, "
        "and impersonation resistance",
    ),
    (
        "EXECUTABLE_BYTES_AND_CUSTODY",
        "INSTALLER",
        "Verified executable provenance, installed-file identity, "
        "file DACL, and immutable handoff",
    ),
    (
        "PROTECTED_RECEIPT_AND_CAS_HEAD",
        "SERVICE_OPERATOR",
        "Independent receipt head, durable journal, witness/CAS "
        "continuity, and crash recovery",
    ),
    (
        "TEACHER_NEGATIVE_SECURITY_TESTS",
        "INDEPENDENT_VALIDATOR",
        "Non-administrator cannot replace executable, change service, "
        "write receipts, or impersonate service",
    ),
)


class ServiceInstallBoundaryError(ValueError):
    """Untrusted observation, incomplete proof, or invalid review contract."""


@dataclass(frozen=True, slots=True)
class IndependentProofObligation:
    """Human-admin obligation; never caller-provided authorization evidence."""

    code: str
    responsible_party: str
    required_evidence: str
    status: str = "INDEPENDENT_PROOF_REQUIRED"


@dataclass(frozen=True, slots=True)
class ServiceInstallBoundaryReview:
    """Read-only reconciliation. Every possible result is non-authorizing."""

    status: str
    service_name: str
    directory_observation: str
    service_observation: str
    missing_directory_purposes: tuple[str, ...]
    blockers: tuple[str, ...]
    independent_proofs: tuple[IndependentProofObligation, ...]
    service_identity_verified: bool = False
    executable_integrity_verified: bool = False
    protected_receipt_head_verified: bool = False
    production_authority: bool = False
    active_receipt_authority: bool = False
    authority: str = _NO_AUTHORITY


def reconcile_service_install_boundary(
    provisioning: ProvisioningReview, service: ServiceIdentityObservation
) -> ServiceInstallBoundaryReview:
    """Fail closed on malformed data; never promote observations to trust.

    Arguments MUST be observations from separate diagnostics. Even correct
    dataclass instances can be forged by local software, so no successful
    result may be used as installer, service, or activation authorization.
    """
    if type(provisioning) is not ProvisioningReview:
        raise ServiceInstallBoundaryError("invalid directory observation type")
    if type(service) is not ServiceIdentityObservation:
        raise ServiceInstallBoundaryError("invalid service observation type")
    if (
        type(provisioning.production_authority) is not bool
        or provisioning.production_authority
        or type(provisioning.active_receipt_authority) is not bool
        or provisioning.active_receipt_authority
        or provisioning.authority != _NO_AUTHORITY
        or provisioning.service_identity
        != "INDEPENDENT_SERVICE_IDENTITY_NOT_ESTABLISHED"
        or provisioning.executable_integrity != "NOT_VERIFIED"
        or provisioning.protected_receipt_head != "NOT_VERIFIED"
        or provisioning.status
        not in (
            "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED",
            "PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        )
    ):
        raise ServiceInstallBoundaryError("directory review asserts unearned authority")
    requirements = provisioning.required_directories
    if (
        len(requirements) != len(_DIR_PURPOSES)
        or tuple(req.purpose for req in requirements) != _DIR_PURPOSES
        or any(
            type(req) is not ProvisioningRequirement
            or type(req.directory) is not str
            or not req.directory
            or type(req.ordinary_user_write_allowed) is not bool
            or req.ordinary_user_write_allowed
            or type(req.authorized_for_creation) is not bool
            or req.authorized_for_creation
            for req in requirements
        )
    ):
        raise ServiceInstallBoundaryError("invalid protected directory contract")
    directory_names = tuple(req.directory for req in requirements)
    if len(set(directory_names)) != len(directory_names):
        raise ServiceInstallBoundaryError("duplicate directory contract entry")
    missing = provisioning.missing_paths
    if (
        type(missing) is not tuple
        or any(type(path) is not str for path in missing)
        or len(set(missing)) != len(missing)
        or not set(missing).issubset(set(directory_names))
        or bool(missing)
        != (provisioning.status == "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED")
    ):
        raise ServiceInstallBoundaryError("directory observation disagrees with paths")
    if (
        type(service.production_authority) is not bool
        or service.production_authority
        or type(service.active_receipt_authority) is not bool
        or service.active_receipt_authority
        or service.service_name != _SERVICE
        or service.authority
        != "NO_SERVICE_INSTALL_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY"
        or service.status
        not in ("SERVICE_NOT_INSTALLED", "SERVICE_METADATA_OBSERVED_UNVERIFIED")
        or service.service_sid_type != "NOT_VERIFIED"
        or service.effective_token != "NOT_VERIFIED"
        or service.service_dacl != "NOT_VERIFIED"
        or service.executable_integrity != "NOT_VERIFIED"
        or service.protected_receipt_head != "NOT_VERIFIED"
    ):
        raise ServiceInstallBoundaryError("service review asserts unearned authority")
    if service.status == "SERVICE_NOT_INSTALLED" and (
        service.observed_state != "NOT_OBSERVED"
        or service.account_category != "NOT_OBSERVED"
        or service.registered_binary_path != "NOT_VERIFIED"
    ):
        raise ServiceInstallBoundaryError("absent service has contradictory metadata")

    missing_purposes = tuple(
        req.purpose for req in requirements if req.directory in missing
    )
    blockers = []
    if missing:
        blockers.append("PROTECTED_DEPLOYMENT_DIRECTORIES_ABSENT")
    if service.status == "SERVICE_NOT_INSTALLED":
        blockers.append("INDEPENDENT_WINDOWS_SERVICE_NOT_INSTALLED")
    blockers.append("ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING")
    status = (
        "PROTECTED_SERVICE_INSTALLATION_REQUIRED"
        if missing or service.status == "SERVICE_NOT_INSTALLED"
        else "INSTALLED_METADATA_ONLY_SECURITY_PROOFS_REQUIRED"
    )
    return ServiceInstallBoundaryReview(
        status=status,
        service_name=_SERVICE,
        directory_observation=provisioning.status,
        service_observation=service.status,
        missing_directory_purposes=missing_purposes,
        blockers=tuple(blockers),
        independent_proofs=tuple(
            IndependentProofObligation(*item) for item in _OBLIGATIONS
        ),
    )


def inspect_windows_service_install_boundary() -> ServiceInstallBoundaryReview:
    """Use two existing read-only Windows observers, without authority."""
    if os.name != "nt":
        raise ServiceInstallBoundaryError("Windows is required")
    try:
        directories = inspect_windows_provisioning()
        service = audit_windows_service_identity()
    except (DeploymentPreflightError, ServiceIdentityPreflightError) as error:
        raise ServiceInstallBoundaryError(
            "Windows security observation unavailable"
        ) from error
    return reconcile_service_install_boundary(directories, service)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        review = inspect_windows_service_install_boundary()
    except ServiceInstallBoundaryError as error:
        print(f"REFUSED: {error}. {_NO_AUTHORITY}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(review), indent=2))
    print(_NO_AUTHORITY)
    # Exit 0 means only observations exist, not that the service is usable.
    return 2 if review.status == "PROTECTED_SERVICE_INSTALLATION_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
