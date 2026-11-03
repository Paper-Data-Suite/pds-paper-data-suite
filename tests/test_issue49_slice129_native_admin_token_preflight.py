"""Slice 129: native admin token signals never confer provisioning authority."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/publisher_pin_admin_preflight.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
HELPER = ROOT / "native/windows/bootstrap/qualify_native_admin_token.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-129-admin-token-preflight.md"


def test_exact_assets_and_bounds() -> None:
    for path in (CPP, CMAKE, GATE, HELPER, DOC):
        assert path.is_file()
        assert 200 < path.stat().st_size < 28000


def test_token_query_is_the_current_process_primary_token() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        "OpenProcessToken(GetCurrentProcess()",
        "TOKEN_QUERY | TOKEN_DUPLICATE",
        "GetTokenInformation(primary.get(), TokenElevation",
        "GetTokenInformation(primary.get(), TokenIntegrityLevel",
        "SECURITY_MANDATORY_HIGH_RID",
        "DuplicateToken(primary.get(), SecurityIdentification",
        "CheckTokenMembership(impersonation.get()",
        "DOMAIN_ALIAS_RID_ADMINS",
    ):
        assert phrase in source


def test_sids_and_handles_are_owned_and_checked() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        "~Handle()",
        "CloseHandle(value_)",
        "~OwnedSid()",
        "FreeSid(value_)",
        "GetSidSubAuthorityCount(integrity)",
        "GetSidSubAuthority(integrity",
        "IsValidSid(integrity)",
        "ERROR_INSUFFICIENT_BUFFER",
        "needed > 2048",
    ):
        assert phrase in source


def test_all_outputs_withhold_provisioning_and_install_authority() -> None:
    source = CPP.read_text(encoding="utf-8")
    for phrase in (
        'independent_administrator_authenticated\\":false',
        'protected_provisioning_performed\\":false',
        'publisher_pin_provisioned\\":false',
        'rollback_protection_verified\\":false',
        'authorized_to_install\\":false',
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY",
        "NATIVE_TOKEN_SIGNALS_OBSERVED_NO_AUTHORITY",
        "NATIVE_TOKEN_PREFLIGHT_INSUFFICIENT_NO_AUTHORITY",
        "NATIVE_TOKEN_PREFLIGHT_UNAVAILABLE_NO_AUTHORITY",
        "REFUSED_UNSUPPORTED_PROVISIONING_ARGUMENT",
    ):
        assert phrase in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "WriteFile(",
        "CreateFileW(",
        "CreateServiceW(",
        "StartServiceW(",
        "AdjustTokenPrivileges(",
        "SetTokenInformation(",
        "RegSetValue",
        "SetNamedSecurityInfo",
        "ShellExecuteW(",
        "CreateProcessW(",
    ),
)
def test_no_native_mutation_or_elevation(forbidden: str) -> None:
    assert forbidden not in CPP.read_text(encoding="utf-8")


def test_cmake_uses_standalone_msvc_warning_gate() -> None:
    source = CMAKE.read_text(encoding="utf-8")
    assert "add_executable(pds_windows_pin_admin_preflight" in source
    assert "publisher_pin_admin_preflight.cpp" in source
    assert "pds_windows_pin_admin_preflight PRIVATE cxx_std_17" in source
    assert "pds_windows_pin_admin_preflight PRIVATE advapi32" in source
    assert "pds_windows_pin_admin_preflight PRIVATE /W4 /WX /permissive- /sdl" in source


def test_native_ci_build_and_runtime_refusal_is_mandatory() -> None:
    source = HELPER.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    assert "--target pds_windows_pin_admin_preflight --parallel 2" in gate
    assert "qualify_native_admin_token.ps1" in gate
    assert "-Architecture $Architecture -Build $build -NoAuthority $noAuthority" in gate
    for phrase in (
        "SLICE129_NATIVE_TOKEN_PREFLIGHT_COMPILED_$Architecture",
        "ToUInt16($bytes, $peOffset + 4)",
        "@(& $exe)",
        "@(& $exe --provision)",
        "REFUSED_UNSUPPORTED_PROVISIONING_ARGUMENT",
        "SLICE129_NATIVE_ADMIN_TOKEN_NO_AUTHORITY_PASSED_$Architecture",
        "$data.independent_administrator_authenticated -cne $false",
        "$data.publisher_pin_provisioned -cne $false",
        "$data.authorized_to_install -cne $false",
    ):
        assert phrase in source
    assert source.index("if ($hostArchitecture -ne $Architecture)") < source.index(
        "@(& $exe)"
    )
    assert gate.rstrip().endswith(
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\nexit 0'
    )


def test_documentation_separates_token_observation_from_real_authority() -> None:
    doc = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "primary token",
        "administrator",
        "not independent administrator authentication",
        "no provisioning",
        "no protected writes",
        "no rollback protection",
        "no installation",
        "x64",
        "arm64",
    ):
        assert phrase in doc
