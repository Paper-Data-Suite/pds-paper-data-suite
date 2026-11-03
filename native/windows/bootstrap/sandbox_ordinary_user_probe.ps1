# Suite #49 Slice 137: child-only, nonadministrator disposable ACL check.
# Invoked solely by a CI administrator's newly created ordinary local account.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SandboxRoot,
    [Parameter(Mandatory = $true)] [string] $ExpectedSid
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if ($null -eq $identity.User -or $identity.User.Value -cne $ExpectedSid -or
        $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'not the independently created ordinary test account'
    }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'Windows required'
    }
    $control = Join-Path $SandboxRoot 'ordinary-control'
    $seed = Join-Path $control 'admin-prepared-control.txt'
    if ([IO.File]::ReadAllText($seed) -cne 'CI_ORDINARY_CONTROL_REACHABLE') {
        throw 'positive control read inaccessible'
    }
    $positive = Join-Path $control 'ordinary-positive-write.txt'
    [IO.File]::WriteAllText($positive, 'ORDINARY_WRITE_SUCCEEDED')
    if ([IO.File]::ReadAllText($positive) -cne 'ORDINARY_WRITE_SUCCEEDED') {
        throw 'positive control write inaccessible'
    }
    $directories = @(
        (Join-Path $SandboxRoot 'app-binaries'),
        (Join-Path $SandboxRoot 'protected-state'),
        (Join-Path $SandboxRoot 'protected-state\active-receipts'),
        (Join-Path $SandboxRoot 'protected-state\service-state')
    )
    $denied = 0
    foreach ($directory in $directories) {
        $candidate = Join-Path $directory 'ordinary-should-never-write.txt'
        $granted = $false
        try {
            $file = [IO.File]::Open($candidate, [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $granted = $true } finally { $file.Dispose() }
        } catch [UnauthorizedAccessException] {
            $denied += 1
        }
        if ($granted) { throw 'PROTECTED_DIRECTORY_WRITE_GRANTED' }
    }
    if ($denied -ne 4) { throw 'not all protected directory writes denied' }

    # Slice 138: request DELETE and FILE_DELETE_CHILD access separately.
    # CreateFileW is used to ASK the kernel for a handle; it NEVER deletes an
    # object, changes a DACL, or exercises the granted access right. A separate
    # user-owned positive control detects broken P/Invoke or token setup.
    $win32Access = @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class PdsSandboxAccess138 {
    [DllImport("kernel32.dll", EntryPoint="CreateFileW", CharSet=CharSet.Unicode,
        ExactSpelling=true, SetLastError=true)]
    private static extern SafeFileHandle CreateFileW(
        string path, uint access, uint share, IntPtr security,
        uint disposition, uint flags, IntPtr template);
    public static int OpenAccessOnly(string path, uint desired) {
        // Share all three ways, with OPEN_EXISTING (3), and use
        // FILE_FLAG_BACKUP_SEMANTICS for existing directories.
        using (SafeFileHandle handle = CreateFileW(path, desired, 7,
            IntPtr.Zero, 3, 0x02000000, IntPtr.Zero)) {
            return handle.IsInvalid ? Marshal.GetLastWin32Error() : 0;
        }
    }
}
'@
    Add-Type -TypeDefinition $win32Access -ErrorAction Stop
    $deleteAccess = [uint32]0x00010000 # DELETE on the child object
    $deleteChildAccess = [uint32]0x00000040 # FILE_DELETE_CHILD on its parent
    if ([PdsSandboxAccess138]::OpenAccessOnly($positive, $deleteAccess) -ne 0) {
        throw 'positive-control DELETE access was not granted'
    }
    $deleteDenials = 0
    $parentDenials = 0
    $parentPaths = @(
        $SandboxRoot,
        $SandboxRoot,
        (Join-Path $SandboxRoot 'protected-state'),
        (Join-Path $SandboxRoot 'protected-state')
    )
    for ($i = 0; $i -lt $directories.Count; $i++) {
        $childResult = [PdsSandboxAccess138]::OpenAccessOnly(
            $directories[$i], $deleteAccess)
        $parentResult = [PdsSandboxAccess138]::OpenAccessOnly(
            $parentPaths[$i], $deleteChildAccess)
        if ($childResult -ne 5 -or $parentResult -ne 5) {
            throw 'DELETE or parent FILE_DELETE_CHILD access not denied'
        }
        $deleteDenials += 1
        $parentDenials += 1
    }
    if ($deleteDenials -ne 4 -or $parentDenials -ne 4) {
        throw 'incomplete deletion-right negative coverage'
    }
    # Successful open-right checks do not delete or mutate any test object.
    if ([IO.File]::ReadAllText($positive) -cne 'ORDINARY_WRITE_SUCCEEDED') {
        throw 'positive control was unexpectedly modified'
    }
    $proof = [ordered]@{
        status = 'DISPOSABLE_ORDINARY_TOKEN_DENIALS_OBSERVED_UNATTESTED'
        ordinary_user_sid = $identity.User.Value
        positive_control_read_write = $true
        protected_directory_denials = $denied
        positive_control_delete_access_granted = $true
        protected_object_delete_access_denials = $deleteDenials
        protected_parent_delete_child_access_denials = $parentDenials
        no_delete_operation_performed = $true
        independently_attested_teacher_identity = $false
        parent_deletion_protection_verified = $false
        installed_service_accepted = $false
        authorized_to_install = $false
        authority = $noAuthority
    }
    [IO.File]::WriteAllText((Join-Path $control 'ordinary-proof.json'),
        ($proof | ConvertTo-Json -Compress -Depth 3))
    exit 0
} catch {
    # The CI parent checks exit code and missing evidence. Do not print paths,
    # account information or credentials to the hosted runner log.
    [Console]::Error.WriteLine('REFUSED_SANDBOX_ORDINARY_USER_NEGATIVE_ACCEPTANCE')
    [Console]::Error.WriteLine($noAuthority)
    exit 1
}
