"""Suite #49 Slice 125: native Authenticode witness is an observation, not approval."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "native/windows/bootstrap/signature_probe.cpp"
CMAKE = ROOT / "native/windows/bootstrap/CMakeLists.txt"
RUN = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
DOC = ROOT / "docs/architecture/issue-49-slice-125-native-signature-witness.md"


def test_exact_files_present() -> None:
    for path in (CPP, CMAKE, RUN, DOC):
        assert path.is_file()
        assert 1 <= path.stat().st_size < 20000


def test_signing_witness_uses_only_own_module_path() -> None:
    source = CPP.read_text(encoding="utf-8")
    assert "GetModuleFileNameW(nullptr, path.data()" in source
    assert "used == 0 || used >= path.size()" in source
    assert "GetEnvironmentVariableW" not in source
    assert "GetCommandLineW" not in source
    assert "argc != 1" in source


def test_wintrust_request_is_explicit_and_offline() -> None:
    source = CPP.read_text(encoding="utf-8")
    for token in (
        "WINTRUST_ACTION_GENERIC_VERIFY_V2",
        "WinVerifyTrust(nullptr, &action, &request)",
        "WTD_UI_NONE",
        "WTD_REVOKE_WHOLECHAIN",
        "WTD_CHOICE_FILE",
        "WTD_STATEACTION_VERIFY",
        "WTD_STATEACTION_CLOSE",
        "WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT",
        "WTD_CACHE_ONLY_URL_RETRIEVAL",
    ):
        assert token in source


def test_native_verification_cannot_authorize() -> None:
    source = CPP.read_text(encoding="utf-8")
    for token in (
        "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY",
        'publisher_pin_verified\\":false',
        'authorized_to_install\\":false',
        "NATIVE_WINDOWS_CHAIN_OBSERVED_PIN_UNPROVISIONED",
        "NATIVE_SIGNATURE_NOT_TRUSTED",
        "REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT",
        "return observed ? 2 : 1;",
    ):
        assert token in source


@pytest.mark.parametrize(
    "token",
    [
        "WriteFile(",
        "DeleteFileW(",
        "CreateServiceW(",
        "StartServiceW(",
        "RegSetValue",
        "SetFileSecurityW(",
        "ShellExecuteW(",
        "CreateProcessW(",
        "CryptSignMessage(",
        "CertAddCertificateContextToStore(",
    ],
    ids=(
        "write",
        "delete",
        "service",
        "start",
        "registry",
        "acl",
        "elevate",
        "process",
        "sign",
        "store",
    ),
)
def test_no_mutating_native_api(token: str) -> None:
    assert token not in CPP.read_text(encoding="utf-8")


def test_separate_witness_compiled_with_security_flags() -> None:
    cmake = CMAKE.read_text(encoding="utf-8")
    assert "add_executable(pds_windows_signature_probe signature_probe.cpp)" in cmake
    assert "cxx_std_17" in cmake
    assert "pds_windows_signature_probe PRIVATE wintrust crypt32" in cmake
    assert "pds_windows_signature_probe PRIVATE /W4 /WX /permissive- /sdl" in cmake
    assert "pds_windows_signature_probe PRIVATE -Wall -Wextra -Werror" in cmake
    assert "add_executable(pds_windows_bootstrap_probe" in cmake


def test_build_gate_enforces_unsigned_and_rejects_install_switch() -> None:
    script = RUN.read_text(encoding="utf-8")
    for text in (
        "--target pds_windows_signature_probe --parallel 2",
        "SLICE125_UNSIGNED_SIGNATURE_WITNESS_SHA256",
        "@(& $signatureExe)",
        "$sigCode -ne 1",
        "$sig.status -ne 'NATIVE_SIGNATURE_NOT_TRUSTED'",
        "$sig.wintrust_chain_observed -cne $false",
        "$sig.publisher_pin_verified -cne $false",
        "$sig.authorized_to_install -cne $false",
        "@(& $signatureExe --install)",
        "REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT",
        "SLICE125_NATIVE_UNSIGNED_SIGNATURE_AND_INSTALL_REFUSAL_PASSED",
    ):
        assert text in script


def test_existing_slice122_success_exit_contract_retained() -> None:
    script = RUN.read_text(encoding="utf-8")
    assert script.rstrip().endswith(
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"\nexit 0'
    )
    assert "SLICE123_NATIVE_ARM64_RUNTIME_PASSED" in script
    assert "SLICE122_NATIVE_APPLY_FLAG_REFUSED" in script
    assert "BLOCKED_NATIVE_RUNTIME_ARCH_MISMATCH" in script


def test_doc_limits_observation_and_native_acceptance() -> None:
    doc = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "unsigned",
        "native arm64",
        "publisher pin",
        "not an authenticated installer",
        "no installation",
        "winverifytrust",
    ):
        assert phrase in doc
