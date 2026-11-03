"""Slice 131: SCM open-rights are observations, never installer approval."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/service_token_access_probe.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
HELPER = ROOT / "native/windows/bootstrap/qualify_native_admin_token.ps1"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-131-current-token-scm-access.md"


def test_exact_assets_and_old_gate_limits() -> None:
    for item in (CPP, CMAKE, HELPER, GATE, DOC):
        assert item.is_file()
        assert 100 < item.stat().st_size < 28000
    assert GATE.stat().st_size < 16_000


def test_fixed_service_and_current_process_token_only() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        'L"PaperDataSuiteService"',
        "OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT)",
        "OpenServiceW(scm.get(), kService, SERVICE_QUERY_STATUS)",
        "OpenServiceW(scm, kService, desired)",
        "GetLastError() == ERROR_SERVICE_DOES_NOT_EXIST",
        "GetLastError() == ERROR_ACCESS_DENIED",
        "CloseServiceHandle(handle_)",
    ):
        assert phrase in source
    for forbidden in ("LogonUser", "DuplicateToken", "OpenProcessToken", "Impersonate"):
        assert forbidden not in source


@pytest.mark.parametrize(
    "right",
    (
        "SERVICE_CHANGE_CONFIG",
        "DELETE",
        "WRITE_DAC",
        "WRITE_OWNER",
        "SERVICE_START",
        "SERVICE_STOP",
        "SERVICE_PAUSE_CONTINUE",
        "SERVICE_USER_DEFINED_CONTROL",
    ),
)
def test_scm_rights_evaluated_individually(right: str) -> None:
    source = CPP.read_text(encoding="utf-8")
    assert f"right_granted(scm.get(), {right}, " in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "CreateServiceW(",
        "DeleteService(",
        "ChangeServiceConfigW(",
        "ChangeServiceConfig2W(",
        "SetServiceObjectSecurity(",
        "StartServiceW(",
        "ControlService(",
        "AdjustTokenPrivileges(",
        "CreateFileW(",
        "WriteFile(",
        "CreateProcessW(",
        "RegSetValue",
    ),
)
def test_no_privileged_mutation_calls(forbidden: str) -> None:
    assert forbidden not in CPP.read_text(encoding="utf-8")


def test_outputs_always_withhold_authority() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        'independent_teacher_token_verified\\":false',
        'service_identity_verified\\":false',
        'protected_state_write_performed\\":false',
        'authorized_to_provision\\":false',
        'authorized_to_install\\":false',
        "PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY",
        "SCM_CURRENT_TOKEN_ACCESS_QUERY_REFUSED_NO_AUTHORITY",
        "SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED",
        "REFUSED_UNSUPPORTED_SERVICE_ACCESS_ARGUMENT",
    ):
        assert phrase in source


def test_cmake_target_is_warnings_as_errors() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    assert (
        "add_executable(pds_windows_service_access_probe "
        "service_token_access_probe.cpp)" in cmake
    )
    assert "pds_windows_service_access_probe PRIVATE advapi32" in cmake
    assert "pds_windows_service_access_probe PRIVATE cxx_std_17" in cmake
    assert "pds_windows_service_access_probe PRIVATE /W4 /WX /permissive- /sdl" in cmake
    assert "pds_windows_service_scm_probe" in cmake


def test_build_and_machine_verification_precede_cross_arch_return() -> None:
    source = HELPER.read_text(encoding="utf-8")
    for phrase in (
        "--target pds_windows_service_access_probe --parallel 2",
        "SLICE131_SCM_ACCESS_COMPILED_$Architecture",
        "ToUInt16($accessBytes, $accessOffset + 4) -ne $expected",
        "if ($hostArchitecture -eq $Architecture)",
        "SLICE131_NATIVE_SCM_CURRENT_TOKEN_NO_AUTHORITY_PASSED_$Architecture",
    ):
        assert phrase in source
    assert source.index("SLICE131_SCM_ACCESS_COMPILED_$Architecture") < source.index(
        "if ($hostArchitecture -ne $Architecture)"
    )


def test_native_runtime_and_refusal_are_required() -> None:
    script = HELPER.read_text(encoding="utf-8")
    for phrase in (
        "@(& $accessExe)",
        "@(& $accessExe --configure)",
        "REFUSED_UNSUPPORTED_SERVICE_ACCESS_ARGUMENT",
        "$access.independent_teacher_token_verified -cne $false",
        "$access.authorized_to_install -cne $false",
        "$access.protected_state_write_performed -cne $false",
        "$refused.authorized_to_provision -cne $false",
    ):
        assert phrase in script
    assert script.rstrip().endswith(
        'Write-Host "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture"\nexit 0'
    )
    assert "@(& $scmExe --install)" in script
    assert "@(& $exe --provision)" in script


def test_docs_defer_true_teacher_access_acceptance() -> None:
    doc = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "current process",
        "provisional",
        "ordinary teacher",
        "not authenticated",
        "read-only",
        "no provisioning",
        "no installation",
        "x64",
        "arm64",
        "no protected writes",
    ):
        assert phrase in doc
