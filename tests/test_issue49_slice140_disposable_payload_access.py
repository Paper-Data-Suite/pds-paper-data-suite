"""Slice 140: synthetic payload staging and separate account handle-denial contract."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "native/windows/bootstrap/qualify_sandbox_os_parent_ci.ps1"
CHILD = ROOT / "native/windows/bootstrap/sandbox_protected_payload_probe.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-os-parent-denial.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-140-synthetic-payload-custody.md"


def a() -> str:
    return ADMIN.read_text(encoding="utf8")


def c() -> str:
    return CHILD.read_text(encoding="utf8")


def test_exact_files_and_bounds() -> None:
    for p in (ADMIN, CHILD, WORKFLOW, DOC):
        assert p.is_file() and 500 < p.stat().st_size < 32000


def test_hosted_admin_precedes_staging() -> None:
    x = a()
    assert "RUNNER_ENVIRONMENT -cne 'github-hosted'" in x
    assert "WindowsBuiltInRole]::Administrator" in x
    assert x.index("RUNNER_ENVIRONMENT") < x.index("$payloadPath =")
    assert x.index("IsInRole(") < x.index("$payloadPath =")


def test_fixed_synthetic_file_in_os_sandbox() -> None:
    x = a()
    for s in (
        "[Environment+SpecialFolder]::CommonApplicationData",
        "pds-suite49-osparent-sbx-",
        "[guid]::NewGuid()",
        "Join-Path $root 'app-binaries\\synthetic-suite49-test-payload.bin'",
        "[IO.File]::WriteAllBytes($payloadPath, $syntheticBytes)",
    ):
        assert s in x
    assert "-PayloadPath" not in x and "-ArtifactUrl" not in x


def test_no_signed_release_claim() -> None:
    for x in (a(), c()):
        assert "PDS_SUITE49_SYNTHETIC_PAYLOAD_V1_NOT_A_SIGNED_RELEASE" in x
        assert "SHA256" in x
    assert "release_artifact_signature_verified = $false" in c()


def test_admin_stage_file_and_acl_verified() -> None:
    x = a()
    for s in (
        "Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256",
        "syntheticBytes.Length",
        "FileAttributes]::ReparsePoint",
        "Get-Acl -LiteralPath $payloadPath",
        "payloadAces.Count -ne 2",
        "FileSystemRights]::FullControl",
    ):
        assert s in x


def test_separate_user_and_os_root_checked() -> None:
    x = c()
    for s in (
        "RUNNER_ENVIRONMENT",
        "WindowsIdentity]::GetCurrent()",
        "identity.User.Value -cne $ExpectedSid",
        "WindowsBuiltInRole]::Administrator",
        "[Environment+SpecialFolder]::CommonApplicationData",
        "'^[0-9a-f]{32}$'",
    ):
        assert s in x


@pytest.mark.parametrize(
    "right", ("0x00000002", "0x00000004", "0x00010000", "0x00040000")
)
def test_four_access_bits_denied(right: str) -> None:
    x = c()
    assert right in x
    assert "OpenAccessOnly($syntheticFile, $right)" in x
    assert "if ($win32 -ne 5)" in x


def test_positive_control_for_three_rights() -> None:
    x = c()
    for s in (
        "[IO.File]::ReadAllText($control)",
        "OpenAccessOnly($control, $writeData)",
        "OpenAccessOnly($control, $appendData)",
        "OpenAccessOnly($control, $delete)",
    ):
        assert s in x


def test_handles_only_never_mutation() -> None:
    x = c()
    for s in (
        "CreateFileW",
        "SafeFileHandle",
        "Marshal.GetLastWin32Error()",
        "IntPtr.Zero, 3, 0, IntPtr.Zero",
        "no_payload_mutation_performed = $true",
    ):
        assert s in x


@pytest.mark.parametrize(
    "forbidden",
    (
        "DeleteFile(",
        "RemoveDirectory(",
        "Remove-Item ",
        "WriteAllBytes($syntheticFile",
        "Set-Acl -LiteralPath $syntheticFile",
        "New-Service",
        "Start-Service",
    ),
)
def test_child_never_mutates_protected_artifact(forbidden: str) -> None:
    assert forbidden not in c()


def test_only_permitted_proof_write() -> None:
    x = c()
    assert "Join-Path $root 'ordinary-control\\payload-proof.json'" in x
    for s in (
        "authorized_to_install = $false",
        "release_artifact_signature_verified = $false",
        "protected_executable_custody_verified = $false",
        "installed_service_accepted = $false",
    ):
        assert s in x


def test_parent_launches_same_credential_and_checks_proof() -> None:
    x = a()
    for s in (
        "Invoke-OrdinaryProbe $payloadProbe",
        "-Credential $credential",
        "staged.ordinary_user_sid -cne $sid",
        "staged.synthetic_payload_mutation_denials -ne 4",
        "staged.payload_sha256 -cne $expectedPayloadSha256",
        "staged.authorized_to_install -cne $false",
    ):
        assert s in x
    assert x.index("[IO.File]::WriteAllBytes($payloadPath") < x.index(
        "Invoke-OrdinaryProbe $payloadProbe"
    )


def test_independent_admin_readback_and_acl_comparison() -> None:
    x = a()
    assert x.count("Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256") == 2
    assert "[Convert]::ToBase64String([IO.File]::ReadAllBytes($payloadPath))" in x
    assert "afterAcl.Sddl -cne $payloadAcl.Sddl" in x
    assert "SLICE140_EPHEMERAL_SYNTHETIC_PAYLOAD_MUTATION_RIGHTS_DENIED" in x


def test_workflow_triggers_child_change() -> None:
    x = WORKFLOW.read_text()
    assert "sandbox_protected_payload_probe.ps1" in x
    assert "runs-on: windows-2022" in x
    assert "contents: read" in x


def test_documentation_lists_trust_limits() -> None:
    x = DOC.read_text().lower()
    for s in (
        "synthetic",
        "not a signed release",
        "sha-256",
        "ephemeral",
        "no automatic cleanup",
        "not pds artifact authentication",
        "no production installer",
    ):
        assert s in x
