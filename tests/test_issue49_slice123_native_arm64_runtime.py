"""Slice 123: native Windows ARM64 execution gate (source-contract only).

These tests do NOT substitute for the native GitHub Actions job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-native-bootstrap-build.yml"
SPEC = ROOT / "docs/architecture/issue-49-slice-123-native-arm64-runtime.md"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_exact_native_assets_exist() -> None:
    assert SCRIPT.is_file()
    assert WORKFLOW.is_file()
    assert SPEC.is_file()
    assert SCRIPT.stat().st_size < 20_000
    assert WORKFLOW.stat().st_size < 10_000


def test_generator_explicit_allowlist_and_safe_default() -> None:
    source = _script()
    assert "[ValidateSet('Visual Studio 17 2022', 'Visual Studio 18 2026')]" in source
    assert "[string] $Generator = 'Visual Studio 17 2022'" in source
    assert "-G $Generator -A $Architecture" in source
    assert "-G 'Visual Studio 17 2022' -A $Architecture" not in source


def test_native_arm64_ci_uses_actual_arm64_host() -> None:
    content = _workflow()
    assert "native-arm64-runtime:" in content
    assert "runs-on: windows-11-vs2026-arm" in content
    assert "-Architecture 'ARM64'" in content
    assert "-Generator 'Visual Studio 18 2026'" in content
    assert "-RequireRuntime" in content
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in content


def test_original_build_matrix_remains() -> None:
    content = _workflow()
    assert "runs-on: windows-2022" in content
    assert "arch: [x64, ARM64]" in content
    assert "fail-fast: false" in content
    assert "-Architecture '${{ matrix.arch }}'" in content
    assert content.count("git status --porcelain=v1") == 2


def test_actual_binary_architecture_and_host_architecture_required() -> None:
    source = _script()
    assert "[switch] $RequireRuntime" in source
    assert (
        "[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture" in source
    )
    assert "if ($Architecture -ne $hostArchitecture)" in source
    assert "BLOCKED_NATIVE_RUNTIME_ARCH_MISMATCH" in source
    assert "ToUInt16($bytes, $peOffset + 4)" in source
    assert "0xaa64" in source
    assert "SLICE123_NATIVE_ARM64_RUNTIME_PASSED" in source
    assert "if ($Architecture -eq 'ARM64' -and $RequireRuntime)" in source


def test_runtime_refusal_and_clean_success_are_still_required() -> None:
    source = _script()
    assert "@(& $exe --apply)" in source
    assert "SLICE122_NATIVE_APPLY_FLAG_REFUSED" in source
    assert (
        'Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"' in source
    )
    assert source.rstrip().endswith("exit 0")
    assert "Assert-NoAuthorityOutput" in source


@pytest.mark.parametrize(
    "field",
    [
        "protected_write_performed",
        "administrator_authenticated",
        "service_identity_verified",
        "production_authority",
        "active_receipt_authority",
    ],
    ids=("write", "admin", "service", "production", "receipt"),
)
def test_native_both_runtimes_must_refuse_authority(field: str) -> None:
    assert "$data." + field + " -cne $false" in _script()


def test_no_install_or_remote_upload_command() -> None:
    content = _workflow()
    script = _script()
    for forbidden in (
        "New-Service",
        "Start-Service",
        "Set-Service",
        "Set-Acl",
        "Copy-Item",
        "Remove-Item",
        "Invoke-WebRequest",
        "upload-artifact",
        "secrets.",
    ):
        assert forbidden not in content
        assert forbidden not in script


def test_documentation_marks_exact_missing_acceptance() -> None:
    doc = SPEC.read_text(encoding="utf-8").lower()
    for requirement in (
        "native arm64 execution",
        "vs2026",
        "not signed",
        "not a service",
        "protected installation",
        "antirollback",
    ):
        assert requirement in doc
