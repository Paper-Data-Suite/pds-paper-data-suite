"""Issue #49 Slice 112: canonical *untrusted* Windows installer intent.

An ordinary teacher can construct these bytes. They are NOT an administrative
approval, signed catalog, artifact verification, privilege escalation token,
service request, receipt, or launch permission. No filesystem, SCM, subprocess,
network, or classroom-data operations are performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, cast

from paper_data_suite.evergreen_windows_admin_install_plan import (
    _PHASE_SPECS,
    AdminInstallPlanReview,
)

_MAX_BYTES: Final = 16 * 1024
_MAX_PACKAGES: Final = 10
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_VERSION: Final = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z"
)
_DIST: Final = (
    "paper-data-suite",
    "pds-concord",
    "pds-core",
    "pds-meridian",
    "pds-portia",
    "pds-vitrine",
    "quillan",
    "scoreform",
)
_OPERATION: Final = "NEW_PROTECTED_WINDOWS_INSTALLATION"
_SERVICE: Final = "PaperDataSuiteService"
_NO_AUTHORITY: Final = (
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
)
_PHASES: Final = tuple(row[0] for row in _PHASE_SPECS)


class InstallerIntentError(ValueError):
    """An untrusted installer-intent document or plan was refused."""


@dataclass(frozen=True, slots=True)
class IntendedArtifact:
    """Untrusted exact artifact *claim*, not an authenticated wheel."""

    distribution: str
    version: str
    sha256: str


@dataclass(frozen=True, slots=True)
class InstallerIntent:
    """Canonical request to review; no credentials, file paths or approvals."""

    schema: int
    operation: str
    service_name: str
    transaction_id: str
    catalog_sha256: str
    recovery_basis_sha256: str
    artifacts: tuple[IntendedArtifact, ...]
    requested_phases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstallerIntentReview:
    """An untrusted intent is structurally recognized, NEVER admitted."""

    status: str
    operation: str
    service_name: str
    transaction_id: str
    request_sha256: str
    artifact_count: int
    directory_observation: str
    service_observation: str
    independently_authenticated_actor: bool = False
    catalog_artifacts_authenticated: bool = False
    recovery_basis_authenticated: bool = False
    authorized_to_provision: bool = False
    authorized_to_register_service: bool = False
    authorized_to_publish_receipt: bool = False
    authorized_to_activate_or_launch: bool = False
    authority: str = _NO_AUTHORITY


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise InstallerIntentError("duplicate installer intent JSON field")
        result[name] = value
    return result


def _sha(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise InstallerIntentError("invalid " + name)
    return value


def _transaction_id(value: object) -> str:
    if type(value) is not str or _TX.fullmatch(value) is None:
        raise InstallerIntentError("invalid transaction ID")
    return value


def parse_untrusted_installer_intent(raw: bytes) -> InstallerIntent:
    """Require strict UTF-8, exact fields and byte-for-byte canonical JSON.

    Unauthenticated hashes do not establish provenance. Foreign directories,
    shell commands, actor IDs, timestamps and approval flags have no fields.
    """
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_BYTES:
        raise InstallerIntentError("missing or excessive installer intent bytes")
    try:
        decoded: object = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs
        )
    except InstallerIntentError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise InstallerIntentError("invalid installer intent JSON") from exc
    if not isinstance(decoded, dict) or set(decoded) != {
        "schema",
        "operation",
        "service_name",
        "transaction_id",
        "catalog_sha256",
        "recovery_basis_sha256",
        "artifacts",
        "requested_phases",
    }:
        raise InstallerIntentError("unexpected installer intent fields")
    obj = cast(dict[str, object], decoded)
    if (
        type(obj["schema"]) is not int
        or obj["schema"] != 1
        or obj["operation"] != _OPERATION
        or obj["service_name"] != _SERVICE
    ):
        raise InstallerIntentError("unknown installer intent schema or operation")
    artifacts = obj["artifacts"]
    if type(artifacts) is not list or not 1 <= len(artifacts) <= _MAX_PACKAGES:
        raise InstallerIntentError("invalid artifact intent count")
    entries: list[IntendedArtifact] = []
    for value in artifacts:
        if type(value) is not dict or set(value) != {
            "distribution",
            "version",
            "sha256",
        }:
            raise InstallerIntentError("unexpected artifact intent fields")
        distribution = value["distribution"]
        version = value["version"]
        if (
            type(distribution) is not str
            or distribution not in _DIST
            or type(version) is not str
            or _VERSION.fullmatch(version) is None
        ):
            raise InstallerIntentError("unapproved distribution or version")
        entries.append(
            IntendedArtifact(
                distribution, version, _sha(value["sha256"], "artifact digest")
            )
        )
    names = tuple(a.distribution for a in entries)
    if tuple(sorted(names)) != names or len(set(names)) != len(names):
        raise InstallerIntentError(
            "artifact distribution list must be unique and sorted"
        )
    if "paper-data-suite" not in names or "pds-core" not in names:
        raise InstallerIntentError("new installation requires Suite and Core intents")
    phases = obj["requested_phases"]
    if type(phases) is not list or tuple(phases) != _PHASES:
        raise InstallerIntentError("required independent installation phases omitted")
    try:
        normalized = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise InstallerIntentError("noncanonical installer intent") from exc
    if normalized != raw:
        raise InstallerIntentError("installer intent bytes not canonical")
    return InstallerIntent(
        1,
        _OPERATION,
        _SERVICE,
        _transaction_id(obj["transaction_id"]),
        _sha(obj["catalog_sha256"], "catalog digest"),
        _sha(obj["recovery_basis_sha256"], "recovery basis digest"),
        tuple(entries),
        tuple(phases),
    )


def inspect_installer_intent(
    raw: bytes, plan: AdminInstallPlanReview
) -> InstallerIntentReview:
    """Reconcile locally forgeable request/plan; every outcome is unapproved.

    The privileged installer MUST independently establish OS actor identity,
    explicit consent, pinned catalog and artifact bytes, recovery state and
    installation identity. This review MUST NOT be treated as their proof.
    """
    if type(plan) is not AdminInstallPlanReview or (
        plan.status
        not in (
            "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED",
            "ADMINISTRATIVE_PROOFS_OUTSTANDING_METADATA_ONLY",
        )
        or plan.service_name != _SERVICE
        or plan.authority
        != ("NO_ADMIN_INSTALL_SERVICE_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY")
        or any(
            type(getattr(plan, field)) is not bool or getattr(plan, field)
            for field in (
                "authenticated_installer",
                "authorized_to_create_directories",
                "authorized_to_register_service",
                "authorized_to_modify_receipts",
                "authorized_to_activate_or_launch",
            )
        )
        or tuple(phase.code for phase in plan.phases) != _PHASES
        or any(
            phase.status != "INDEPENDENT_ADMINISTRATIVE_ACTION_PENDING"
            or type(phase.authorized_for_execution) is not bool
            or phase.authorized_for_execution
            for phase in plan.phases
        )
        or plan.directory_observation
        not in (
            "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED",
            "PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        )
        or plan.service_observation
        not in ("SERVICE_NOT_INSTALLED", "SERVICE_METADATA_OBSERVED_UNVERIFIED")
    ):
        raise InstallerIntentError("administrator plan asserts unearned authority")
    request = parse_untrusted_installer_intent(raw)
    return InstallerIntentReview(
        status="UNTRUSTED_INSTALLER_INTENT_REVIEW_ONLY",
        operation=request.operation,
        service_name=request.service_name,
        transaction_id=request.transaction_id,
        request_sha256=hashlib.sha256(raw).hexdigest(),
        artifact_count=len(request.artifacts),
        directory_observation=plan.directory_observation,
        service_observation=plan.service_observation,
    )


def main(argv: list[str] | None = None) -> int:
    """Show the importer boundary, never load user files or accept approvals."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(
        json.dumps(
            {
                "status": "INDEPENDENT_INSTALLER_REQUEST_NOT_SUBMITTED",
                "schema": 1,
                "required_operation": _OPERATION,
                "service_name": _SERVICE,
                "required_phases": _PHASES,
                "allowed_distributions": _DIST,
                "maximum_request_bytes": _MAX_BYTES,
                "privileged_installer_implemented": False,
                "production_authority": False,
                "active_receipt_authority": False,
                "authority": _NO_AUTHORITY,
            },
            indent=2,
        )
    )
    print(_NO_AUTHORITY)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
