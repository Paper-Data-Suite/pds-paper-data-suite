"""Slice 121: source-level native bootstrap audit, not Windows binary acceptance."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native/windows/bootstrap/bootstrap_probe.cpp"
BUILD = ROOT / "native/windows/bootstrap/CMakeLists.txt"
SPEC = (
    ROOT / "docs/architecture/issue-49-slice-121-native-windows-bootstrap-prototype.md"
)


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_native_source_and_build_metadata_exist() -> None:
    assert SOURCE.is_file()
    assert BUILD.is_file()
    assert SPEC.is_file()
    assert SOURCE.stat().st_size < 40_000


def test_standalone_cxx17_windows_only_project() -> None:
    cmake = BUILD.read_text(encoding="utf-8")
    assert "LANGUAGES CXX" in cmake
    assert "cxx_std_17" in cmake
    assert "if(NOT WIN32)" in cmake
    assert "message(FATAL_ERROR" in cmake
    assert "bootstrap_probe.cpp" in cmake
    assert "advapi32 shell32 ole32" in cmake
    assert "add_executable(pds_windows_bootstrap_probe" in cmake


def test_native_entry_has_no_user_supplied_path_or_approval_argument() -> None:
    source = _source()
    assert "int wmain(int argc, wchar_t* argv[])" in source
    assert "argc != 1" in source
    assert "--apply" in source
    assert "--approve" in source
    assert "REFUSED_UNSUPPORTED_NATIVE_BOOTSTRAP_ARGUMENT" in source


def test_programdata_root_is_os_known_folder_not_environment() -> None:
    source = _source()
    assert "SHGetKnownFolderPath(FOLDERID_ProgramData" in source
    assert "CoTaskMemFree(raw)" in source
    assert "GetEnvironmentVariableW" not in source
    assert "_wgetenv" not in source


@pytest.mark.parametrize(
    "fixed_name",
    [
        "Paper Data Suite",
        "service-state",
        "installer-checkpoint-v1.json",
        "installer-intent-journal-v1.json",
    ],
    ids=("app", "state", "checkpoint", "journal"),
)
def test_only_known_protected_paths(fixed_name: str) -> None:
    assert fixed_name in _source()


def test_held_file_and_parent_handles() -> None:
    source = _source()
    assert "Handle root, app_dir, state_dir, checkpoint_file, journal_file;" in source
    assert "open_checked(base, true, true, root)" in source
    assert "open_checked(checkpoint, false, false, checkpoint_file)" in source
    assert "open_checked(journal, false, false, journal_file)" in source
    assert "bounded_read(checkpoint_file.get(), checkpoint_bytes)" in source
    assert "bounded_read(journal_file.get(), journal_bytes)" in source


def test_opening_is_noncreating_and_nonwriting() -> None:
    source = _source()
    assert "CreateFileW(" in source
    assert "OPEN_EXISTING" in source
    assert "FILE_SHARE_READ" in source
    assert "READ_CONTROL | FILE_READ_ATTRIBUTES" in source
    assert "FILE_READ_DATA" in source
    assert "FILE_FLAG_OPEN_REPARSE_POINT" in source
    for forbidden in (
        "CREATE_ALWAYS",
        "CREATE_NEW",
        "OPEN_ALWAYS",
        "TRUNCATE_EXISTING",
        "FILE_WRITE_DATA,",
        "WriteFile(",
        "ReplaceFileW(",
        "MoveFileExW(",
        "FlushFileBuffers(",
        "StartServiceW(",
        "CreateServiceW(",
        "ShellExecuteW(",
        "CreateProcessW(",
    ):
        assert forbidden not in source


def test_reparse_hardlink_and_file_kind_refusal() -> None:
    source = _source()
    assert "GetFileInformationByHandle(" in source
    assert "FILE_ATTRIBUTE_REPARSE_POINT" in source
    assert "FILE_ATTRIBUTE_DIRECTORY" in source
    assert "nNumberOfLinks != 1" in source


def test_real_acl_owner_and_dacl_inspection() -> None:
    source = _source()
    assert "GetSecurityInfo(" in source
    assert "OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION" in source
    assert "IsValidSid(" in source
    assert "EqualSid(" in source
    assert "GetAce(" in source
    assert "ACCESS_ALLOWED_ACE_TYPE" in source
    assert "INHERIT_ONLY_ACE" in source
    assert "kParentDanger" in source
    assert "kMutationMask" in source
    assert "!privileged_sid(principal)" in source


@pytest.mark.parametrize(
    "sid",
    [
        "S-1-5-18",
        "S-1-5-32-544",
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
    ],
    ids=("system", "administrators", "trusted-installer"),
)
def test_allowed_privileged_sids_are_explicit(sid: str) -> None:
    assert sid in _source()


def test_bounded_read_never_exports_raw_evidence() -> None:
    source = _source()
    assert "GetFileSizeEx(" in source
    assert "ReadFile(" in source
    assert "kMaxRecord = 4096" in source
    assert "length.QuadPart <= 0" in source
    assert "length.QuadPart > static_cast<LONGLONG>(kMaxRecord)" in source
    assert '"native_read_only"' not in source  # JSON is escaped in C++ literal
    assert "checkpoint_bytes.data()" not in source
    assert "journal_bytes.data()" not in source


def test_all_handle_and_os_allocations_have_raii_cleanup() -> None:
    source = _source()
    assert "~Handle()" in source
    assert "CloseHandle(handle_)" in source
    assert "~LocalMemory()" in source
    assert "LocalFree(ptr)" in source
    assert "CoTaskMemFree(raw)" in source
    assert "Handle(const Handle&) = delete" in source


def test_every_result_explicitly_denies_approval() -> None:
    source = _source()
    assert (
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY"
        in source
    )
    for phrase in (
        'administrator_authenticated\\":false',
        'service_identity_verified\\":false',
        'production_authority\\":false',
        'active_receipt_authority\\":false',
    ):
        assert phrase in source
    assert "return observed ? 2 : 1;" in source


def test_documentation_distinguishes_source_from_native_acceptance() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    assert "not native windows integration tests" in spec.lower()
    assert "not cryptographically authenticated" in spec
    assert "not" in spec.lower()
    assert "ordinary teacher-token negative tests" in spec
