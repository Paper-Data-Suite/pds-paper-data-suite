"""Slice 138: kernel checks protect child DELETE and parent FILE_DELETE_CHILD."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "native/windows/bootstrap/sandbox_ordinary_user_probe.ps1"
PARENT = ROOT / "native/windows/bootstrap/qualify_sandbox_ordinary_user_ci.ps1"
WORKFLOW = ROOT / ".github/workflows/issue49-sandbox-ordinary-user-denial.yml"
DOC = ROOT / "docs/architecture/issue-49-slice-138-disposable-delete-rights.md"


def test_exact_assets_and_documentation() -> None:
    for path in (CHILD, PARENT, WORKFLOW, DOC):
        assert path.is_file()
        assert 300 < path.stat().st_size < 30_000
    text = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "delete_child",
        "ordinary",
        "positive-control",
        "non-destructive",
        "error_access_denied",
        "parent",
        "no production installation",
        "rollback",
    ):
        assert phrase in text


def test_windows_probe_compiles_kernel_handle_only_api() -> None:
    text = CHILD.read_text(encoding="utf-8")
    for part in (
        "Add-Type -TypeDefinition $win32Access -ErrorAction Stop",
        'DllImport("kernel32.dll", EntryPoint="CreateFileW"',
        "SetLastError=true",
        "SafeFileHandle",
        "Marshal.GetLastWin32Error()",
        "OpenAccessOnly",
        "FILE_FLAG_BACKUP_SEMANTICS",
        "0x02000000",
        "using (SafeFileHandle handle",
    ):
        assert part in text
    assert text.index("Add-Type -TypeDefinition") < text.index(
        "positive-control DELETE access was not granted"
    )


def test_distinct_minimal_access_masks() -> None:
    text = CHILD.read_text(encoding="utf-8")
    assert "$deleteAccess = [uint32]0x00010000" in text
    assert "$deleteChildAccess = [uint32]0x00000040" in text
    assert "OpenAccessOnly($positive, $deleteAccess) -ne 0" in text
    assert "OpenAccessOnly(" in text
    assert "OPEN_EXISTING" in text
    assert "CreateFileW(path, desired, 7" in text


@pytest.mark.parametrize(
    "required",
    (
        "'app-binaries'",
        "'protected-state'",
        "'protected-state\\active-receipts'",
        "'protected-state\\service-state'",
        "$SandboxRoot,",
        "Join-Path $SandboxRoot 'protected-state'",
        "$childResult -ne 5",
        "$parentResult -ne 5",
        "$deleteDenials -ne 4",
        "$parentDenials -ne 4",
    ),
)
def test_four_targets_and_eight_denied_handles(required: str) -> None:
    assert required in CHILD.read_text(encoding="utf-8")


def test_new_report_fields_have_strict_parent_validation() -> None:
    child = CHILD.read_text(encoding="utf-8")
    parent = PARENT.read_text(encoding="utf-8")
    for name in (
        "positive_control_delete_access_granted",
        "protected_object_delete_access_denials",
        "protected_parent_delete_child_access_denials",
        "no_delete_operation_performed",
    ):
        assert name in child and name in parent
    assert "-cne $true" in parent
    assert "protected_object_delete_access_denials -ne 4" in parent
    assert "protected_parent_delete_child_access_denials -ne 4" in parent
    assert "SLICE138_EPHEMERAL_DELETE_AND_PARENT_DELETE_CHILD_RIGHTS_DENIED" in parent


@pytest.mark.parametrize(
    "forbidden",
    (
        "DeleteFileW(",
        "RemoveDirectoryW(",
        "Remove-Item",
        "Remove-LocalUser",
        "Start-Service",
        "New-Service",
        "icacls.exe",
        "SetNamedSecurityInfo",
        "Register-ScheduledTask",
        "Start-Process -Verb RunAs",
        "Invoke-Expression",
        "ProgramData",
        "publisher-pin-v1.json",
    ),
)
def test_no_delete_or_production_mutation_operation(forbidden: str) -> None:
    assert forbidden not in CHILD.read_text(encoding="utf-8") + PARENT.read_text(
        encoding="utf-8"
    )


def test_prior_positive_and_write_denial_remain_mandatory() -> None:
    child = CHILD.read_text(encoding="utf-8")
    parent = PARENT.read_text(encoding="utf-8")
    assert "CI_ORDINARY_CONTROL_REACHABLE" in child
    assert "ORDINARY_WRITE_SUCCEEDED" in child
    assert "[IO.FileMode]::CreateNew" in child
    assert "catch [UnauthorizedAccessException]" in child
    assert "$denied -ne 4" in child
    assert "protected_directory_denials -ne 4" in parent
    assert "Get-Acl -LiteralPath $path" in parent
    assert "RUNNER_ENVIRONMENT -cne 'github-hosted'" in parent
    assert "New-LocalUser -Name $name" in parent
    assert "Start-Process -FilePath $pwsh" in parent
    assert "-Credential $credential" in parent


def test_ci_trigger_includes_both_modified_scripts() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sandbox_ordinary_user_probe.ps1" in text
    assert "qualify_sandbox_ordinary_user_ci.ps1" in text
    assert "runs-on: windows-2022" in text
    assert "git diff --check" in text


def test_scope_remains_disposable_and_unattested() -> None:
    child = CHILD.read_text(encoding="utf-8")
    parent = PARENT.read_text(encoding="utf-8")
    for text in (child, parent):
        assert (
            "NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY" in text
        )
    assert "independently_attested_teacher_identity = $false" in child
    assert "installed_service_accepted = $false" in child
    assert "authorized_to_install = $false" in child
    assert "no unreviewed user deletion" in parent
