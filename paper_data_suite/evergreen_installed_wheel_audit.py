"""Issue #49 Slice 96: read-only installed-wheel acceptance evidence inventory.

This inspects installed metadata, wheel RECORD drift, interpreter confinement,
and console-script declarations without importing module code or launching it.
A clean local audit is NOT provenance authentication, official wheel acceptance,
Core contract qualification, or permission to install, launch, or activate.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, replace
from email.parser import Parser
from importlib import metadata
from pathlib import Path
from typing import Final

APPROVED_DISTRIBUTIONS: Final = (
    "paper-data-suite",
    "pds-core",
    "pds-scoreform",
    "pds-quillan",
    "pds-concord",
    "pds-meridian",
    "pds-vitrine",
    "pds-portia",
)
_NAME: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}\Z")
_MAX_RECORD_ROWS: Final = 20_000
_MAX_RECORD_BYTES: Final = 2_000_000
_MAX_FILE_BYTES: Final = 60_000_000
_MAX_TOTAL_BYTES: Final = 400_000_000


@dataclass(frozen=True, slots=True)
class InstalledWheelEvidence:
    """Observations only; never a trusted-release or launchability decision."""

    distribution: str
    status: str
    installed_version: str | None
    inside_active_interpreter: bool | None
    editable: bool | None
    wheel_tags: tuple[str, ...]
    launcher_names: tuple[str, ...]
    record_status: str
    record_files_checked: int
    findings: tuple[str, ...]
    provenance: str = "UNAUTHENTICATED_LOCAL_EVIDENCE_ONLY"
    authority: str = "NO_INSTALL_LAUNCH_ACTIVATION_OR_TRUST_AUTHORITY"


class InstalledAuditError(ValueError):
    """Refuse unsafe audit inputs or unbounded local metadata."""


def _canonical_name(value: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", value).lower()
    if len(normalized) > 64 or not _NAME.fullmatch(normalized):
        raise InstalledAuditError("invalid distribution identity")
    return normalized


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((path.resolve(), root.resolve())) == str(
            root.resolve()
        )
    except (OSError, ValueError):
        return False


def _parse_wheel_tags(dist: metadata.Distribution) -> tuple[str, ...]:
    raw = dist.read_text("WHEEL")
    if raw is None or len(raw) > 20_000:
        return ()
    tags = Parser().parsestr(raw).get_all("Tag", [])
    if len(tags) > 64:
        return ()
    return tuple(sorted(set(tag for tag in tags if _VERSION.fullmatch(tag))))


def _editable(dist: metadata.Distribution) -> bool | None:
    raw = dist.read_text("direct_url.json")
    if raw is None:
        return None
    if len(raw) > 40_000:
        return True
    try:
        item = json.loads(raw)
    except (ValueError, TypeError):
        return True
    if not isinstance(item, dict):
        return True
    info = item.get("dir_info")
    return isinstance(info, dict) and info.get("editable") is True


def _verify_record(
    dist: metadata.Distribution, environment: Path
) -> tuple[str, int, tuple[str, ...]]:
    raw = dist.read_text("RECORD")
    if raw is None:
        return "MISSING", 0, ("record_missing",)
    if len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
        return "UNVERIFIABLE", 0, ("record_too_large",)
    reader = csv.reader(io.StringIO(raw))
    checked = 0
    total_bytes = 0
    unverified = 0
    findings: set[str] = set()
    seen: set[str] = set()
    try:
        for idx, row in enumerate(reader):
            if idx >= _MAX_RECORD_ROWS:
                return "UNVERIFIABLE", checked, ("record_too_many_rows",)
            if len(row) != 3 or not row[0] or row[0] in seen:
                return "INVALID", checked, ("invalid_record_row",)
            seen.add(row[0])
            name, digest, recorded_size = row
            if "\\" in name or name.startswith("/") or Path(name).is_absolute():
                return "INVALID", checked, ("invalid_record_path",)
            candidate = Path(str(dist.locate_file(name)))
            if not _inside(candidate, environment):
                return "INVALID", checked, ("record_path_outside_environment",)
            if not digest:
                if not name.endswith(".dist-info/RECORD"):
                    unverified += 1
                continue
            if not digest.startswith("sha256="):
                return "UNVERIFIABLE", checked, ("unsupported_record_digest",)
            expected_b64 = digest.removeprefix("sha256=")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", expected_b64):
                return "INVALID", checked, ("invalid_record_digest",)
            if not candidate.is_file() or candidate.is_symlink():
                return "DRIFT", checked, ("record_file_missing_or_symlinked",)
            stat_size = candidate.stat().st_size
            if (
                stat_size > _MAX_FILE_BYTES
                or total_bytes + stat_size > _MAX_TOTAL_BYTES
            ):
                return "UNVERIFIABLE", checked, ("audit_size_limit",)
            if recorded_size:
                if not recorded_size.isascii() or not recorded_size.isdigit():
                    return "INVALID", checked, ("invalid_record_size",)
                if int(recorded_size) != stat_size:
                    return "DRIFT", checked, ("installed_file_size_changed",)
            h = hashlib.sha256()
            with candidate.open("rb") as stream:
                while block := stream.read(65536):
                    h.update(block)
            total_bytes += stat_size
            observed = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode()
            if observed != expected_b64:
                return "DRIFT", checked, ("installed_file_digest_changed",)
            checked += 1
    except (OSError, UnicodeError, csv.Error, ValueError):
        return "UNVERIFIABLE", checked, ("record_read_failed",)
    if checked == 0:
        findings.add("record_has_no_verified_files")
    if unverified:
        findings.add("record_contains_unhashed_entries")
    return (
        ("LOCAL_MATCH" if checked else "UNVERIFIABLE"),
        checked,
        tuple(sorted(findings)),
    )


def inspect_distribution(
    requested: str, dist: metadata.Distribution, environment: Path
) -> InstalledWheelEvidence:
    """Inspect one provided distribution without importing/executing its code."""
    name = _canonical_name(requested)
    if name not in APPROVED_DISTRIBUTIONS:
        raise InstalledAuditError("unapproved distribution requested")
    findings: set[str] = set()
    try:
        actual = _canonical_name(dist.metadata["Name"] or "")
    except InstalledAuditError:
        actual = ""
    version = dist.version if _VERSION.fullmatch(dist.version) else None
    inside = _inside(Path(str(dist.locate_file(""))), environment)
    if actual != name:
        findings.add("installed_identity_mismatch")
    if version is None:
        findings.add("version_invalid")
    if not inside:
        findings.add("distribution_outside_active_interpreter")
    editable = _editable(dist)
    if editable:
        findings.add("editable_install_not_accepted")
    wheel_tags = _parse_wheel_tags(dist)
    if not wheel_tags:
        findings.add("wheel_tags_unavailable")
    launchers = tuple(
        sorted(
            {
                ep.name
                for ep in dist.entry_points
                if ep.group == "console_scripts"
                and len(ep.name) <= 80
                and re.fullmatch(r"[A-Za-z0-9_.-]+", ep.name)
            }
        )
    )
    if not launchers:
        findings.add("console_script_not_observed")
    record_status, checked, record_findings = _verify_record(dist, environment)
    findings.update(record_findings)
    if record_status != "LOCAL_MATCH":
        findings.add("installed_record_not_verified")
    status = "LOCAL_INVENTORY_ONLY" if not findings else "REVIEW_REQUIRED"
    return InstalledWheelEvidence(
        distribution=name,
        status=status,
        installed_version=version,
        inside_active_interpreter=inside,
        editable=editable,
        wheel_tags=wheel_tags,
        launcher_names=launchers,
        record_status=record_status,
        record_files_checked=checked,
        findings=tuple(sorted(findings)),
    )


def audit_active_interpreter(
    names: tuple[str, ...] = APPROVED_DISTRIBUTIONS,
) -> tuple[InstalledWheelEvidence, ...]:
    """Read-only inventory for this interpreter, never a provenance grant."""
    selected = tuple(_canonical_name(n) for n in names)
    if len(selected) > len(APPROVED_DISTRIBUTIONS) or len(set(selected)) != len(
        selected
    ):
        raise InstalledAuditError("duplicate or excessive distribution selection")
    if any(name not in APPROVED_DISTRIBUTIONS for name in selected):
        raise InstalledAuditError("unapproved distribution requested")
    observations: list[InstalledWheelEvidence] = []
    env = Path(sys.prefix)
    for name in selected:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            observations.append(
                InstalledWheelEvidence(
                    distribution=name,
                    status="NOT_INSTALLED_IN_THIS_INTERPRETER",
                    installed_version=None,
                    inside_active_interpreter=None,
                    editable=None,
                    wheel_tags=(),
                    launcher_names=(),
                    record_status="NOT_AVAILABLE",
                    record_files_checked=0,
                    findings=("module_not_installed",),
                )
            )
            continue
        observations.append(inspect_distribution(name, dist, env))
    names_to_owners: dict[str, set[str]] = {}
    for item in observations:
        for launcher in item.launcher_names:
            names_to_owners.setdefault(launcher.casefold(), set()).add(
                item.distribution
            )
    conflicts = {
        launcher for launcher, owners in names_to_owners.items() if len(owners) > 1
    }
    return tuple(
        replace(
            item,
            status="REVIEW_REQUIRED",
            findings=tuple(
                sorted(set(item.findings) | {"shared_console_script_identity"})
            ),
        )
        if any(n.casefold() in conflicts for n in item.launcher_names)
        else item
        for item in observations
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution", action="append", choices=APPROVED_DISTRIBUTIONS
    )
    args = parser.parse_args()
    selected = tuple(args.distribution) if args.distribution else APPROVED_DISTRIBUTIONS
    observations = audit_active_interpreter(selected)
    print(
        json.dumps(
            {
                "schema": "pds-installed-wheel-inventory-v1",
                "source": "read_only_active_python_interpreter",
                "acceptance": "NOT_ESTABLISHED",
                "authority": "NO_INSTALL_LAUNCH_ACTIVATION_OR_TRUST_AUTHORITY",
                "limitations": [
                    "installed_RECORD_is_not_signed_artifact_provenance",
                    "signed_official_wheel_and_catalog_acceptance_not_performed",
                    "no_module_process_or_workspace_is_accessed",
                ],
                "distributions": [asdict(item) for item in observations],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
