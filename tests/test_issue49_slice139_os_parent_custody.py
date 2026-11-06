"""Slice 139: disposable OS-anchored parent must deny ordinary delete rights."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "native/windows/bootstrap/qualify_sandbox_os_parent_ci.ps1"
CHILD = ROOT / "native/windows/bootstrap/sandbox_os_parent_probe.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-os-parent-denial.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-139-os-parent-custody.md"
OLD_CHILD = ROOT / "native/windows/bootstrap/sandbox_ordinary_user_probe.ps1"


def test_exact_assets_exist_and_stay_bounded() -> None:
    for path in (ORCHESTRATOR, CHILD, WORKFLOW, DOC, OLD_CHILD):
        assert path.is_file(), path
        assert 400 < path.stat().st_size < 26000


def test_admin_script_refuses_non_hosted_invocation_before_writes() -> None:
    code = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "GITHUB_ACTIONS",
        "RUNNER_OS",
        "RUNNER_ENVIRONMENT",
        "github-hosted",
        "WindowsBuiltInRole]::Administrator",
        "only ephemeral hosted Windows CI",
        "[IO.Directory]::CreateDirectory($path)",
        "New-LocalUser",
    ):
        assert phrase in code
    assert code.index("RUNNER_ENVIRONMENT") < code.index("CreateDirectory($path)")
    assert code.index("IsInRole(") < code.index("CreateDirectory($path)")


def test_real_os_root_is_not_environment_supplied() -> None:
    code = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "[Environment+SpecialFolder]::CommonApplicationData",
        "GetFolderPath(",
        "[IO.Path]::GetFullPath(",
        "pds-suite49-osparent-sbx-",
        "[guid]::NewGuid().ToString('N')",
        "FileAttributes]::ReparsePoint",
        "$parentSddlBefore",
    ):
        assert phrase in code
    for unsafe in ("$env:ProgramData", "$env:TEMP", "-InstallRoot", "-ServiceName"):
        assert unsafe not in code


def test_exact_five_disposable_children_and_protected_acl() -> None:
    code = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "Join-Path $root 'app-binaries'",
        "Join-Path $root 'protected-state'",
        "Join-Path $root 'protected-state\\active-receipts'",
        "Join-Path $root 'protected-state\\service-state'",
        "SetAccessRuleProtection($true, $false)",
        "RemoveAccessRuleSpecific($old)",
        "S-1-5-18",
        "S-1-5-32-544",
        "FileSystemRights]::FullControl",
        "Set-Acl -LiteralPath $path",
    ):
        assert phrase in code
    assert code.count("[void][IO.Directory]::CreateDirectory($path)") == 1


def test_second_account_random_short_name_sid_is_checked() -> None:
    code = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "'pdsacl_' + [guid]::NewGuid()",
        "Substring(0, 12)",
        "$name.Length -gt 20",
        "RandomNumberGenerator]::Fill",
        "New-LocalUser -Name $name",
        "^S-1-5-21-[0-9-]+$",
        "Get-LocalGroupMember",
        "-Credential $credential",
    ):
        assert phrase in code


def test_ordinary_account_has_only_control_access() -> None:
    code = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "FileSystemRights]::ReadAndExecute",
        "FileSystemRights]::Modify",
        "[Security.AccessControl.InheritanceFlags]::None",
        "[Security.AccessControl.AccessControlType]::Allow",
        "Set-Acl -LiteralPath $root",
        "Set-Acl -LiteralPath $control",
        "admin-prepared-control.txt",
    ):
        assert phrase in code


def test_both_actual_child_processes_are_required() -> None:
    code = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "sandbox_ordinary_user_probe.ps1",
        "sandbox_os_parent_probe.ps1",
        "Invoke-OrdinaryProbe $ordinaryProbe",
        "Invoke-OrdinaryProbe $externalProbe",
        "-EncodedCommand",
        "-PassThru -Wait -ErrorAction Stop",
        "process.ExitCode -ne 0",
    ):
        assert phrase in code


def test_child_rejects_wrong_user_and_untrusted_path() -> None:
    code = CHILD.read_text(encoding="utf-8")
    for phrase in (
        "WindowsIdentity]::GetCurrent()",
        "identity.User.Value -cne $ExpectedSid",
        "WindowsBuiltInRole]::Administrator",
        "RUNNER_ENVIRONMENT",
        "[Environment+SpecialFolder]::CommonApplicationData",
        "'^[0-9a-f]{32}$'",
        "pds-suite49-osparent-sbx-",
        "-cne $SandboxRoot",
    ):
        assert phrase in code


def test_os_parent_delete_checks_are_non_destructive() -> None:
    code = CHILD.read_text(encoding="utf-8")
    for phrase in (
        "CreateFileW",
        "SafeFileHandle",
        "Marshal.GetLastWin32Error()",
        "OPEN_EXISTING",  # Descriptive comment is required too.
        "0x00010000 # DELETE",
        "0x00000040 # FILE_DELETE_CHILD",
        "OpenAccessOnly($positive, $deleteAccess)",
        "OpenAccessOnly($root, $deleteAccess)",
        "$parent, $deleteChildAccess",
        "$rootDelete -ne 5 -or $parentDeleteChild -ne 5",
    ):
        assert phrase in code
    for forbidden in ("DeleteFile(", "RemoveDirectory(", "Remove-Item "):
        assert forbidden not in code


def test_positive_control_and_two_required_denials_reported() -> None:
    child = CHILD.read_text(encoding="utf-8")
    parent = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "ORDINARY_WRITE_SUCCEEDED",
        "ordinary_positive_control_delete_access = $true",
        "sandbox_root_delete_access_denied = $true",
        "os_parent_delete_child_access_denied = $true",
        "no_delete_operation_performed = $true",
        "os_parent_production_custody_verified = $false",
        "authorized_to_install = $false",
    ):
        assert phrase in child
    for phrase in (
        "external.sandbox_root_delete_access_denied -cne $true",
        "external.os_parent_delete_child_access_denied -cne $true",
        "ordinary.protected_object_delete_access_denials -ne 4",
        "ordinary.protected_parent_delete_child_access_denials -ne 4",
        "ordinary.protected_directory_denials -ne 4",
        "parentSddlBefore",
        "SLICE139_EPHEMERAL_OS_ANCHORED_PARENT_DELETE_RIGHTS_DENIED",
    ):
        assert phrase in parent


@pytest.mark.parametrize(
    "bad",
    (
        "New-Service",
        "Remove-LocalUser",
        "Remove-Item ",
        "DeleteFile(",
        "RemoveDirectory(",
        "Restart-Service",
        "Start-Service",
        "Set-Service",
        "icacls.exe",
        "Invoke-Expression",
        "ProgramData\\Paper Data Suite",
        "publisher-pin-v1.json",
    ),
)
def test_no_production_install_or_destructive_operations(bad: str) -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8") + CHILD.read_text(
        encoding="utf-8"
    )
    assert bad not in source


def test_ci_job_is_hosted_and_read_only_checkout() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for phrase in (
        "runs-on: windows-2022",
        "timeout-minutes: 15",
        "contents: read",
        "qualify_sandbox_os_parent_ci.ps1",
        "git diff --check",
        "git status --porcelain=v1 --untracked-files=all",
    ):
        assert phrase in workflow
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "-Credential" not in workflow


def test_documented_boundaries() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "os-resolved commonapplicationdata",
        "external parent",
        "ephemeral",
        "positive",
        "non-production",
        "no automatic deletion",
        "no production installer",
        "not a production installer",
        "rollback",
        "not authenticate a real",
    ):
        assert phrase in text
