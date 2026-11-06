"""Slice 137: second ordinary Windows identity for disposable ACL denial CI."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "native/windows/bootstrap/qualify_sandbox_ordinary_user_ci.ps1"
CHILD = ROOT / "native/windows/bootstrap/sandbox_ordinary_user_probe.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-ordinary-user-denial.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-137-disposable-standard-user-denial.md"
OLD = ROOT / "native/windows/bootstrap/sandbox_acl_provisioning.ps1"


def test_exact_assets_and_prior_sandbox() -> None:
    for path in (ORCHESTRATOR, CHILD, WORKFLOW, DOC, OLD):
        assert path.is_file()
        assert 500 < path.stat().st_size < 30000


def test_only_ephemeral_hosted_ci_may_run_account_creation() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for value in (
        "GITHUB_ACTIONS",
        "RUNNER_OS",
        "RUNNER_ENVIRONMENT",
        "github-hosted",
        "WindowsBuiltInRole]::Administrator",
        "New-LocalUser",
        "[guid]::NewGuid()",
        "RandomNumberGenerator]::Fill",
        "ConvertTo-SecureString",
        "-PasswordNeverExpires",
    ):
        assert value in text
    assert text.index("GITHUB_ACTIONS") < text.index("New-LocalUser")


def test_previous_provisioning_script_invoked_in_disposable_mode_only() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for value in (
        "sandbox_acl_provisioning.ps1",
        "-ApplySandbox -Acknowledge 'SANDBOX_ACL_EXPERIMENT_ONLY'",
        "DISPOSABLE_ACL_SANDBOX_CREATED_NOT_PRODUCTION",
        "pds-suite49-acl-sandbox-",
        "'^[0-9a-f]{32}$'",
        "-cnotmatch",
        "created.authorized_to_install -cne $false",
    ):
        assert value in text


def test_child_binds_real_os_user_sid_and_checks_not_administrator() -> None:
    text = CHILD.read_text(encoding="utf-8")
    for value in (
        "WindowsIdentity]::GetCurrent()",
        "WindowsPrincipal]::new($identity)",
        "identity.User.Value -cne $ExpectedSid",
        "WindowsBuiltInRole]::Administrator",
        "ordinary-positive-write.txt",
    ):
        assert value in text


def test_positive_control_is_real_file_read_and_write() -> None:
    text = CHILD.read_text(encoding="utf-8")
    for value in (
        "admin-prepared-control.txt",
        "CI_ORDINARY_CONTROL_REACHABLE",
        "[IO.File]::ReadAllText($seed)",
        "[IO.File]::WriteAllText($positive",
        "[IO.File]::ReadAllText($positive)",
        "positive_control_read_write = $true",
    ):
        assert value in text


def test_all_four_real_protected_directory_write_denials() -> None:
    text = CHILD.read_text(encoding="utf-8")
    for value in (
        "Join-Path $SandboxRoot 'app-binaries'",
        "Join-Path $SandboxRoot 'protected-state'",
        "Join-Path $SandboxRoot 'protected-state\\active-receipts'",
        "Join-Path $SandboxRoot 'protected-state\\service-state'",
        "[IO.File]::Open($candidate, [IO.FileMode]::CreateNew",
        "catch [UnauthorizedAccessException]",
        "PROTECTED_DIRECTORY_WRITE_GRANTED",
        "denied -ne 4",
        "protected_directory_denials = $denied",
    ):
        assert value in text


def test_explicit_root_traversal_and_isolated_control_acl() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for value in (
        "[Security.AccessControl.FileSystemRights]::ReadAndExecute",
        "[Security.AccessControl.InheritanceFlags]::None",
        "ordinary-control",
        "[Security.AccessControl.FileSystemRights]::Modify",
        "SetAccessRuleProtection($true, $false)",
        "[Security.AccessControl.FileSystemRights]::FullControl",
        "Set-Acl -LiteralPath $control",
    ):
        assert value in text


def test_real_child_process_and_no_secret_reporting() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for value in (
        "Start-Process -FilePath $pwsh",
        "-Credential $credential",
        "-Wait -ErrorAction Stop",
        "[PSCredential]::new",
        "-EncodedCommand",
        "process.ExitCode -ne 0",
        "ConvertFrom-Json",
    ):
        assert value in text
    for bad in ("Write-Host $name", "Write-Host $password", "Write-Host $secret"):
        assert bad not in text


@pytest.mark.parametrize(
    "forbidden",
    (
        "New-Service",
        "Start-Service",
        "Stop-Service",
        "Remove-LocalUser",
        "Remove-Item",
        "icacls.exe",
        "Set-Service",
        "New-ScheduledTask",
        "Register-ScheduledTask",
        "Program Files",
        "ProgramData",
        "publisher-pin-v1.json",
        "Start-Process -Verb RunAs",
    ),
)
def test_never_mutates_production_state_or_removes_accounts(forbidden: str) -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8") + CHILD.read_text(encoding="utf-8")
    assert forbidden not in text


def test_protected_child_acls_rechecked_after_negative_process() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for value in (
        "ordinary-should-never-write.txt",
        "Get-Acl -LiteralPath $path",
        "acl.AreAccessRulesProtected",
        "aces.Count -ne 2",
        "IdentityReference.Value -eq $sid",
        "ordinary-proof.json",
        "protected_directory_denials -ne 4",
    ):
        assert value in text


def test_workflow_is_new_ephemeral_windows_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for value in (
        "runs-on: windows-2022",
        "timeout-minutes: 15",
        "contents: read",
        "qualify_sandbox_ordinary_user_ci.ps1",
        "git diff --check",
        "git status --porcelain=v1 --untracked-files=all",
    ):
        assert value in text
    assert "-Credential" not in text  # Credential handling stays in sandbox script.
    assert "workflow_dispatch:" in text


def test_docs_explicitly_refuse_deployment_authority() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    for value in (
        "positive",
        "negative",
        "standard user",
        "ephemeral",
        "not production authority",
        "parent-delete rights",
        "service",
        "no automatic deletion",
    ):
        assert value in text


def test_no_source_runner_invokes_ci_privileged_script() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "qualify_sandbox_ordinary_user_ci.ps1" in text
    assert "actions/checkout@" in text
    assert "schedule:" not in text
