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
    $proof = [ordered]@{
        status = 'DISPOSABLE_ORDINARY_TOKEN_DENIALS_OBSERVED_UNATTESTED'
        ordinary_user_sid = $identity.User.Value
        positive_control_read_write = $true
        protected_directory_denials = $denied
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
