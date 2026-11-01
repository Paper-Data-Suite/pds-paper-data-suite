"""Slice 111: fixed administrator phases cannot authorize teacher installation."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from paper_data_suite import evergreen_windows_admin_install_plan as target
from paper_data_suite.evergreen_windows_service_install_boundary import (
    IndependentProofObligation,
    ServiceInstallBoundaryError,
    ServiceInstallBoundaryReview,
)


@pytest.fixture
def missing_boundary() -> ServiceInstallBoundaryReview:
    codes = (
        "INDEPENDENT_INSTALLER_IDENTITY",
        "CANONICAL_OS_DEPLOYMENT_PATHS",
        "SCM_SERVICE_OBJECT_DACL",
        "SERVICE_TOKEN_AND_SID",
        "EXECUTABLE_BYTES_AND_CUSTODY",
        "PROTECTED_RECEIPT_AND_CAS_HEAD",
        "TEACHER_NEGATIVE_SECURITY_TESTS",
    )
    return ServiceInstallBoundaryReview(
        status="PROTECTED_SERVICE_INSTALLATION_REQUIRED",
        service_name="PaperDataSuiteService",
        directory_observation="PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED",
        service_observation="SERVICE_NOT_INSTALLED",
        missing_directory_purposes=(
            "APPLICATION_BINARIES",
            "PROTECTED_STATE_ROOT",
            "ACTIVE_RECEIPTS",
            "SERVICE_TRANSACTION_STATE",
        ),
        blockers=(
            "PROTECTED_DEPLOYMENT_DIRECTORIES_ABSENT",
            "INDEPENDENT_WINDOWS_SERVICE_NOT_INSTALLED",
            "ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",
        ),
        independent_proofs=tuple(
            IndependentProofObligation(c, "ADMINISTRATOR", "Required evidence")
            for c in codes
        ),
    )


def test_missing_pilot_is_deterministic_and_non_authorizing(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    plan = target.prepare_admin_install_plan(missing_boundary)
    assert plan.status == "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED"
    assert plan.service_name == "PaperDataSuiteService"
    assert len(plan.phases) == 7
    assert tuple(x.ordinal for x in plan.phases) == tuple(range(1, 8))
    assert plan.required_proof_codes == tuple(
        proof.code for proof in missing_boundary.independent_proofs
    )
    assert (
        plan.missing_directory_purposes == missing_boundary.missing_directory_purposes
    )
    assert not plan.authenticated_installer
    assert not plan.authorized_to_create_directories
    assert not plan.authorized_to_register_service
    assert not plan.authorized_to_modify_receipts
    assert not plan.authorized_to_activate_or_launch
    assert all(not phase.authorized_for_execution for phase in plan.phases)
    assert all(
        phase.status == "INDEPENDENT_ADMINISTRATIVE_ACTION_PENDING"
        for phase in plan.phases
    )


def test_phases_have_no_missing_or_forward_dependencies(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    plan = target.prepare_admin_install_plan(missing_boundary)
    seen: set[str] = set()
    for phase in plan.phases:
        assert all(dep in seen for dep in phase.requires_completed)
        assert phase.code not in seen
        assert phase.responsible_party.startswith("INDEPENDENT_")
        seen.add(phase.code)
    assert plan.phases[-1].code == "INDEPENDENT_ACTIVATION_RELEASE_GATE"


def test_both_metadata_observed_still_no_authority(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    observed = replace(
        missing_boundary,
        status="INSTALLED_METADATA_ONLY_SECURITY_PROOFS_REQUIRED",
        directory_observation="PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        service_observation="SERVICE_METADATA_OBSERVED_UNVERIFIED",
        missing_directory_purposes=(),
        blockers=("ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",),
    )
    plan = target.prepare_admin_install_plan(observed)
    assert plan.status == "ADMINISTRATIVE_PROOFS_OUTSTANDING_METADATA_ONLY"
    assert len(plan.phases) == 7
    assert not plan.authorized_to_activate_or_launch


def test_directories_present_service_missing(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    partial = replace(
        missing_boundary,
        directory_observation="PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        missing_directory_purposes=(),
        blockers=(
            "INDEPENDENT_WINDOWS_SERVICE_NOT_INSTALLED",
            "ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",
        ),
    )
    assert (
        target.prepare_admin_install_plan(partial).status
        == "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED"
    )


def test_service_present_some_directories_missing(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    partial = replace(
        missing_boundary,
        service_observation="SERVICE_METADATA_OBSERVED_UNVERIFIED",
        missing_directory_purposes=("APPLICATION_BINARIES",),
        blockers=(
            "PROTECTED_DEPLOYMENT_DIRECTORIES_ABSENT",
            "ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",
        ),
    )
    assert (
        target.prepare_admin_install_plan(partial).status
        == "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("production_authority", True),
        ("active_receipt_authority", True),
        ("service_identity_verified", True),
        ("executable_integrity_verified", True),
        ("protected_receipt_head_verified", True),
        ("status", "VERIFIED"),
        ("service_name", "OtherService"),
        ("authority", "APPROVED"),
        ("directory_observation", "UNKNOWN"),
        ("service_observation", "TRUSTED"),
        ("missing_directory_purposes", ()),
        ("missing_directory_purposes", ("ACTIVE_RECEIPTS", "ACTIVE_RECEIPTS")),
        ("missing_directory_purposes", ("FOREIGN",)),
        ("missing_directory_purposes", ("ACTIVE_RECEIPTS", "APPLICATION_BINARIES")),
        ("missing_directory_purposes", ["APPLICATION_BINARIES"]),
        ("blockers", ()),
        ("blockers", ("APPROVED",)),
    ],
)
def test_unearned_or_inconsistent_inputs_refuse(
    missing_boundary: ServiceInstallBoundaryReview, field: str, value: object
) -> None:
    with pytest.raises(target.AdminInstallPlanError):
        target.prepare_admin_install_plan(replace(missing_boundary, **{field: value}))


def test_missing_proof_is_refused(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    with pytest.raises(target.AdminInstallPlanError, match="proof"):
        target.prepare_admin_install_plan(
            replace(
                missing_boundary,
                independent_proofs=missing_boundary.independent_proofs[:-1],
            )
        )


def test_forged_proof_completion_is_refused(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    forged = replace(missing_boundary.independent_proofs[0], status="VERIFIED")
    with pytest.raises(target.AdminInstallPlanError, match="proof"):
        target.prepare_admin_install_plan(
            replace(
                missing_boundary,
                independent_proofs=(forged, *missing_boundary.independent_proofs[1:]),
            )
        )


def test_duplicate_proof_is_refused(
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    duplicate = missing_boundary.independent_proofs[0]
    with pytest.raises(target.AdminInstallPlanError, match="proof"):
        target.prepare_admin_install_plan(
            replace(
                missing_boundary,
                independent_proofs=(
                    missing_boundary.independent_proofs[0],
                    duplicate,
                    *missing_boundary.independent_proofs[2:],
                ),
            )
        )


def test_bad_boundary_type_refuses() -> None:
    with pytest.raises(target.AdminInstallPlanError, match="type"):
        target.prepare_admin_install_plan(SimpleNamespace())  # type: ignore[arg-type]


def test_non_windows_refuses_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="posix"))

    def forbidden() -> None:
        raise AssertionError("must not probe")

    monkeypatch.setattr(target, "inspect_windows_service_install_boundary", forbidden)
    with pytest.raises(target.AdminInstallPlanError, match="Windows"):
        target.inspect_windows_admin_install_plan()


def test_observer_failure_is_not_bypassed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))

    def refused() -> None:
        raise ServiceInstallBoundaryError("denied")

    monkeypatch.setattr(target, "inspect_windows_service_install_boundary", refused)
    with pytest.raises(target.AdminInstallPlanError, match="unavailable"):
        target.inspect_windows_admin_install_plan()


def test_actual_boundary_dispatch(
    monkeypatch: pytest.MonkeyPatch, missing_boundary: ServiceInstallBoundaryReview
) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        target, "inspect_windows_service_install_boundary", lambda: missing_boundary
    )
    assert (
        target.inspect_windows_admin_install_plan().status
        == "ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED"
    )


def test_cli_missing_returns_two_and_no_grants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    monkeypatch.setattr(
        target,
        "inspect_windows_admin_install_plan",
        lambda: target.prepare_admin_install_plan(missing_boundary),
    )
    assert target.main([]) == 2
    out = capsys.readouterr().out
    obj = json.loads(out.split("\n" + target._NO_AUTHORITY)[0])
    assert len(obj["phases"]) == 7
    assert obj["authorized_to_register_service"] is False
    assert obj["authorized_to_activate_or_launch"] is False
    assert not any(phase["authorized_for_execution"] for phase in obj["phases"])


def test_cli_observed_returns_zero_but_still_no_grants(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing_boundary: ServiceInstallBoundaryReview,
) -> None:
    observed = replace(
        missing_boundary,
        status="INSTALLED_METADATA_ONLY_SECURITY_PROOFS_REQUIRED",
        directory_observation="PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY",
        service_observation="SERVICE_METADATA_OBSERVED_UNVERIFIED",
        missing_directory_purposes=(),
        blockers=("ADMINISTRATIVE_IDENTITY_AND_SECURITY_PROOFS_OUTSTANDING",),
    )
    monkeypatch.setattr(
        target,
        "inspect_windows_admin_install_plan",
        lambda: target.prepare_admin_install_plan(observed),
    )
    assert target.main([]) == 0
    output = capsys.readouterr().out
    assert target._NO_AUTHORITY in output
    assert '"authorized_to_create_directories": false' in output


def test_cli_refusal_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def deny() -> target.AdminInstallPlanReview:
        raise target.AdminInstallPlanError("denied")

    monkeypatch.setattr(target, "inspect_windows_admin_install_plan", deny)
    assert target.main([]) == 1
    assert target._NO_AUTHORITY in capsys.readouterr().err
