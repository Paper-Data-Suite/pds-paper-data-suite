# Suite #49 Slice 139. Standard-user check of an OS-anchored disposable parent.
# This script is invoked only as a newly created, local standard account in CI.
# It opens access-check handles; it NEVER calls DeleteFile/RemoveDirectory.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SandboxRoot,
    [Parameter(Mandatory = $true)] [string] $ExpectedSid
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
        $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_OS -cne 'Windows' -or
        $env:RUNNER_ENVIRONMENT -cne 'github-hosted') {
        throw 'hosted Windows CI required'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if ($null -eq $identity.User -or $identity.User.Value -cne $ExpectedSid -or
        $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'real ordinary account SID mismatch'
    }
    # Resolve through the OS, not an environment variable or caller-provided parent.
    $parent = [IO.Path]::GetFullPath([Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonApplicationData)).TrimEnd('\')
    $root = [IO.Path]::GetFullPath($SandboxRoot)
    $prefix = $parent + '\pds-suite49-osparent-sbx-'
    if ($parent -notmatch '^[A-Za-z]:\\' -or
        -not $root.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        $root.Substring($prefix.Length) -cnotmatch '^[0-9a-f]{32}$' -or
        $root -cne $SandboxRoot) {
        throw 'noncanonical OS-anchored sandbox'
    }
    foreach ($path in @($parent, $root)) {
        $entry = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if (-not $entry.PSIsContainer -or
            (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'redirected OS parent or sandbox'
        }
    }
    $positive = Join-Path $root 'ordinary-control\ordinary-positive-write.txt'
    if ([IO.File]::ReadAllText($positive) -cne 'ORDINARY_WRITE_SUCCEEDED') {
        throw 'ordinary-account positive control missing'
    }
    # A successful positive control establishes valid Win32 access machinery.
    # OPEN_EXISTING (3) requests only a handle and never performs deletion.
    $native = @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class PdsSandboxOsParentAccess139 {
    [DllImport("kernel32.dll", EntryPoint="CreateFileW", CharSet=CharSet.Unicode,
        ExactSpelling=true, SetLastError=true)]
    private static extern SafeFileHandle CreateFileW(
        string path, uint access, uint share, IntPtr security,
        uint disposition, uint flags, IntPtr template);
    public static int OpenAccessOnly(string path, uint desired) {
        using (SafeFileHandle h = CreateFileW(path, desired, 7,
            IntPtr.Zero, 3, 0x02000000, IntPtr.Zero)) {
            return h.IsInvalid ? Marshal.GetLastWin32Error() : 0;
        }
    }
}
'@
    Add-Type -TypeDefinition $native -ErrorAction Stop
    $deleteAccess = [uint32]0x00010000 # DELETE requested; no deletion occurs.
    $deleteChildAccess = [uint32]0x00000040 # FILE_DELETE_CHILD requested.
    if ([PdsSandboxOsParentAccess139]::OpenAccessOnly($positive, $deleteAccess) -ne 0) {
        throw 'positive-control DELETE right unavailable'
    }
    $rootDelete = [PdsSandboxOsParentAccess139]::OpenAccessOnly($root, $deleteAccess)
    $parentDeleteChild = [PdsSandboxOsParentAccess139]::OpenAccessOnly(
        $parent, $deleteChildAccess)
    if ($rootDelete -ne 5 -or $parentDeleteChild -ne 5) {
        throw 'external-parent DELETE or FILE_DELETE_CHILD was not denied'
    }
    $proof = [ordered]@{
        status = 'OS_ANCHORED_SANDBOX_DELETE_RIGHTS_DENIED_UNATTESTED'
        ordinary_user_sid = $identity.User.Value
        ordinary_positive_control_delete_access = $true
        sandbox_root_delete_access_denied = $true
        os_parent_delete_child_access_denied = $true
        no_delete_operation_performed = $true
        independently_attested_teacher_identity = $false
        os_parent_production_custody_verified = $false
        installed_service_accepted = $false
        authorized_to_install = $false
        authority = $noAuthority
    }
    [IO.File]::WriteAllText((Join-Path $root 'ordinary-control\os-parent-proof.json'),
        ($proof | ConvertTo-Json -Compress -Depth 3))
    exit 0
} catch {
    [Console]::Error.WriteLine('REFUSED_OS_ANCHORED_SANDBOX_PARENT_CHECK')
    [Console]::Error.WriteLine($noAuthority)
    exit 1
}
