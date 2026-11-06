"""Slice 128: read-only native pin custody never grants trust authority."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/publisher_pin_custody_probe.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
GATE = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-128-pin-custody-probe.md"


def _cpp() -> str:
    return CPP.read_text(encoding="utf-8")


def test_new_files_are_bounded_and_present() -> None:
    for path in (CPP, CMAKE, GATE, DOC):
        assert path.is_file()
        assert 100 < path.stat().st_size < 24_000


def test_fixed_programdata_root_from_windows_known_folders() -> None:
    source = _cpp()
    assert "SHGetKnownFolderPath(FOLDERID_ProgramData" in source
    assert "CoTaskMemFree(raw)" in source
    assert "GetEnvironmentVariableW" not in source
    assert "_wgetenv" not in source


@pytest.mark.parametrize(
    "segment",
    (
        "Paper Data Suite",
        "service-state",
        "publisher-pin-v1.json",
    ),
)
def test_only_fixed_policy_paths(segment: str) -> None:
    assert segment in _cpp()


def test_all_ancestors_and_policy_handle_held_during_read() -> None:
    source = _cpp()
    assert "HeldHandle root, app_dir, state_dir, policy_file;" in source
    assert "open_fixed(base, true, true, root)" in source
    assert "open_fixed(app, true, false, app_dir)" in source
    assert "open_fixed(state, true, false, state_dir)" in source
    assert "open_fixed(pin, false, false, policy_file)" in source
    assert "bounded_policy_read(policy_file.get(), content)" in source


def test_no_creation_and_no_write_share() -> None:
    source = _cpp()
    assert "CreateFileW(" in source
    assert "OPEN_EXISTING" in source
    assert "FILE_SHARE_READ" in source
    assert "READ_CONTROL | FILE_READ_ATTRIBUTES" in source
    assert "FILE_READ_DATA" in source
    assert "FILE_FLAG_OPEN_REPARSE_POINT" in source
    assert "FILE_FLAG_BACKUP_SEMANTICS" in source


def test_acl_owner_reparse_and_hardlink_checks() -> None:
    source = _cpp()
    for token in (
        "GetSecurityInfo(",
        "OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION",
        "IsValidSid(",
        "EqualSid(",
        "GetAclInformation(",
        "GetAce(",
        "ACCESS_ALLOWED_ACE_TYPE",
        "INHERIT_ONLY_ACE",
        "FILE_ATTRIBUTE_REPARSE_POINT",
        "FILE_ATTRIBUTE_DIRECTORY",
        "nNumberOfLinks != 1",
        "GENERIC_WRITE | GENERIC_ALL",
    ):
        assert token in source


def test_bounded_native_policy_claim_parser() -> None:
    source = _cpp()
    assert "pds_publisher_pin_contract::kMaxBytes" in source
    assert "GetFileSizeEx(" in source
    assert "ReadFile(" in source
    assert "parse_claimed_pin(content, parsed)" in source
    assert "length.QuadPart <= 0" in source
    assert "count != static_cast<DWORD>(length.QuadPart)" in source


def test_raii_closes_win32_handles_and_os_allocations() -> None:
    source = _cpp()
    assert "~HeldHandle()" in source
    assert "CloseHandle(h_)" in source
    assert "~AllocatedLocal()" in source
    assert "LocalFree(p_)" in source
    assert "HeldHandle(const HeldHandle&) = delete" in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "CREATE_ALWAYS",
        "CREATE_NEW",
        "OPEN_ALWAYS",
        "WriteFile(",
        "MoveFileExW(",
        "SetNamedSecurityInfoW(",
        "CreateServiceW(",
        "StartServiceW(",
        "CreateProcessW(",
        "ShellExecuteW(",
    ),
)
def test_native_probe_has_no_mutating_api(forbidden: str) -> None:
    assert forbidden not in _cpp()


def test_every_result_is_non_authorizing() -> None:
    source = _cpp()
    for text in (
        "NATIVE_PIN_CLAIM_NOT_OBSERVED",
        "NATIVE_PIN_CLAIM_OBSERVED_CUSTODY_UNPROVEN",
        "REFUSED_UNSUPPORTED_PUBLISHER_PIN_ARGUMENT",
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY",
        'independent_provisioner_authenticated\\":false',
        'rollback_protection_verified\\":false',
        'publisher_pin_verified\\":false',
        'authorized_to_install\\":false',
    ):
        assert text in source
    assert "return observed ? 2 : 1;" in source


def test_build_target_is_windows_native_and_warning_clean() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    assert (
        "add_executable(pds_windows_publisher_pin_custody_probe "
        "publisher_pin_custody_probe.cpp)" in cmake
    )
    assert "pds_windows_publisher_pin_custody_probe PRIVATE cxx_std_17" in cmake
    assert "pds_windows_publisher_pin_custody_probe PRIVATE /W4 /WX" in cmake
    assert "pds_windows_publisher_pin_custody_probe PRIVATE advapi32" in cmake


def test_ci_build_and_architecture_gate() -> None:
    source = GATE.read_text(encoding="utf-8")
    for text in (
        "--target pds_windows_publisher_pin_custody_probe --parallel 2",
        "[System.IO.File]::ReadAllBytes($pinCustodyExe)",
        "ToUInt16($pinImage, $pinOffset + 4)",
        "if ($pinMachine -ne $expectedMachine)",
        "SLICE128_NATIVE_PIN_CUSTODY_TARGET_VERIFIED_$Architecture",
        "SLICE128_NATIVE_PIN_CUSTODY_NO_AUTHORITY_PASSED_$Architecture",
    ):
        assert text in source


def test_runtime_refuses_install_and_cannot_provision() -> None:
    source = GATE.read_text(encoding="utf-8")
    assert "@(& $pinCustodyExe)" in source
    assert "@(& $pinCustodyExe --install)" in source
    assert "$pinDeniedCode -ne 2" in source
    assert "$pinResult.publisher_pin_verified -cne $false" in source
    assert "$pinResult.authorized_to_install -cne $false" in source
    assert "$pinResult.rollback_protection_verified -cne $false" in source
    assert source.index("if ($Architecture -ne $hostArchitecture)") < source.index(
        "@(& $pinCustodyExe)"
    )


def test_prior_success_exit_and_security_obligations_preserved() -> None:
    source = GATE.read_text(encoding="utf-8")
    assert source.rstrip().endswith(
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\nexit 0'
    )
    for text in (
        "SLICE123_NATIVE_ARM64_RUNTIME_PASSED",
        "SLICE125_NATIVE_UNSIGNED_SIGNATURE_AND_INSTALL_REFUSAL_PASSED",
        "SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_PASSED_$Architecture",
        "SLICE127_NATIVE_PUBLISHER_EVIDENCE_PASSED_$Architecture",
    ):
        assert text in source


def test_docs_do_not_claim_provisioning_or_rollback_protection() -> None:
    content = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "not provisioned",
        "not independently authenticated",
        "not rollback resistant",
        "no installation",
        "read-only",
        "arm64",
        "service-state",
    ):
        assert phrase in content
