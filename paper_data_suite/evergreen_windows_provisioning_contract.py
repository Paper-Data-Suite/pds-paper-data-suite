"""Issue #49 Slice 108: read-only protected Windows provisioning contract.

Turns the Slice 106-107 directory ACL observation into a bounded administrator
handoff/checklist. This module never provisions a directory, modifies an ACL,
selects a service account, installs software, or establishes any authority.
Environment variables and caller-provided paths are only diagnostic inputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_windows_custody import _powershell_acl
from paper_data_suite.evergreen_windows_deployment_preflight import (
    DeploymentPreflightError,
    inspect_proposed_deployment,
)

_APP: Final = "Paper Data Suite"
_TRUSTED_OWNER_SIDS: Final = (
    "S-1-5-18",  # LocalSystem
    "S-1-5-32-544",  # Builtin Administrators
    # TrustedInstaller
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
)
_NO_AUTHORITY: Final = "NO_INSTALL_SERVICE_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY"


@dataclass(frozen=True, slots=True)
class ProvisioningRequirement:
    """A proposed child, not an instruction or permission to create it."""

    directory: str
    purpose: str
    permitted_owner_sids: tuple[str, ...] = _TRUSTED_OWNER_SIDS
    ordinary_user_write_allowed: bool = False
    authorized_for_creation: bool = False


@dataclass(frozen=True, slots=True)
class ProvisioningReview:
    """Immutable read-only handoff; never itself trust or installation proof."""

    status: str
    required_directories: tuple[ProvisioningRequirement, ...]
    checked_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    service_identity: str = "INDEPENDENT_SERVICE_IDENTITY_NOT_ESTABLISHED"
    executable_integrity: str = "NOT_VERIFIED"
    protected_receipt_head: str = "NOT_VERIFIED"
    production_authority: bool = False
    active_receipt_authority: bool = False
    authority: str = _NO_AUTHORITY


def review_windows_provisioning(
    program_files: Path,
    program_data: Path,
    *,
    read_acl: object,
) -> ProvisioningReview:
    """Read/check proposed locations only, using existing strict ACL policy.

    The result is a human review contract; it MUST NOT be consumed as an
    authorization token by an installer, Windows service, or launcher.
    """
    if not callable(read_acl):
        raise DeploymentPreflightError("ACL reader unavailable")
    observation = inspect_proposed_deployment(
        program_files, program_data, read_acl=read_acl
    )
    app = program_files / _APP
    state = program_data / _APP
    requirements = (
        ProvisioningRequirement(str(app), "APPLICATION_BINARIES"),
        ProvisioningRequirement(str(state), "PROTECTED_STATE_ROOT"),
        ProvisioningRequirement(str(state / "active-receipts"), "ACTIVE_RECEIPTS"),
        ProvisioningRequirement(
            str(state / "service-state"), "SERVICE_TRANSACTION_STATE"
        ),
    )
    # The preflight independently checks OS roots and all existing named
    # children. Its statuses are informational, never privilege grants.
    return ProvisioningReview(
        status=observation.status,
        required_directories=requirements,
        checked_paths=observation.checked_paths,
        missing_paths=observation.missing_paths,
    )


def inspect_windows_provisioning() -> ProvisioningReview:
    """Review the current machine without creating directories or changing ACLs."""
    if os.name != "nt":
        raise DeploymentPreflightError("Windows is required")
    program_files = os.environ.get("ProgramFiles")
    program_data = os.environ.get("ProgramData")
    if not program_files or not program_data:
        raise DeploymentPreflightError("Windows installation roots unavailable")
    return review_windows_provisioning(
        Path(program_files).absolute(),
        Path(program_data).absolute(),
        read_acl=_powershell_acl,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args(argv)
    del args
    try:
        result = inspect_windows_provisioning()
    except DeploymentPreflightError as exc:
        print(f"REFUSED: {exc}. {_NO_AUTHORITY}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), indent=2))
    print(_NO_AUTHORITY)
    # 0 says only that directory-level ACLs were observed, never that the
    # independently administered service or an installed release is safe.
    return 2 if result.missing_paths else 0


if __name__ == "__main__":
    raise SystemExit(main())
