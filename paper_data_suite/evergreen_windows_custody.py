"""Issue #49 Slice 104: Windows protected-install ACL custody *audit*.

Read-only diagnostic. Inspect each real filesystem component from the OS
Program Files root through a proposed installation directory or executable.
A permissive DACL, unsafe owner, reparse point, or unknown write grant refuses.
Passing does NOT establish a protected service, receipt, binary provenance,
full access-token effective rights, or launch authority.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

# These FileSystemRights bits are sufficient for conservative refusal of
# untrusted modification. Deny entries never cancel an observed allow here.
_GENERIC_WRITE: Final = 0x10000000 | 0x40000000
_WRITE: Final = (
    0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | _GENERIC_WRITE
)
_SYSTEM: Final = "S-1-5-18"
_ADMINISTRATORS: Final = "S-1-5-32-544"
_MAX_DEPTH: Final = 16
_MAX_OUTPUT: Final = 128 * 1024
_SCRIPT: Final = r"""
$ErrorActionPreference = 'Stop'
$p = $env:PDS_CUSTODY_INSPECT_PATH
if ([string]::IsNullOrWhiteSpace($p)) { throw 'missing audit target' }
$a = Get-Acl -LiteralPath $p -ErrorAction Stop
$owner = $a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
$sidType = [System.Security.Principal.SecurityIdentifier]
$inheritOnlyFlag = [System.Security.AccessControl.PropagationFlags]::InheritOnly
$rules = @(
    foreach ($r in $a.GetAccessRules($true, $true, $sidType)) {
        [ordered]@{
            sid = $r.IdentityReference.Value
            type = $r.AccessControlType.ToString()
            rights = [long]$r.FileSystemRights
            inherited = [bool]$r.IsInherited
            inherit_only = [bool]($r.PropagationFlags -band $inheritOnlyFlag)
        }
    }
)
[ordered]@{
    owner = $owner
    rules = $rules
} | ConvertTo-Json -Compress -Depth 5
"""


class CustodyAuditError(ValueError):
    """Windows custody cannot be established by this read-only audit."""


@dataclass(frozen=True, slots=True)
class CustodyAuditObservation:
    checked_paths: tuple[str, ...]
    status: str = "WINDOWS_PROTECTED_PATH_ACL_OBSERVED_ONLY"
    production_authority: bool = False


def _trusted(sid: str) -> bool:
    # Service SIDs are not universally trusted. Only the canonical
    # TrustedInstaller SID is acceptable, not an arbitrary service principal.
    return sid in {_SYSTEM, _ADMINISTRATORS, _TRUSTED_INSTALLER}


_TRUSTED_INSTALLER: Final = (
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
)


def inspect_acl_document(value: object) -> None:
    """Conservatively refuse unsafe owner/DACL, including inherited grants."""
    if not isinstance(value, dict) or set(value) != {"owner", "rules"}:
        raise CustodyAuditError("ACL inspection document has unexpected fields")
    owner, rules = value["owner"], value["rules"]
    if type(owner) is not str or not _trusted(owner):
        raise CustodyAuditError(
            "path owner is not SYSTEM, Administrators, or TrustedInstaller"
        )
    if type(rules) is not list or len(rules) > 128 or not rules:
        raise CustodyAuditError("missing or excessive DACL entries")
    for row in rules:
        if not isinstance(row, dict) or set(row) != {
            "sid",
            "type",
            "rights",
            "inherited",
            "inherit_only",
        }:
            raise CustodyAuditError("malformed DACL entry")
        sid = row["sid"]
        kind = row["type"]
        rights = row["rights"]
        inherited = row["inherited"]
        inherit_only = row["inherit_only"]
        if (
            type(sid) is not str
            or not sid.startswith("S-1-")
            or kind not in ("Allow", "Deny")
            or type(rights) is not int
            or rights < -(2**31)
            or rights > 2**32 - 1
            or type(inherited) is not bool
            or type(inherit_only) is not bool
        ):
            raise CustodyAuditError("invalid DACL identity or rights")
        if (
            kind == "Allow"
            and not inherit_only
            and not _trusted(sid)
            and (rights & 0xFFFFFFFF) & _WRITE
        ):
            raise CustodyAuditError(
                "non-administrator principal has DACL write authority"
            )


def _reparse_free(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise CustodyAuditError("path component does not exist") from error
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise CustodyAuditError("path contains a symlink or Windows reparse point")
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise CustodyAuditError("path component is neither directory nor regular file")


def _powershell_acl(path: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PDS_CUSTODY_INSPECT_PATH"] = str(path)
    encoded = base64.b64encode(_SCRIPT.encode("utf-16le")).decode("ascii")
    try:
        output = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            check=False,
            text=True,
            capture_output=True,
            timeout=15,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CustodyAuditError("Windows ACL API query unavailable") from error
    if (
        output.returncode
        or len(output.stdout) > _MAX_OUTPUT
        or not output.stdout.strip()
    ):
        raise CustodyAuditError("Windows ACL API query failed or exceeded bounds")
    try:
        data: object = json.loads(output.stdout.lstrip("\ufeff"))
    except (ValueError, UnicodeError) as error:
        raise CustodyAuditError("Windows ACL API returned invalid data") from error
    if not isinstance(data, dict):
        raise CustodyAuditError("Windows ACL API did not return a document")
    return cast(dict[str, object], data)


def audit_windows_install_path(path: Path) -> CustodyAuditObservation:
    """Inspect actual Windows owner and DACL for every existing path segment."""
    if os.name != "nt":
        raise CustodyAuditError("Windows is required")
    program_files = os.environ.get("ProgramFiles")
    if not program_files:
        raise CustodyAuditError("Windows ProgramFiles location unavailable")
    base = Path(program_files).absolute()
    target = path.expanduser().absolute()
    try:
        parts = target.relative_to(base).parts
    except ValueError as error:
        raise CustodyAuditError(
            "protected install must reside under OS Program Files"
        ) from error
    if len(parts) > _MAX_DEPTH:
        raise CustodyAuditError("installation directory nesting exceeds limit")
    checked: list[str] = []
    current = base
    for segment in (None, *parts):
        if segment is not None:
            current = current / segment
        _reparse_free(current)
        inspect_acl_document(_powershell_acl(current))
        checked.append(str(current))
    if not current.is_dir() and current != target:
        raise CustodyAuditError("non-directory component in protected install path")
    return CustodyAuditObservation(tuple(checked))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit_windows_install_path(args.path)
    except CustodyAuditError as error:
        print(
            f"REFUSED: {error}. NO_PRODUCTION_INSTALL_CUSTODY_ESTABLISHED",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "status": result.status,
                "checked_paths": result.checked_paths,
                "production_authority": result.production_authority,
            },
            indent=2,
        )
    )
    print("WINDOWS_INSTALL_ACL_AUDIT_PASSED_READ_ONLY_NO_LAUNCH_AUTHORITY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
