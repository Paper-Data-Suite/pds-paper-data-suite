"""Slice 122: native Windows build matrix/source contract (not an actual C++ build)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native/windows/bootstrap/qualify_native_bootstrap.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-native-bootstrap-build.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-122-native-build-runtime-gate.md"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_required_assets_exist_and_are_bounded() -> None:
    assert all(item.is_file() for item in (SCRIPT, WORKFLOW, DOC))
    assert 1_000 < len(SCRIPT.read_bytes().replace(b"\r\n", b"\n")) < 16_000
    assert WORKFLOW.stat().st_size < 6_000


def test_generator_is_explicit_visual_studio_and_no_automatic_tool_install() -> None:
    source = _script()
    assert "'Visual Studio 17 2022'" in source
    assert "'cmake.exe'" in source
    assert "Get-Command" in source
    assert "--build $build" in source
    for forbidden in (
        "winget install",
        "choco install",
        "Invoke-WebRequest",
        "Start-Process -Verb RunAs",
    ):
        assert forbidden not in source


def test_x64_arm64_pe_machine_identity_is_derived_from_actual_executable() -> None:
    source = _script()
    assert "[ValidateSet('x64', 'ARM64')]" in source
    assert "[System.IO.File]::ReadAllBytes($exe)" in source
    assert "ToUInt16($bytes, $peOffset + 4)" in source
    assert "0x8664" in source
    assert "0xaa64" in source
    assert "Get-FileHash -LiteralPath $exe -Algorithm SHA256" in source


def test_build_outputs_outside_repo_and_is_noninstalling() -> None:
    source = _script()
    assert "[System.IO.Path]::GetTempPath()" in source
    assert "[guid]::NewGuid()" in source
    assert "SLICE122_BUILD_ROOT" in source
    for forbidden in (
        "New-Service",
        "Set-Service",
        "sc.exe",
        "Set-Acl",
        "icacls",
        "Start-Service",
        "Remove-Item",
        "WriteAllBytes",
        "Copy-Item",
    ):
        assert forbidden not in source


def test_read_only_runtime_and_apply_refusal_are_required() -> None:
    source = _script()
    assert "@(& $exe --apply)" in source
    assert "@(& $exe)" in source
    assert "ConvertFrom-Json" in source
    assert "Assert-NoAuthorityOutput" in source
    assert "SLICE122_NATIVE_APPLY_FLAG_REFUSED" in source
    assert "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED" in source
    assert "BLOCKED_NATIVE_RUNTIME_ARCH_MISMATCH" in source
    assert "NATIVE_WINDOWS_CHECKPOINT_CUSTODY_NOT_ESTABLISHED" in source
    assert "NATIVE_WINDOWS_CHECKPOINT_BYTES_OBSERVED_ONLY" in source


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
def test_every_runtime_authority_flag_must_be_false(field: str) -> None:
    assert "$data." + field + " -cne $false" in _script()


def test_cross_compile_never_impersonates_arm64_runtime() -> None:
    source = _script()
    assert "if ($Architecture -ne $hostArchitecture)" in source
    assert "SLICE122_CROSS_COMPILED_ONLY" in source
    assert "[switch] $RequireRuntime" in source
    assert "return" in source


def test_ci_is_restricted_to_read_only_build_and_source_hygiene() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: windows-2022" in content
    assert "arch: [x64, ARM64]" in content
    assert "fail-fast: false" in content
    assert "workflow_dispatch:" in content
    assert "permissions:" in content and "contents: read" in content
    assert "qualify_native_bootstrap.ps1" in content
    assert "git status --porcelain=v1" in content
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in content
    for forbidden in (
        "upload-artifact",
        "workflow_run",
        "pull_request_target",
        "secrets.",
        "Set-Service",
        "New-Service",
    ):
        assert forbidden not in content


def test_spec_explicitly_withholds_native_security_acceptance() -> None:
    doc = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "x64 runtime",
        "arm64 compile-only",
        "not signed",
        "no protected writes",
        "native service",
        "toolchain",
    ):
        assert phrase in doc
