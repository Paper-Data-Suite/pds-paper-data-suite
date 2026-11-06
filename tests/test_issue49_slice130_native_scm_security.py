"""Slice 130: read-only SCM security inventory grants no authority."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/service_scm_security_probe.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
HELPER = ROOT / "native/windows/bootstrap/qualify_native_admin_token.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-130-native-scm-security.md"


def test_assets_are_bounded_and_existing_gate_is_preserved() -> None:
    for item in (CPP, CMAKE, GATE, HELPER, DOC):
        assert item.is_file()
        assert 100 < item.stat().st_size < 28000
    assert len(GATE.read_bytes().replace(b"\r\n", b"\n")) < 16_000
    assert (
        GATE.read_text(encoding="utf-8")
        .rstrip()
        .endswith(
            'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\n'
            "exit 0"
        )
    )


def test_fixed_provisional_service_and_minimal_scm_rights() -> None:
    source = CPP.read_text(encoding="utf-8")
    for text in (
        'L"PaperDataSuiteService"',
        "OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT)",
        "OpenServiceW(",
        "READ_CONTROL | SERVICE_QUERY_CONFIG",
        "ERROR_SERVICE_DOES_NOT_EXIST",
        "QueryServiceObjectSecurity(",
        "OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION",
        "QueryServiceConfig2W(",
        "SERVICE_CONFIG_SERVICE_SID_INFO",
    ):
        assert text in source


def test_acl_parser_is_bounded_and_unknown_ace_forms_refuse() -> None:
    source = CPP.read_text(encoding="utf-8")
    for text in (
        "needed > 8192",
        "IsValidSecurityDescriptor(descriptor)",
        "GetSecurityDescriptorOwner(",
        "GetSecurityDescriptorDacl(",
        "IsValidAcl(dacl)",
        "GetAclInformation(",
        "acl.AceCount > 128",
        "GetAce(dacl, index, &raw)",
        "ACCESS_ALLOWED_ACE_TYPE",
        "ACCESS_DENIED_ACE_TYPE",
        "SERVICE_CHANGE_CONFIG",
        "WRITE_DAC",
        "WRITE_OWNER",
    ):
        assert text in source


def test_service_sid_type_is_only_observed_not_authenticated() -> None:
    source = CPP.read_text(encoding="utf-8")
    for text in (
        "SERVICE_SID_TYPE_NONE",
        "SERVICE_SID_TYPE_UNRESTRICTED",
        "SERVICE_SID_TYPE_RESTRICTED",
        "observation.sid_type_observed = true",
        'service_identity_verified\\":false',
        'effective_teacher_rights_verified\\":false',
    ):
        assert text in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "CreateServiceW(",
        "ChangeServiceConfigW(",
        "ChangeServiceConfig2W(",
        "SetServiceObjectSecurity(",
        "DeleteService(",
        "StartServiceW(",
        "ControlService(",
        "CreateFileW(",
        "WriteFile(",
        "ShellExecuteW(",
        "CreateProcessW(",
        "AdjustTokenPrivileges(",
    ),
)
def test_no_scm_mutation_or_elevation(forbidden: str) -> None:
    assert forbidden not in CPP.read_text(encoding="utf-8")


def test_output_always_withholds_provisioning_and_installation() -> None:
    source = CPP.read_text(encoding="utf-8")
    for text in (
        'native_read_only\\":true',
        'publisher_pin_provisioned\\":false',
        'protected_state_write_performed\\":false',
        'authorized_to_provision\\":false',
        'authorized_to_install\\":false',
        "PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY",
        "SCM_SECURITY_QUERY_REFUSED_NO_AUTHORITY",
        "SCM_SECURITY_METADATA_OBSERVED_UNVERIFIED",
        "REFUSED_UNSUPPORTED_SCM_ARGUMENT",
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY",
    ):
        assert text in source


def test_cmake_native_target_keeps_msvc_warnings_as_errors() -> None:
    source = CMAKE.read_text(encoding="utf-8")
    assert (
        "add_executable(pds_windows_service_scm_probe "
        "service_scm_security_probe.cpp)" in source
    )
    assert "pds_windows_service_scm_probe PRIVATE cxx_std_17" in source
    assert "pds_windows_service_scm_probe PRIVATE advapi32" in source
    assert "pds_windows_service_scm_probe PRIVATE /W4 /WX /permissive- /sdl" in source


def test_cross_build_and_native_runtime_require_real_pe_machine() -> None:
    source = HELPER.read_text(encoding="utf-8")
    assert "--target pds_windows_service_scm_probe --parallel 2" in source
    assert "ToUInt16($scmBytes, $scmOffset + 4) -ne $expected" in source
    assert source.index("SLICE130_SCM_COMPILED_$Architecture") < source.index(
        "if ($hostArchitecture -ne $Architecture)"
    )
    assert source.index("if ($hostArchitecture -ne $Architecture)") < source.index(
        "@(& $scmExe)"
    )
    assert "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture" in source


def test_native_runtime_refuses_mutation_switch_and_unauthorized_claims() -> None:
    source = HELPER.read_text(encoding="utf-8")
    for text in (
        "@(& $scmExe)",
        "@(& $scmExe --install)",
        "REFUSED_UNSUPPORTED_SCM_ARGUMENT",
        "$scm.authorized_to_install -cne $false",
        "$scm.authorized_to_provision -cne $false",
        "$scm.service_identity_verified -cne $false",
        "$scm.effective_teacher_rights_verified -cne $false",
    ):
        assert text in source


def test_earlier_slice129_qualification_is_preserved() -> None:
    source = HELPER.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    assert "--target pds_windows_pin_admin_preflight --parallel 2" in gate
    assert "@(& $exe --provision)" in source
    assert "SLICE129_NATIVE_ADMIN_TOKEN_NO_AUTHORITY_PASSED_$Architecture" in source


def test_documentation_requires_true_independent_service_proof() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "provisional",
        "read-only",
        "service-object",
        "service sid",
        "ordinary teacher",
        "no provisioning",
        "no installation",
        "x64",
        "arm64",
        "not independently authenticated",
    ):
        assert phrase in text
