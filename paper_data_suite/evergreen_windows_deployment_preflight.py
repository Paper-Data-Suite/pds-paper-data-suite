"""Issue #49 Slice 106: audit proposed Windows protected deployment roots.

Read-only, bounded, non-authorizing inspection of the intended Program Files
application directory and ProgramData service/receipt directories. Never
creates a directory, assigns an ACL, installs code, or issues a launch permit.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_windows_custody import (
    CustodyAuditError,
    _powershell_acl,
    _trusted,
    inspect_acl_document,
)

_APP_NAME: Final = "Paper Data Suite"
_STATE_CHILDREN: Final = ("active-receipts", "service-state")
_MAX_ACES: Final = 128
# The default ProgramData DACL may allow ordinary users to create entries
# and change attributes/extended attributes on ProgramData itself. Those rights
# do not grant mutation of an existing independently protected PDS child.
# Refuse delete/replace and security-descriptor authority on the parent;
# inspect every existing PDS-owned child separately with the STRICT policy.
_PARENT_DANGER: Final = (
    0x40  # DELETE_CHILD
    | 0x10000  # DELETE
    | 0x40000  # WRITE_DAC
    | 0x80000  # WRITE_OWNER
    | 0x10000000  # GENERIC_ALL
    | 0x40000000  # GENERIC_WRITE
)


class DeploymentPreflightError(ValueError):
    """A proposed deployment path or its security evidence was rejected."""


@dataclass(frozen=True, slots=True)
class DeploymentPreflight:
    """Path observations only; NEVER evidence of installation or service authority."""

    status: str
    checked_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    production_authority: bool = False
    active_receipt_authority: bool = False


def inspect_state_parent_acl(value: object) -> None:
    """Reject untrusted ability to replace or alter the ProgramData parent.

    Creation of unrelated files/child directories is not sufficient to
    modify an *existing* protected child. The named child MUST be inspected
    separately and must reject every untrusted write grant.
    """
    if not isinstance(value, dict) or set(value) != {"owner", "rules"}:
        raise CustodyAuditError("invalid state-parent ACL fields")
    owner = value["owner"]
    rules = value["rules"]
    if type(owner) is not str or not _trusted(owner):
        raise CustodyAuditError("state-parent owner is not privileged")
    if type(rules) is not list or not 1 <= len(rules) <= _MAX_ACES:
        raise CustodyAuditError("invalid state-parent DACL count")
    safe_rows: list[dict[str, object]] = []
    for row in rules:
        if not isinstance(row, dict) or set(row) != {
            "sid",
            "type",
            "rights",
            "inherited",
            "inherit_only",
        }:
            raise CustodyAuditError("invalid state-parent ACL entry")
        rights = row["rights"]
        if type(rights) is not int or not -(2**31) <= rights <= 2**32 - 1:
            raise CustodyAuditError("invalid state-parent rights mask")
        # Delegate all SID, type, inheritance, and owner validation to the
        # previously qualified strict ACL parser. Retain only parent-danger
        # bits for ordinary principals; do not alter the reported evidence.
        safe_rows.append({**row, "rights": (rights & 0xFFFFFFFF) & _PARENT_DANGER})
    inspect_acl_document({"owner": owner, "rules": safe_rows})


def _safe_directory(path: Path) -> bool:
    """Return False for missing paths; refuse links, reparse points and files."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DeploymentPreflightError("directory cannot be inspected") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise DeploymentPreflightError("directory is unsafe or not a directory")
    return True


def inspect_proposed_deployment(
    program_files: Path,
    program_data: Path,
    *,
    read_acl: Callable[[Path], object],
) -> DeploymentPreflight:
    """Inspect exact prospective roots; injection is only for isolated tests.

    The real CLI calls this with Windows' ACL reader. No checked or missing
    path is treated as a trust root: a service must separately own lifecycle,
    privileges, and durable activation/receipt state.
    """
    if (
        not isinstance(program_files, Path)
        or not isinstance(program_data, Path)
        or not callable(read_acl)
    ):
        raise DeploymentPreflightError("invalid deployment preflight inputs")
    if program_files == program_data or program_files in program_data.parents:
        raise DeploymentPreflightError("application and state roots overlap")
    if program_data in program_files.parents:
        raise DeploymentPreflightError("application and state roots overlap")

    for base in (program_files, program_data):
        if not _safe_directory(base):
            raise DeploymentPreflightError("Windows installation base is missing")

    app = program_files / _APP_NAME
    state = program_data / _APP_NAME
    required = (
        (program_files, "strict"),
        (app, "strict"),
        (program_data, "parent"),
        (state, "strict"),
        *((state / child, "strict") for child in _STATE_CHILDREN),
    )
    checked: list[str] = []
    missing: list[str] = []
    for path, policy in required:
        if not _safe_directory(path):
            missing.append(str(path))
            continue
        try:
            document = read_acl(path)
            if policy == "parent":
                inspect_state_parent_acl(document)
            else:
                inspect_acl_document(document)
        except (CustodyAuditError, OSError, ValueError, TypeError) as exc:
            raise DeploymentPreflightError(
                f"ACL custody refused at {path.name}: {exc}"
            ) from exc
        checked.append(str(path))
    return DeploymentPreflight(
        status=(
            "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED"
            if missing
            else "PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY"
        ),
        checked_paths=tuple(checked),
        missing_paths=tuple(missing),
    )


def audit_windows_deployment_preflight() -> DeploymentPreflight:
    """Inspect fixed intended OS locations, without touching their contents."""
    if os.name != "nt":
        raise DeploymentPreflightError("Windows is required")
    program_files = os.environ.get("ProgramFiles")
    program_data = os.environ.get("ProgramData")
    if not program_files or not program_data:
        raise DeploymentPreflightError("Windows installation roots unavailable")
    base_app = Path(program_files).absolute()
    base_state = Path(program_data).absolute()
    return inspect_proposed_deployment(base_app, base_state, read_acl=_powershell_acl)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args(argv)
    del args
    try:
        observation = audit_windows_deployment_preflight()
    except DeploymentPreflightError as exc:
        print(
            f"REFUSED: {exc}. NO_PRODUCTION_INSTALL_OR_RECEIPT_AUTHORITY",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": observation.status,
                "checked_paths": observation.checked_paths,
                "missing_paths": observation.missing_paths,
                "production_authority": observation.production_authority,
                "active_receipt_authority": observation.active_receipt_authority,
            },
            indent=2,
        )
    )
    if observation.missing_paths:
        print("PROVISIONING_REQUIRED_NO_FILESYSTEM_WRITES")
        return 2
    print("DIRECTORY_ACLS_OBSERVED_ONLY_NO_SERVICE_OR_LAUNCH_AUTHORITY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
