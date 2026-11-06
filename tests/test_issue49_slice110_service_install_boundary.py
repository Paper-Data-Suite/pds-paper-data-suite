"""Slice 110: mixed directory/SCM observations never authorize installation."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from paper_data_suite import evergreen_windows_service_install_boundary as target
from paper_data_suite.evergreen_windows_deployment_preflight import (
    DeploymentPreflightError,
)
from paper_data_suite.evergreen_windows_provisioning_contract import (
    ProvisioningRequirement,
    ProvisioningReview,
)
from paper_data_suite.evergreen_windows_service_identity_preflight import (
    ServiceIdentityObservation,
    ServiceIdentityPreflightError,
)


@pytest.fixture
def absent() -> tuple[ProvisioningReview, ServiceIdentityObservation]:
    app = r"C:\Program Files\Paper Data Suite"
    state = r"C:\ProgramData\Paper Data Suite"
    paths = (app, state, state + r"\active-receipts", state + r"\service-state")
    purposes = (
        "APPLICATION_BINARIES",
        "PROTECTED_STATE_ROOT",
        "ACTIVE_RECEIPTS",
        "SERVICE_TRANSACTION_STATE",
    )
    directory = ProvisioningReview(
        status="PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED",
        required_directories=tuple(
            ProvisioningRequirement(path, purpose)
            for path, purpose in zip(paths, purposes, strict=True)
        ),
        checked_paths=(r"C:\Program Files", r"C:\ProgramData"),
        missing_paths=paths,
    )
    service = ServiceIdentityObservation(status="SERVICE_NOT_INSTALLED")
    return directory, service


def test_all_missing_still_not_installer_authority(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    observation = target.reconcile_service_install_boundary(*absent)
    assert observation.status == "PROTECTED_SERVICE_INSTALLATION_REQUIRED"
    assert observation.service_name == "PaperDataSuiteService"
    assert observation.missing_directory_purposes == tuple(
        r.purpose for r in absent[0].required_directories
    )
    assert observation.blockers == (
        "PROTECTED_DEPLOYMENT_DIRECTORIES_ABSENT",
        "INDEPENDENT_WINDOWS_SERVICE_NOT_INSTALLED",
        "ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",
    )
    assert not observation.production_authority
    assert not observation.active_receipt_authority
    assert not observation.service_identity_verified
    assert not observation.executable_integrity_verified
    assert not observation.protected_receipt_head_verified
    assert len(observation.independent_proofs) == 7
    assert all(
        p.status == "INDEPENDENT_PROOF_REQUIRED" for p in observation.independent_proofs
    )


def test_observed_service_and_directories_still_no_grants(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    dirs, svc = absent
    dirs = replace(
        dirs,
        status="PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        missing_paths=(),
    )
    svc = replace(
        svc,
        status="SERVICE_METADATA_OBSERVED_UNVERIFIED",
        observed_state="STOPPED_OBSERVED",
        observed_start_mode="MANUAL_OBSERVED",
        account_category="SHARED_PRIVILEGED_ACCOUNT_OBSERVED",
        registered_binary_path="REGISTERED_PATH_UNTRUSTED_NOT_DISCLOSED",
    )
    review = target.reconcile_service_install_boundary(dirs, svc)
    assert review.status == "INSTALLED_METADATA_ONLY_SECURITY_PROOFS_REQUIRED"
    assert review.blockers == (
        "ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",
    )
    assert review.missing_directory_purposes == ()
    assert review.authority == target._NO_AUTHORITY
    assert not review.production_authority


@pytest.mark.parametrize(
    "field,value",
    [
        ("production_authority", True),
        ("active_receipt_authority", True),
        ("service_identity", "VERIFIED"),
        ("executable_integrity", "VERIFIED"),
        ("protected_receipt_head", "VERIFIED"),
        ("authority", "APPROVED"),
        ("status", "TRUSTED"),
        ("missing_paths", ()),
        ("missing_paths", ("foreign",)),
        ("missing_paths", ("duplicated", "duplicated")),
        ("missing_paths", ["foreign"]),
    ],
)
def test_forged_directory_authority_refused(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
    field: str,
    value: object,
) -> None:
    with pytest.raises(target.ServiceInstallBoundaryError):
        target.reconcile_service_install_boundary(
            replace(absent[0], **{field: value}), absent[1]
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("production_authority", True),
        ("active_receipt_authority", True),
        ("service_name", "OtherService"),
        ("authority", "APPROVED"),
        ("status", "TRUSTED"),
        ("service_sid_type", "VERIFIED"),
        ("effective_token", "VERIFIED"),
        ("service_dacl", "VERIFIED"),
        ("executable_integrity", "VERIFIED"),
        ("protected_receipt_head", "VERIFIED"),
        ("observed_state", "RUNNING_OBSERVED"),
        ("registered_binary_path", "bogus.exe"),
    ],
)
def test_forged_service_authority_refused(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
    field: str,
    value: object,
) -> None:
    with pytest.raises(target.ServiceInstallBoundaryError):
        target.reconcile_service_install_boundary(
            absent[0], replace(absent[1], **{field: value})
        )


def test_forged_requirement_rejected(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    dirs, svc = absent
    bad = replace(dirs.required_directories[0], ordinary_user_write_allowed=True)
    with pytest.raises(target.ServiceInstallBoundaryError):
        target.reconcile_service_install_boundary(
            replace(dirs, required_directories=(bad, *dirs.required_directories[1:])),
            svc,
        )


def test_duplicate_directory_rejected(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    dirs, svc = absent
    duplicate = replace(
        dirs.required_directories[1], directory=dirs.required_directories[0].directory
    )
    with pytest.raises(target.ServiceInstallBoundaryError):
        target.reconcile_service_install_boundary(
            replace(
                dirs,
                required_directories=(
                    dirs.required_directories[0],
                    duplicate,
                    *dirs.required_directories[2:],
                ),
            ),
            svc,
        )


def test_strict_type_checks(
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    with pytest.raises(target.ServiceInstallBoundaryError):
        target.reconcile_service_install_boundary(SimpleNamespace(), absent[1])  # type: ignore[arg-type]
    with pytest.raises(target.ServiceInstallBoundaryError):
        target.reconcile_service_install_boundary(absent[0], SimpleNamespace())  # type: ignore[arg-type]


def test_windows_probe_calls_both_read_only_components(
    monkeypatch: pytest.MonkeyPatch,
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    called: list[str] = []
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))

    def dirs() -> ProvisioningReview:
        called.append("dirs")
        return absent[0]

    def service() -> ServiceIdentityObservation:
        called.append("service")
        return absent[1]

    monkeypatch.setattr(target, "inspect_windows_provisioning", dirs)
    monkeypatch.setattr(target, "audit_windows_service_identity", service)
    assert (
        target.inspect_windows_service_install_boundary().production_authority is False
    )
    assert called == ["dirs", "service"]


@pytest.mark.parametrize("kind", ["directory", "service"])
def test_observer_failure_refuses_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
    kind: str,
) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))

    def fail() -> object:
        if kind == "directory":
            raise DeploymentPreflightError("private path")
        raise ServiceIdentityPreflightError("private service")

    if kind == "directory":
        monkeypatch.setattr(target, "inspect_windows_provisioning", fail)
    else:
        monkeypatch.setattr(target, "inspect_windows_provisioning", lambda: absent[0])
    if kind == "service":
        monkeypatch.setattr(target, "audit_windows_service_identity", fail)
    with pytest.raises(target.ServiceInstallBoundaryError, match="unavailable"):
        target.inspect_windows_service_install_boundary()


def test_non_windows_refuses_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="posix"))
    with pytest.raises(target.ServiceInstallBoundaryError, match="Windows"):
        target.inspect_windows_service_install_boundary()


def test_cli_status_two_and_no_grants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    monkeypatch.setattr(
        target,
        "inspect_windows_service_install_boundary",
        lambda: target.reconcile_service_install_boundary(*absent),
    )
    assert target.main([]) == 2
    output = capsys.readouterr().out
    decoded = json.loads(output.split("\n" + target._NO_AUTHORITY)[0])
    assert decoded["production_authority"] is False
    assert decoded["active_receipt_authority"] is False
    assert decoded["status"] == "PROTECTED_SERVICE_INSTALLATION_REQUIRED"


def test_cli_observed_zero_is_still_not_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    absent: tuple[ProvisioningReview, ServiceIdentityObservation],
) -> None:
    dirs, svc = absent
    dirs = replace(
        dirs,
        status="PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        missing_paths=(),
    )
    svc = replace(svc, status="SERVICE_METADATA_OBSERVED_UNVERIFIED")
    monkeypatch.setattr(
        target,
        "inspect_windows_service_install_boundary",
        lambda: target.reconcile_service_install_boundary(dirs, svc),
    )
    assert target.main([]) == 0
    out = capsys.readouterr().out
    assert '"production_authority": false' in out
    assert '"service_identity_verified": false' in out


def test_cli_failure_code_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> target.ServiceInstallBoundaryReview:
        raise target.ServiceInstallBoundaryError("denied")

    monkeypatch.setattr(target, "inspect_windows_service_install_boundary", fail)
    assert target.main([]) == 1
    assert target._NO_AUTHORITY in capsys.readouterr().err
