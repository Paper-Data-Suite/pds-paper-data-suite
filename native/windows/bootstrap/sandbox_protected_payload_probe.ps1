# Suite #49 Slice 140. Real OS access checks, synthetic file only.
# Called under an ephemeral separate Windows standard-user token, NEVER a teacher.
# Access-handle requests only: no WriteFile, SetSecurityInfo or DeleteFile.
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
        throw 'ephemeral hosted Windows CI required'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if ($null -eq $identity.User -or $identity.User.Value -cne $ExpectedSid -or
        $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'not the required separate standard-user token'
    }
    $parent = [IO.Path]::GetFullPath([Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonApplicationData)).TrimEnd('\')
    $root = [IO.Path]::GetFullPath($SandboxRoot)
    $prefix = $parent + '\pds-suite49-osparent-sbx-'
    if ($parent -notmatch '^[A-Za-z]:\\' -or
        -not $root.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        $root.Substring($prefix.Length) -cnotmatch '^[0-9a-f]{32}$' -or
        $root -cne $SandboxRoot) {
        throw 'noncanonical disposable OS-anchored sandbox'
    }
    $control = Join-Path $root 'ordinary-control\ordinary-positive-write.txt'
    if ([IO.File]::ReadAllText($control) -cne 'ORDINARY_WRITE_SUCCEEDED') {
        throw 'ordinary account positive write control unavailable'
    }
    $syntheticFile = Join-Path $root 'app-binaries\synthetic-suite49-test-payload.bin'
    # Open existing handles with requested access bits; never mutate or delete.
    $native = @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class PdsSandboxSyntheticPayloadAccess140 {
    [DllImport("kernel32.dll", EntryPoint="CreateFileW", CharSet=CharSet.Unicode,
        ExactSpelling=true, SetLastError=true)]
    private static extern SafeFileHandle CreateFileW(
        string path, uint access, uint share, IntPtr security,
        uint disposition, uint flags, IntPtr template);
    public static int OpenAccessOnly(string path, uint desired) {
        using (SafeFileHandle h = CreateFileW(path, desired, 7,
            IntPtr.Zero, 3, 0, IntPtr.Zero)) {
            return h.IsInvalid ? Marshal.GetLastWin32Error() : 0;
        }
    }
}
'@
    Add-Type -TypeDefinition $native -ErrorAction Stop
    $writeData = [uint32]0x00000002
    $appendData = [uint32]0x00000004
    $delete = [uint32]0x00010000
    $writeDac = [uint32]0x00040000
    # Positive controls must demonstrate the handle-opening API works, not
    # merely report ERROR_ACCESS_DENIED for every request.
    if ([PdsSandboxSyntheticPayloadAccess140]::OpenAccessOnly($control, $writeData) -ne 0 -or
        [PdsSandboxSyntheticPayloadAccess140]::OpenAccessOnly($control, $appendData) -ne 0 -or
        [PdsSandboxSyntheticPayloadAccess140]::OpenAccessOnly($control, $delete) -ne 0) {
        throw 'positive-control modification access unavailable'
    }
    $denied = 0
    foreach ($right in @($writeData, $appendData, $writeDac, $delete)) {
        $win32 = [PdsSandboxSyntheticPayloadAccess140]::OpenAccessOnly($syntheticFile, $right)
        if ($win32 -ne 5) { throw 'synthetic payload dangerous access was not denied' }
        $denied += 1
    }
    if ($denied -ne 4) { throw 'incomplete synthetic payload mutation denials' }
    # This is a synthetic public test string, NOT an independently signed file.
    $bytes = [Text.Encoding]::ASCII.GetBytes(
        'PDS_SUITE49_SYNTHETIC_PAYLOAD_V1_NOT_A_SIGNED_RELEASE')
    $sha256 = [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    $proof = [ordered]@{
        status = 'SYNTHETIC_PAYLOAD_MUTATION_RIGHTS_DENIED_UNATTESTED'
        ordinary_user_sid = $identity.User.Value
        positive_write_data_access = $true
        positive_append_data_access = $true
        positive_delete_access = $true
        synthetic_payload_mutation_denials = $denied
        payload_sha256 = $sha256
        no_payload_mutation_performed = $true
        release_artifact_signature_verified = $false
        protected_executable_custody_verified = $false
        installed_service_accepted = $false
        authorized_to_install = $false
        authority = $noAuthority
    }
    [IO.File]::WriteAllText((Join-Path $root 'ordinary-control\payload-proof.json'),
        ($proof | ConvertTo-Json -Compress -Depth 3))
    exit 0
} catch {
    [Console]::Error.WriteLine('REFUSED_DISPOSABLE_SYNTHETIC_PAYLOAD_ACCESS_CHECK')
    [Console]::Error.WriteLine($noAuthority)
    exit 1
}
