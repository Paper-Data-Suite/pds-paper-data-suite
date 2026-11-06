"""Issue #49 Slice 135: fail-closed installed-machine negative acceptance rehearsal.

This program only launches existing diagnostic executables supplied in one
explicit build directory. Neither the executables nor their output constitute
independent proof of installed-service identity or privileged authorization.
Even complete observations return exit 2 (UNATTESTED), never exit 0.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)
_MAX_STDOUT: Final = 8192
_TIMEOUT_SECONDS: Final = 12

# Fixed names: caller may select only the explicit build directory, not an
# executable, argument, alternate service, claim file, or account identity.
_PROBES: Final = (
    ("teacher", "pds_windows_teacher_denial_probe.exe"),
    ("service_access", "pds_windows_service_access_probe.exe"),
    ("service_security", "pds_windows_service_scm_probe.exe"),
    ("service_image", "pds_windows_service_image_probe.exe"),
    ("publisher_pin", "pds_windows_publisher_pin_custody_probe.exe"),
)


class RehearsalRefused(ValueError):
    """Evidence is absent, inconsistent, forged or insufficient for rehearsal."""


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    status: str
    exit_code: int
    fields: Mapping[str, object]


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found: dict[str, object] = {}
    for name, value in pairs:
        if name in found:
            raise RehearsalRefused("duplicate native JSON property")
        found[name] = value
    return found


def parse_native_output(name: str, exit_code: int, output: bytes) -> ProbeObservation:
    """Reject oversized, duplicate-key, noncanonical or authorizing output."""
    if name not in dict(_PROBES) or exit_code not in (1, 2):
        raise RehearsalRefused("unrecognized native probe or exit status")
    if not 1 <= len(output) <= _MAX_STDOUT or b"\x00" in output:
        raise RehearsalRefused("native output missing or outside bounds")
    try:
        decoded = output.decode("utf-8", errors="strict")
        if decoded.startswith("\ufeff"):
            raise RehearsalRefused("noncanonical native output encoding")
        # MSVC stdout is usually CRLF; accept uniform CRLF or LF only.
        if "\r\n" in decoded:
            if decoded.count("\n") != decoded.count("\r\n"):
                raise RehearsalRefused("mixed native output line endings")
            decoded = decoded.replace("\r\n", "\n")
        if "\r" in decoded:
            raise RehearsalRefused("unpaired native output carriage return")
        lines = decoded.splitlines()
        if len(lines) != 2 or decoded[-1] != "\n":
            raise RehearsalRefused("native probe returned unexpected lines")
        value = json.loads(lines[0], object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError) as exc:
        raise RehearsalRefused("native probe emitted invalid JSON") from exc
    if not isinstance(value, dict):
        raise RehearsalRefused("native result must be a JSON object")
    if lines[1] != _NO_AUTHORITY or value.get("authority") != _NO_AUTHORITY:
        raise RehearsalRefused("native probe asserted unauthorized authority")
    status = value.get("status")
    if type(status) is not str or not status.startswith(("ALL_", "SCM_", "NATIVE_")):
        raise RehearsalRefused("native probe did not report a recognized status")
    if any(
        type(v) is not bool
        for k, v in value.items()
        if k not in ("status", "authority")
    ):
        raise RehearsalRefused("native probe emitted a non-boolean evidence field")
    return ProbeObservation(status=status, exit_code=exit_code, fields=value)


def _validate_fields(
    result: ProbeObservation,
    *,
    required_status: str,
    required_true: tuple[str, ...],
    required_false: tuple[str, ...],
    optional_boolean: tuple[str, ...] = (),
) -> None:
    if result.status != required_status or result.exit_code != 2:
        raise RehearsalRefused("required installed-machine observation unavailable")
    expected = {
        "status",
        "authority",
        *required_true,
        *required_false,
        *optional_boolean,
    }
    if set(result.fields) != expected:
        raise RehearsalRefused("native probe fields do not match the reviewed schema")
    for field in required_true:
        if result.fields[field] is not True:
            raise RehearsalRefused("required native observation is absent: " + field)
    for field in required_false:
        if result.fields[field] is not False:
            raise RehearsalRefused("dangerous right or authority observed: " + field)
    for field in optional_boolean:
        if type(result.fields[field]) is not bool:
            raise RehearsalRefused("non-boolean descriptive observation")


def review_rehearsal(observations: Mapping[str, ProbeObservation]) -> str:
    """Demand a coherent five-probe observation, NEVER certify installation."""
    if set(observations) != set(dict(_PROBES)):
        raise RehearsalRefused("all five independent diagnostic runs are mandatory")
    _validate_fields(
        observations["teacher"],
        required_status="ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED",
        required_true=(
            "native_read_only",
            "ordinary_primary_token_observed",
            "service_present",
            "access_checks_complete",
            "all_eight_dangerous_rights_denied",
        ),
        required_false=(
            "any_dangerous_right_granted",
            "independent_teacher_identity_attested",
            "installed_service_identity_verified",
            "publisher_pin_provisioned",
            "protected_write_performed",
            "authorized_to_install",
        ),
    )
    _validate_fields(
        observations["service_access"],
        required_status="SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED",
        required_true=("native_read_only", "service_present", "access_query_complete"),
        required_false=(
            "change_config_access_granted",
            "delete_access_granted",
            "write_dac_access_granted",
            "write_owner_access_granted",
            "start_access_granted",
            "stop_access_granted",
            "pause_access_granted",
            "user_control_access_granted",
            "independent_teacher_token_verified",
            "service_identity_verified",
            "protected_state_write_performed",
            "authorized_to_provision",
            "authorized_to_install",
        ),
    )
    _validate_fields(
        observations["service_security"],
        required_status="SCM_SECURITY_METADATA_OBSERVED_UNVERIFIED",
        required_true=(
            "native_read_only",
            "service_present",
            "service_dacl_observed",
            "service_sid_type_observed",
        ),
        required_false=(
            "service_identity_verified",
            "effective_teacher_rights_verified",
            "publisher_pin_provisioned",
            "protected_state_write_performed",
            "authorized_to_provision",
            "authorized_to_install",
        ),
        optional_boolean=("mutation_ace_observed",),
    )
    _validate_fields(
        observations["service_image"],
        required_status="SCM_PROCESS_IMAGE_LINKAGE_OBSERVED_UNVERIFIED",
        required_true=(
            "native_read_only",
            "service_present",
            "running_process_observed",
            "scm_process_image_agreement_observed",
            "held_image_attributes_observed",
            "image_owner_sid_observed",
            "image_dacl_observed",
        ),
        required_false=(
            "installed_service_identity_verified",
            "executable_custody_verified",
            "independent_teacher_identity_attested",
            "publisher_pin_verified",
            "protected_write_performed",
            "authorized_to_install",
        ),
        optional_boolean=("image_mutation_allow_ace_observed",),
    )
    _validate_fields(
        observations["publisher_pin"],
        required_status="NATIVE_PIN_CLAIM_OBSERVED_CUSTODY_UNPROVEN",
        required_true=("native_read_only", "publisher_pin_claim_observed"),
        required_false=(
            "independent_provisioner_authenticated",
            "rollback_protection_verified",
            "publisher_pin_verified",
            "authorized_to_install",
        ),
    )
    return "INSTALLED_MACHINE_NEGATIVE_REHEARSAL_OBSERVED_UNATTESTED"


def _build_directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise RehearsalRefused("explicit existing absolute build directory required")
    root = path.resolve(strict=True)
    if root != path or any(part in ("..", ".") for part in path.parts):
        raise RehearsalRefused("noncanonical or redirected build directory")
    if root.name.lower() != "build":
        raise RehearsalRefused("expected native CMake build directory")
    release = root / "Release"
    if release.is_symlink() or not release.is_dir():
        raise RehearsalRefused("native Release build directory missing")
    return release


def run_local_rehearsal(build_dir: Path) -> str:
    """Run fixed diagnostics under THIS process token; do not assert identity."""
    if os.name != "nt":
        raise RehearsalRefused("installed-machine rehearsal requires Windows")
    release = _build_directory(build_dir)
    results: dict[str, ProbeObservation] = {}
    for name, filename in _PROBES:
        executable = release / filename
        if executable.is_symlink() or not executable.is_file():
            raise RehearsalRefused("native diagnostic missing or redirected: " + name)
        try:
            completed = subprocess.run(
                [str(executable)],
                cwd=release,
                capture_output=True,
                check=False,
                timeout=_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RehearsalRefused(
                "native diagnostic could not complete: " + name
            ) from exc
        if completed.stderr:
            raise RehearsalRefused("unexpected native stderr: " + name)
        results[name] = parse_native_output(
            name, completed.returncode, completed.stdout
        )
    return review_rehearsal(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        status = run_local_rehearsal(options.build_dir)
    except (RehearsalRefused, OSError, ValueError) as exc:
        print("REFUSED_INSTALLED_MACHINE_REHEARSAL: " + str(exc), file=sys.stderr)
        print(_NO_AUTHORITY, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": status,
                "native_observations_complete": True,
                "independent_teacher_identity_attested": False,
                "independent_administrator_approved": False,
                "publisher_pin_verified": False,
                "rollback_protection_verified": False,
                "installed_service_identity_verified": False,
                "authorized_to_install": False,
                "authority": _NO_AUTHORITY,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    print(_NO_AUTHORITY)
    return 2  # Observations only. Zero never grants or reports acceptance.


if __name__ == "__main__":
    raise SystemExit(main())
