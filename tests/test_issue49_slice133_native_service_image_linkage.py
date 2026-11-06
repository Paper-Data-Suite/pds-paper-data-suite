"""Slice 133: native SCM/process image agreement remains non-authorizing."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native/windows/bootstrap/service_image_linkage_probe.cpp"
HEADER = ROOT / "native/windows/bootstrap/service_image_linkage.h"
UNIT = ROOT / "native/windows/bootstrap/service_image_linkage_test.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
HELPER = ROOT / "native/windows/bootstrap/qualify_native_admin_token.ps1"
MAIN = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-133-native-service-image-linkage.md"


def test_exact_assets_and_prior_win_gate_preserved() -> None:
    for item in (NATIVE, HEADER, UNIT, CMAKE, HELPER, MAIN, DOC):
        assert item.is_file()
        assert 100 < item.stat().st_size < 30_000
    assert len(MAIN.read_bytes().replace(b"\r\n", b"\n")) < 16_000
    assert (
        MAIN.read_text(encoding="utf-8")
        .rstrip()
        .endswith(
            'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\n'
            "exit 0"
        )
    )


def test_native_probe_uses_one_fixed_service_and_os_known_folder() -> None:
    source = NATIVE.read_text(encoding="utf-8")
    for token in (
        'L"PaperDataSuiteService"',
        "OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT)",
        "SERVICE_QUERY_CONFIG | SERVICE_QUERY_STATUS",
        "QueryServiceConfigW(",
        "QueryServiceStatusEx(",
        "SERVICE_WIN32_OWN_PROCESS",
        "SERVICE_RUNNING",
        "OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION",
        "QueryFullProcessImageNameW(",
        "SHGetKnownFolderPath(FOLDERID_ProgramFiles",
        "FILE_FLAG_OPEN_REPARSE_POINT",
        "GetFileInformationByHandle(",
        "GetFinalPathNameByHandleW(",
        "VOLUME_NAME_DOS",
        "FILE_ATTRIBUTE_REPARSE_POINT",
        "attributes.nNumberOfLinks != 1",
    ):
        assert token in source


def test_checked_service_image_string_is_bounded() -> None:
    source = NATIVE.read_text(encoding="utf-8")
    for token in (
        "bytes_needed > 8192",
        "capacity > 8192",
        "length > 4098",
        "at < begin",
        "length == capacity",
        "std::wstring configured",
        "read_configured_image(config_bytes, config->lpBinaryPathName, configured)",
    ):
        assert token in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "CreateServiceW(",
        "ChangeServiceConfigW(",
        "DeleteService(",
        "StartServiceW(",
        "ControlService(",
        "SetServiceObjectSecurity(",
        "WriteFile(",
        "RegSetValue",
        "CreateProcessW(",
        "ShellExecuteW(",
        "AdjustTokenPrivileges(",
        "ImpersonateLoggedOnUser(",
        "CryptSignMessage(",
    ),
)
def test_no_service_mutation_or_privilege_escalation(forbidden: str) -> None:
    assert forbidden not in NATIVE.read_text(encoding="utf-8")


def test_native_success_remains_explicitly_untrusted() -> None:
    source = NATIVE.read_text(encoding="utf-8")
    for token in (
        'installed_service_identity_verified\\":false',
        'executable_custody_verified\\":false',
        'independent_teacher_identity_attested\\":false',
        'publisher_pin_verified\\":false',
        'protected_write_performed\\":false',
        'authorized_to_install\\":false',
        "PROVISIONAL_SERVICE_NOT_INSTALLED_NO_IMAGE_ACCEPTANCE",
        "SERVICE_NOT_RUNNING_NO_IMAGE_ACCEPTANCE",
        "SERVICE_IMAGE_QUERY_REFUSED_NO_ACCEPTANCE",
        "SCM_PROCESS_IMAGE_LINKAGE_OBSERVED_UNVERIFIED",
        "REFUSED_UNSUPPORTED_SERVICE_IMAGE_ARGUMENT",
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY",
    ):
        assert token in source


def test_pure_comparison_is_strictly_canonical() -> None:
    source = HEADER.read_text(encoding="utf-8")
    for token in (
        "canonical_drive_path",
        "claimed_image_linkage",
        "equal_ascii_nocase",
        "required_root",
        'L"\\\\Paper Data Suite\\\\"',
        "service_command.find(L' ')",
        "program_files_root",
        "observed_process_image",
        "service_command.remove_prefix(1)",
        "service_command.remove_suffix(1)",
        "value.size() > 4096",
    ):
        assert token in source


@pytest.mark.parametrize(
    "case",
    (
        "canonical-quoted",
        "ascii-case-fold",
        "bounded-child",
        "unquoted-space",
        "argument-injection",
        "trailing-argument-space",
        "unterminated-quote",
        "process-mismatch",
        "process-drive-mismatch",
        "prefix-confusion",
        "dotdot",
        "dot-segment",
        "alternate-stream",
        "non-exe",
        "environment-expansion",
        "network-image",
        "device-path",
        "nonascii-process",
        "double-slash",
        "different-known-folder",
        "oversize-command",
    ),
)
def test_portable_negative_contract_case_exists(case: str) -> None:
    assert f'"{case}"' in UNIT.read_text(encoding="utf-8")


def test_windows_cmake_builds_both_native_contract_targets() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    for token in (
        (
            "add_executable(pds_service_image_contract_test "
            "service_image_linkage_test.cpp)"
        ),
        "pds_service_image_contract_test PRIVATE cxx_std_17",
        "pds_service_image_contract_test PRIVATE /W4 /WX /permissive- /sdl",
        (
            "add_executable(pds_windows_service_image_probe "
            "service_image_linkage_probe.cpp)"
        ),
        "pds_windows_service_image_probe PRIVATE cxx_std_17",
        "pds_windows_service_image_probe PRIVATE advapi32 shell32 ole32",
        "pds_windows_service_image_probe PRIVATE /W4 /WX /permissive- /sdl",
        "pds_windows_service_image_probe PRIVATE -Wall -Wextra -Werror",
    ):
        assert token in cmake


def test_native_gate_requires_pe_architecture_and_native_executions() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    for token in (
        "--target pds_service_image_contract_test pds_windows_service_image_probe",
        "SLICE133_SERVICE_IMAGE_COMPILED_$Architecture",
        "ToUInt16($imageBytes, $imageOffset + 4) -ne $expected",
        "@(& $imageContractExe)",
        "SLICE133_NATIVE_SERVICE_IMAGE_CONTRACT_TESTS_PASSED",
        "@(& $imageExe)",
        "@(& $imageExe --approve)",
        "SLICE133_NATIVE_SERVICE_IMAGE_NONAUTHORITY_PASSED_$Architecture",
        "$image.installed_service_identity_verified -cne $false",
        "$image.executable_custody_verified -cne $false",
    ):
        assert token in helper
    assert helper.index("SLICE133_SERVICE_IMAGE_COMPILED_$Architecture") < (
        helper.index("if ($hostArchitecture -ne $Architecture)")
    )
    assert helper.index("if ($hostArchitecture -ne $Architecture)") < (
        helper.index("@(& $imageContractExe)")
    )
    assert helper.rstrip().endswith(
        'Write-Host "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture"\nexit 0'
    )


def test_no_earlier_native_refusal_contract_removed() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    for text in (
        "@(& $exe --provision)",
        "@(& $scmExe --install)",
        "@(& $accessExe --configure)",
        "@(& $teacherExe --accept)",
        "SLICE132_NATIVE_TEACHER_DENIAL_NONAUTHORITY_PASSED_$Architecture",
    ):
        assert text in helper


def test_documentation_delegates_actual_installed_machine_acceptance() -> None:
    note = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "provisional service",
        "read-only",
        "program files",
        "running process",
        "reparse",
        "ordinary teacher",
        "not authenticated",
        "not executable custody",
        "no provisioning",
        "no installation",
        "x64",
        "arm64",
    ):
        assert phrase in note
