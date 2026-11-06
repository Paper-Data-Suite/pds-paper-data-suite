"""Slice 132: current-token SCM denials never grant installer authority."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/teacher_service_denial_probe.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
HELPER = ROOT / "native/windows/bootstrap/qualify_native_admin_token.ps1"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-132-teacher-service-denial.md"


def test_source_assets_present_and_old_gate_unchanged() -> None:
    for item in (CPP, CMAKE, HELPER, GATE, DOC):
        assert item.is_file()
        assert 100 < item.stat().st_size < 30000
    assert len(GATE.read_bytes().replace(b"\r\n", b"\n")) < 16000
    assert (
        GATE.read_text(encoding="utf-8")
        .rstrip()
        .endswith(
            'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\n'
            "exit 0"
        )
    )


def test_current_primary_token_not_impersonated() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        "OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY",
        "TokenElevation, &elevation",
        "TokenElevationType, &kind",
        "kind != TokenElevationTypeDefault",
        "TokenIntegrityLevel",
        "SECURITY_MANDATORY_MEDIUM_RID",
        "SECURITY_MANDATORY_HIGH_RID",
        "TokenGroups",
        "WinBuiltinAdministratorsSid",
        "EqualSid(sid, admin.data())",
    ):
        assert phrase in source
    for forbidden in (
        "LogonUser",
        "DuplicateToken",
        "Impersonate",
        "RevertToSelf",
        "AdjustTokenPrivileges",
    ):
        assert forbidden not in source


def test_group_parsing_is_bounded_and_includes_deny_only_membership() -> None:
    source = CPP.read_text(encoding="utf-8")
    for text in (
        "needed > 65536",
        "groups->GroupCount > 1024",
        "sizeof(SID_AND_ATTRIBUTES)",
        "IsValidSid(sid)",
        "EqualSid(sid, admin.data())",
        "GetTokenInformation(token.get(), TokenGroups",
    ):
        assert text in source


@pytest.mark.parametrize(
    "right",
    [
        "SERVICE_CHANGE_CONFIG",
        "DELETE",
        "WRITE_DAC",
        "WRITE_OWNER",
        "SERVICE_START",
        "SERVICE_STOP",
        "SERVICE_PAUSE_CONTINUE",
        "SERVICE_USER_DEFINED_CONTROL",
    ],
)
def test_each_sensitive_right_is_independently_requested(right: str) -> None:
    source = CPP.read_text(encoding="utf-8")
    assert right in source
    assert "for (DWORD right : rights)" in source
    assert "check_right(scm.get(), right, granted)" in source


@pytest.mark.parametrize(
    "forbidden",
    [
        "CreateServiceW(",
        "ChangeServiceConfigW(",
        "DeleteService(",
        "StartServiceW(",
        "ControlService(",
        "SetServiceObjectSecurity(",
        "WriteFile(",
        "CreateFileW(",
        "CreateProcessW(",
        "ShellExecuteW(",
        "RegSetValue",
        "CryptSignMessage(",
    ],
)
def test_probe_cannot_modify_system_state(forbidden: str) -> None:
    assert forbidden not in CPP.read_text(encoding="utf-8")


def test_service_absence_granted_right_and_query_failure_refuse() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        'L"PaperDataSuiteService"',
        "SC_MANAGER_CONNECT",
        "SERVICE_QUERY_STATUS",
        "ERROR_SERVICE_DOES_NOT_EXIST",
        "ERROR_ACCESS_DENIED",
        "SERVICE_NOT_INSTALLED_NO_TEACHER_ACCEPTANCE",
        "SERVICE_RIGHTS_QUERY_REFUSED_NO_ACCEPTANCE",
        "DANGEROUS_SCM_RIGHT_GRANTED_NO_ACCEPTANCE",
        "ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED",
    ):
        assert phrase in source


def test_output_always_refuses_authority_and_argument() -> None:
    source = CPP.read_text(encoding="utf-8")
    for text in (
        'independent_teacher_identity_attested\\":false',
        'installed_service_identity_verified\\":false',
        'publisher_pin_provisioned\\":false',
        'protected_write_performed\\":false',
        'authorized_to_install\\":false',
        "REFUSED_UNSUPPORTED_TEACHER_ACCEPTANCE_ARGUMENT",
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY",
        "argc != 1",
    ):
        assert text in source


def test_cmake_target_is_separate_with_warnings_as_errors() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    assert (
        "add_executable(pds_windows_teacher_denial_probe "
        "teacher_service_denial_probe.cpp)" in cmake
    )
    for text in (
        "pds_windows_teacher_denial_probe PRIVATE cxx_std_17",
        "pds_windows_teacher_denial_probe PRIVATE advapi32",
        "pds_windows_teacher_denial_probe PRIVATE /W4 /WX /permissive- /sdl",
        "pds_windows_teacher_denial_probe PRIVATE -Wall -Wextra -Werror",
    ):
        assert text in cmake


def test_native_pe_machine_verified_before_cross_arch_return() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    for phrase in (
        "--target pds_windows_teacher_denial_probe --parallel 2",
        "SLICE132_TEACHER_DENIAL_COMPILED_$Architecture",
        "ToUInt16($teacherBytes, $teacherOffset + 4) -ne $expected",
        "SLICE132_NATIVE_TEACHER_DENIAL_NONAUTHORITY_PASSED_$Architecture",
    ):
        assert phrase in helper
    assert helper.index("SLICE132_TEACHER_DENIAL_COMPILED_$Architecture") < (
        helper.index("if ($hostArchitecture -ne $Architecture)")
    )


def test_native_status_and_refusal_enforced_on_matching_cpu() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    for phrase in (
        "@(& $teacherExe)",
        "@(& $teacherExe --accept)",
        "$teacherCode -notin @(1, 2)",
        "$teacher.independent_teacher_identity_attested -cne $false",
        "$teacher.installed_service_identity_verified -cne $false",
        "$teacher.authorized_to_install -cne $false",
        "REFUSED_UNSUPPORTED_TEACHER_ACCEPTANCE_ARGUMENT",
        "ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED",
        "SLICE132_NATIVE_TEACHER_DENIAL_NONAUTHORITY_PASSED_$Architecture",
    ):
        assert phrase in helper
    assert helper.rstrip().endswith(
        'Write-Host "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture"\nexit 0'
    )
    assert "@(& $scmExe --install)" in helper
    assert "@(& $accessExe --configure)" in helper


def test_docs_limit_observation_and_actual_acceptance() -> None:
    note = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "primary token",
        "uac-filtered",
        "ordinary teacher",
        "separately authenticated",
        "service absent",
        "no provisioning",
        "no installation",
        "no protected writes",
        "x64",
        "arm64",
        "not production acceptance",
    ):
        assert phrase in note
