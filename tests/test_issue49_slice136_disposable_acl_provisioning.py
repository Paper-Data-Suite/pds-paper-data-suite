"""Slice 136: actual Windows ACL mutations remain in isolated sandbox only."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROVISION = ROOT / "native/windows/bootstrap/sandbox_acl_provisioning.ps1"
QUALIFY = ROOT / "native/windows/bootstrap/qualify_sandbox_acl.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-acl-provisioning.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-136-disposable-acl-provisioning.md"


def test_four_additive_assets_are_bounded() -> None:
    for path in (PROVISION, QUALIFY, WORKFLOW, DOC):
        assert path.is_file()
        assert 500 < path.stat().st_size < 24000


def test_prototype_requires_explicit_action_before_first_write() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    for phrase in (
        "[switch] $ApplySandbox",
        "[string] $Acknowledge = ''",
        "-not $ApplySandbox",
        "SANDBOX_ACL_EXPERIMENT_ONLY",
        "GetCurrent()",
        "IsInRole(",
        "WindowsBuiltInRole]::Administrator",
        "exit 1",
    ):
        assert phrase in source
    assert source.index("SANDBOX_ACL_EXPERIMENT_ONLY") < source.index(
        "[void][IO.Directory]::CreateDirectory($path)"
    )


def test_prototype_uses_only_random_local_temp_root() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    for phrase in (
        "[IO.Path]::GetTempPath()",
        "GetFullPath(",
        "pds-suite49-acl-sandbox-",
        "[guid]::NewGuid()",
        "-notmatch '^[A-Za-z]:",
        "FileAttributes]::ReparsePoint",
        "Test-Path -LiteralPath $root",
    ):
        assert phrase in source
    assert "param(" in source
    assert "$Root" not in source
    assert "$InstallPath" not in source


def test_exact_disposable_directory_layout() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    for phrase in (
        "Join-Path $root 'app-binaries'",
        "Join-Path $root 'protected-state'",
        "Join-Path $root 'protected-state\\active-receipts'",
        "Join-Path $root 'protected-state\\service-state'",
        "protected_paths_checked = $paths.Count",
    ):
        assert phrase in source
    assert source.count("[void][IO.Directory]::CreateDirectory($path)") == 1


def test_acl_is_explicitly_protected_and_administrator_only() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    for phrase in (
        "S-1-5-32-544",
        "S-1-5-18",
        "SetAccessRuleProtection($true, $false)",
        "RemoveAccessRuleSpecific($old)",
        "FileSystemRights]::FullControl",
        "ContainerInherit",
        "ObjectInherit",
        "AccessControlType]::Allow",
        "Set-Acl -LiteralPath $path",
        "Get-Acl -LiteralPath $path",
        "AreAccessRulesProtected",
        "GetAccessRules($true, $true,",
        "IdentityReference.Value",
        "$aces.Count -ne 2",
        "$observed.Count -ne 2",
    ):
        assert phrase in source


@pytest.mark.parametrize(
    "forbidden",
    (
        "New-Service",
        "Start-Service",
        "Stop-Service",
        "sc.exe",
        "CreateService",
        "Set-Service",
        "Remove-Item",
        "Reset-Acl",
        "icacls.exe",
        "Invoke-Expression",
        "Start-Process",
        "Register-ScheduledTask",
        "CreateProcess",
        "PaperDataSuiteService",
        "receipt.json",
        "publisher-pin-v1.json",
        "pds-paper-data-suite",
    ),
)
def test_no_production_or_destructive_operation(forbidden: str) -> None:
    assert forbidden not in PROVISION.read_text(encoding="utf-8")


def test_sandbox_success_expressly_denies_production_authority() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    for phrase in (
        "DISPOSABLE_ACL_SANDBOX_CREATED_NOT_PRODUCTION",
        "independent_administrator_authenticated = $false",
        "ordinary_user_effective_denial_attested = $false",
        "parent_delete_rights_protected = $false",
        "production_provisioning_performed = $false",
        "service_registered = $false",
        "publisher_pin_provisioned = $false",
        "receipt_published = $false",
        "authorized_to_install = $false",
        "NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY",
        "exit 2",
    ):
        assert phrase in source


def test_failure_retains_state_and_refuses_without_cleanup() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    assert "catch {" in source
    assert "Refuse 'sandbox test failed" in source
    assert "No automatic" not in source  # No implicit cleanup logic.
    assert "Remove-Item" not in source


def test_windows_ci_checks_actual_acl_rules_not_just_status() -> None:
    source = QUALIFY.read_text(encoding="utf-8")
    for phrase in (
        "pwsh.exe",
        "-ApplySandbox -Acknowledge 'SANDBOX_ACL_EXPERIMENT_ONLY'",
        "$exitCode -ne 2",
        "protected_paths_checked -ne 5",
        "production_provisioning_performed -cne $false",
        "parent_delete_rights_protected -cne $false",
        "dacl_rules_verified -cne $true",
        "S-1-5-18,S-1-5-32-544",
        "Get-Acl -LiteralPath $path",
        "AreAccessRulesProtected",
        "FileSystemRights]::FullControl",
        "SLICE136_DISPOSABLE_WINDOWS_ACL_PROVISIONING_PASSED_NO_PRODUCTION_AUTHORITY",
    ):
        assert phrase in source


def test_ci_never_accepts_non_admin_skip_as_success() -> None:
    source = QUALIFY.read_text(encoding="utf-8")
    assert "throw 'Sandbox was not created" in source
    assert "-ApplySandbox" in source
    assert "exit 0" in source
    assert "SKIP" not in source


def test_github_job_is_ephemeral_and_minimally_scoped() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    for phrase in (
        "runs-on: windows-2022",
        "timeout-minutes: 15",
        "contents: read",
        "qualify_sandbox_acl.ps1",
        "git diff --check",
        "git status --porcelain=v1 --untracked-files=all",
    ):
        assert phrase in source
    assert "workflow_dispatch:" in source
    assert "pull_request:" not in source
    assert "-ApplySandbox" not in source  # Helper encapsulates consent.


def test_docs_state_critical_limits_and_manual_boundary() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "first intentionally",
        "disposable",
        "temporary",
        "parent deletion rights",
        "are **not** proved",
        "independently",
        "not a production installer",
        "ordinary-user effective rights",
        "crash recovery",
        "no automatic",
        "no production",
    ):
        assert phrase in text
