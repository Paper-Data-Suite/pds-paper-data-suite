"""Issue #49 Slice 109: observe a proposed Windows service identity, read-only.

Windows SCM metadata is untrusted diagnostic input. A recorded service name,
account, image path or running process never grants installation, protected
receipt, activation, or launch authority. This tool never creates, modifies,
starts or stops a Windows service and does not read classroom data.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Final, cast

# Fixed, PROVISIONAL service name. Not an installed credential or authority.
_SERVICE: Final = "PaperDataSuiteService"
_MAX_OUTPUT: Final = 16 * 1024
_NO_AUTHORITY: Final = "NO_SERVICE_INSTALL_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY"
_SCRIPT: Final = r"""
$ErrorActionPreference = 'Stop'
$found = @(Get-CimInstance -ClassName Win32_Service `
    -Filter "Name='PaperDataSuiteService'" -ErrorAction Stop)
if ($found.Count -eq 0) {
    '{"present":false}'
    return
}
if ($found.Count -ne 1) { throw 'ambiguous service result' }
$s = $found[0]
[ordered]@{
    present = $true
    name = [string]$s.Name
    start_name = [string]$s.StartName
    path_name = [string]$s.PathName
    state = [string]$s.State
    start_mode = [string]$s.StartMode
    process_id = [long]$s.ProcessId
} | ConvertTo-Json -Compress -Depth 3
"""


class ServiceIdentityPreflightError(ValueError):
    """SCM inventory failed or returned unacceptable diagnostic evidence."""


@dataclass(frozen=True, slots=True)
class ServiceIdentityObservation:
    """Sanitized service inventory only; NOT an authorization record."""

    status: str
    service_name: str = _SERVICE
    observed_state: str = "NOT_OBSERVED"
    observed_start_mode: str = "NOT_OBSERVED"
    account_category: str = "NOT_OBSERVED"
    registered_binary_path: str = "NOT_VERIFIED"
    service_sid_type: str = "NOT_VERIFIED"
    effective_token: str = "NOT_VERIFIED"
    service_dacl: str = "NOT_VERIFIED"
    executable_integrity: str = "NOT_VERIFIED"
    protected_receipt_head: str = "NOT_VERIFIED"
    production_authority: bool = False
    active_receipt_authority: bool = False
    authority: str = _NO_AUTHORITY


def _text(value: object, *, limit: int) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= limit
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ServiceIdentityPreflightError("malformed service metadata text")
    return value


def _account_category(value: str) -> str:
    if value in ("LocalSystem", "NT AUTHORITY\\SYSTEM"):
        return "SHARED_PRIVILEGED_ACCOUNT_OBSERVED"
    if value in ("LocalService", "NT AUTHORITY\\LocalService"):
        return "SHARED_LOCAL_SERVICE_ACCOUNT_OBSERVED"
    if value in ("NetworkService", "NT AUTHORITY\\NetworkService"):
        return "SHARED_NETWORK_SERVICE_ACCOUNT_OBSERVED"
    if value.casefold() == ("NT SERVICE\\" + _SERVICE).casefold():
        return "NAMED_VIRTUAL_SERVICE_ACCOUNT_OBSERVED"
    return "OTHER_ACCOUNT_UNVERIFIED"


def inspect_service_snapshot(value: object) -> ServiceIdentityObservation:
    """Validate a tightly bounded SCM snapshot without trusting its claims."""
    if not isinstance(value, dict) or type(value.get("present")) is not bool:
        raise ServiceIdentityPreflightError("invalid SCM inventory fields")
    if value["present"] is False:
        if set(value) != {"present"}:
            raise ServiceIdentityPreflightError("unexpected absent-service fields")
        return ServiceIdentityObservation(status="SERVICE_NOT_INSTALLED")
    required = {
        "present",
        "name",
        "start_name",
        "path_name",
        "state",
        "start_mode",
        "process_id",
    }
    if set(value) != required:
        raise ServiceIdentityPreflightError("unexpected SCM inventory fields")
    if _text(value["name"], limit=128) != _SERVICE:
        raise ServiceIdentityPreflightError("SCM service identity mismatch")
    account = _text(value["start_name"], limit=256)
    _text(value["path_name"], limit=2048)
    state = _text(value["state"], limit=32)
    start_mode = _text(value["start_mode"], limit=32)
    if state not in {
        "Stopped",
        "Running",
        "Paused",
        "Start Pending",
        "Stop Pending",
        "Continue Pending",
        "Pause Pending",
        "Unknown",
    }:
        raise ServiceIdentityPreflightError("unrecognized service state")
    if start_mode not in {"Auto", "Manual", "Disabled", "Boot", "System"}:
        raise ServiceIdentityPreflightError("unrecognized service start mode")
    pid = value["process_id"]
    if type(pid) is not int or not 0 <= pid <= 2**32 - 1:
        raise ServiceIdentityPreflightError("invalid SCM process ID")
    if (state == "Running" and pid == 0) or (state == "Stopped" and pid != 0):
        raise ServiceIdentityPreflightError("inconsistent SCM process state")
    return ServiceIdentityObservation(
        status="SERVICE_METADATA_OBSERVED_UNVERIFIED",
        observed_state=state.upper().replace(" ", "_") + "_OBSERVED",
        observed_start_mode=start_mode.upper() + "_OBSERVED",
        account_category=_account_category(account),
        registered_binary_path="REGISTERED_PATH_UNTRUSTED_NOT_DISCLOSED",
    )


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys; last-write-wins parsing is not acceptable."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ServiceIdentityPreflightError("duplicate SCM JSON field")
        result[key] = value
    return result


def _read_scm_snapshot() -> dict[str, object]:
    """Query one fixed Windows service; no caller-controlled script or name."""
    encoded = base64.b64encode(_SCRIPT.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceIdentityPreflightError(
            "Windows SCM inventory unavailable"
        ) from exc
    if (
        completed.returncode != 0
        or not completed.stdout.strip()
        or len(completed.stdout) > _MAX_OUTPUT
    ):
        raise ServiceIdentityPreflightError(
            "Windows SCM inventory failed or exceeded bounds"
        )
    try:
        snapshot: object = json.loads(
            completed.stdout.lstrip("\ufeff"), object_pairs_hook=_unique_fields
        )
    except ServiceIdentityPreflightError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise ServiceIdentityPreflightError("invalid SCM JSON") from exc
    if not isinstance(snapshot, dict):
        raise ServiceIdentityPreflightError("invalid SCM root object")
    return cast(dict[str, object], snapshot)


def audit_windows_service_identity() -> ServiceIdentityObservation:
    """Windows-only SCM observation; NEVER a service/installer trust gate."""
    if os.name != "nt":
        raise ServiceIdentityPreflightError("Windows is required")
    return inspect_service_snapshot(_read_scm_snapshot())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        observation = audit_windows_service_identity()
    except ServiceIdentityPreflightError as exc:
        print(f"REFUSED: {exc}. {_NO_AUTHORITY}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(observation), indent=2))
    print(_NO_AUTHORITY)
    # Zero only reports that one SCM record was observed, never trusted.
    return 2 if observation.status == "SERVICE_NOT_INSTALLED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
