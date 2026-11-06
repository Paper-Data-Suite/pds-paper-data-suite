"""Slice 112: locally constructible installer intent never authenticates installer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from paper_data_suite import evergreen_windows_installer_intent as target
from paper_data_suite.evergreen_windows_admin_install_plan import (
    _PHASE_SPECS,
    AdminInstallPhase,
    AdminInstallPlanReview,
)


def _plan() -> AdminInstallPlanReview:
    phases = tuple(
        AdminInstallPhase(n, name, role, deps, evidence)
        for n, (name, role, deps, evidence) in enumerate(_PHASE_SPECS, 1)
    )
    return AdminInstallPlanReview(
        status="ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED",
        service_name="PaperDataSuiteService",
        directory_observation="PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED",
        service_observation="SERVICE_NOT_INSTALLED",
        missing_directory_purposes=("APPLICATION_BINARIES",),
        blockers=("ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",),
        required_proof_codes=(),
        phases=phases,
    )


def _dict() -> dict[str, object]:
    return {
        "schema": 1,
        "operation": "NEW_PROTECTED_WINDOWS_INSTALLATION",
        "service_name": "PaperDataSuiteService",
        "transaction_id": "a" * 32,
        "catalog_sha256": "b" * 64,
        "recovery_basis_sha256": "c" * 64,
        "artifacts": [
            {
                "distribution": "paper-data-suite",
                "version": "0.1.0",
                "sha256": "d" * 64,
            },
            {"distribution": "pds-core", "version": "0.6.6", "sha256": "e" * 64},
        ],
        "requested_phases": list(target._PHASES),
    }


def _canon(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_canonical_request_is_still_untrusted() -> None:
    raw = _canon(_dict())
    parsed = target.parse_untrusted_installer_intent(raw)
    assert parsed.operation == "NEW_PROTECTED_WINDOWS_INSTALLATION"
    assert parsed.transaction_id == "a" * 32
    assert tuple(x.distribution for x in parsed.artifacts) == (
        "paper-data-suite",
        "pds-core",
    )
    review = target.inspect_installer_intent(raw, _plan())
    assert review.status == "UNTRUSTED_INSTALLER_INTENT_REVIEW_ONLY"
    assert review.request_sha256 == hashlib.sha256(raw).hexdigest()
    assert review.artifact_count == 2
    assert review.directory_observation == "PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED"
    for field in (
        "independently_authenticated_actor",
        "catalog_artifacts_authenticated",
        "recovery_basis_authenticated",
        "authorized_to_provision",
        "authorized_to_register_service",
        "authorized_to_publish_receipt",
        "authorized_to_activate_or_launch",
    ):
        assert getattr(review, field) is False


def test_review_of_existing_metadata_does_not_admit() -> None:
    plan = replace(
        _plan(),
        status="ADMINISTRATIVE_PROOFS_OUTSTANDING_METADATA_ONLY",
        directory_observation="PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        service_observation="SERVICE_METADATA_OBSERVED_UNVERIFIED",
    )
    review = target.inspect_installer_intent(_canon(_dict()), plan)
    assert review.status == "UNTRUSTED_INSTALLER_INTENT_REVIEW_ONLY"
    assert not review.authorized_to_activate_or_launch


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema", True),
        ("schema", 2),
        ("operation", "INSTALL_NOW"),
        ("service_name", "PDSservice"),
        ("transaction_id", "A" * 32),
        ("transaction_id", "a" * 31),
        ("catalog_sha256", "z" * 64),
        ("catalog_sha256", "a" * 63),
        ("recovery_basis_sha256", "C" * 64),
        ("requested_phases", []),
        ("requested_phases", list(target._PHASES[:-1])),
        ("artifacts", []),
        ("artifacts", "not-a-list"),
    ],
)
def test_invalid_top_level_fields_refuse(field: str, invalid: object) -> None:
    d = _dict()
    d[field] = invalid
    with pytest.raises(target.InstallerIntentError):
        target.parse_untrusted_installer_intent(_canon(d))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("distribution", "evil-package"),
        ("distribution", "PDS-CORE"),
        ("version", "0.6.6rc1"),
        ("version", "0.6.6; rm -rf"),
        ("version", "01.2.3"),
        ("sha256", "F" * 64),
        ("sha256", "0" * 65),
    ],
)
def test_bad_artifact_claims_refuse(field: str, value: object) -> None:
    d = _dict()
    a = d["artifacts"]
    assert isinstance(a, list)
    a[1][field] = value
    with pytest.raises(target.InstallerIntentError):
        target.parse_untrusted_installer_intent(_canon(d))


def test_duplicate_artifact_refuses() -> None:
    d = _dict()
    a = d["artifacts"]
    assert isinstance(a, list)
    a.append(dict(a[1]))
    with pytest.raises(target.InstallerIntentError, match="unique"):
        target.parse_untrusted_installer_intent(_canon(d))


def test_unsorted_artifacts_refuse() -> None:
    d = _dict()
    a = d["artifacts"]
    assert isinstance(a, list)
    a.reverse()
    with pytest.raises(target.InstallerIntentError, match="sorted"):
        target.parse_untrusted_installer_intent(_canon(d))


@pytest.mark.parametrize("missing", ["pds-core", "paper-data-suite"])
def test_missing_base_distributions_refuse(missing: str) -> None:
    d = _dict()
    a = d["artifacts"]
    assert isinstance(a, list)
    d["artifacts"] = [v for v in a if v["distribution"] != missing]
    with pytest.raises(target.InstallerIntentError, match="requires"):
        target.parse_untrusted_installer_intent(_canon(d))


def test_unapproved_artifact_property_refuses() -> None:
    d = _dict()
    a = d["artifacts"]
    assert isinstance(a, list)
    a[0]["wheel_path"] = "C:\\untrusted.exe"
    with pytest.raises(target.InstallerIntentError):
        target.parse_untrusted_installer_intent(_canon(d))


@pytest.mark.parametrize("key", ["installer_is_admin", "consent", "command", "path"])
def test_privilege_or_command_injection_field_refuses(key: str) -> None:
    d = _dict()
    d[key] = "untrusted"
    with pytest.raises(target.InstallerIntentError):
        target.parse_untrusted_installer_intent(_canon(d))


def test_duplicate_json_key_refuses() -> None:
    raw = _canon(_dict()).replace(b'"schema":1', b'"schema":1,"schema":1')
    with pytest.raises(target.InstallerIntentError, match="duplicate"):
        target.parse_untrusted_installer_intent(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b + b"\n",
        lambda b: b" " + b,
        lambda b: b.replace(b'"schema":1', b'"schema": 1'),
        lambda b: b"\xef\xbb\xbf" + b,
    ],
)
def test_noncanonical_bytes_refuse(mutation: object) -> None:
    raw = mutation(_canon(_dict()))  # type: ignore[operator]
    with pytest.raises(target.InstallerIntentError):
        target.parse_untrusted_installer_intent(raw)


@pytest.mark.parametrize("raw", [None, "text", b"", b"{}", b"\xff", b"x" * 16385])
def test_invalid_raw_bytes_refuse(raw: object) -> None:
    with pytest.raises(target.InstallerIntentError):
        target.parse_untrusted_installer_intent(raw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "authenticated_installer",
        "authorized_to_create_directories",
        "authorized_to_register_service",
        "authorized_to_modify_receipts",
        "authorized_to_activate_or_launch",
    ],
)
def test_forged_admin_authority_refuses(field: str) -> None:
    with pytest.raises(target.InstallerIntentError, match="unearned authority"):
        target.inspect_installer_intent(
            _canon(_dict()), replace(_plan(), **{field: True})
        )


def test_forged_phase_execution_refuses() -> None:
    plan = _plan()
    bad = replace(plan.phases[0], authorized_for_execution=True)
    with pytest.raises(target.InstallerIntentError, match="unearned authority"):
        target.inspect_installer_intent(
            _canon(_dict()), replace(plan, phases=(bad, *plan.phases[1:]))
        )


def test_forged_plan_service_refuses() -> None:
    with pytest.raises(target.InstallerIntentError):
        target.inspect_installer_intent(
            _canon(_dict()), replace(_plan(), service_name="TeacherService")
        )


def test_cli_is_non_authorizing_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    assert target.main([]) == 2
    output = capsys.readouterr().out
    obj = json.loads(output.split("\n" + target._NO_AUTHORITY)[0])
    assert obj["privileged_installer_implemented"] is False
    assert obj["production_authority"] is False
    assert obj["active_receipt_authority"] is False
    assert obj["allowed_distributions"]


def test_cli_rejects_unimplemented_apply_option() -> None:
    with pytest.raises(SystemExit) as raised:
        target.main(["--apply"])
    assert raised.value.code == 2
