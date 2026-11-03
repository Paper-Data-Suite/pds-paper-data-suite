# Slice 136: independent Windows sandbox ACL acceptance in disposable CI runner.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest
$script = Join-Path $PSScriptRoot 'sandbox_acl_provisioning.ps1'
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'Sandbox source unavailable' }
$pwsh = (Get-Command -Name pwsh.exe -CommandType Application -ErrorAction Stop).Source
$absent = @(& $pwsh -NoProfile -NonInteractive -File $script)
if ($LASTEXITCODE -ne 1 -or $absent.Count -ne 0) {
    throw 'Sandbox script did not refuse without explicit consent'
}
$lines = @(& $pwsh -NoProfile -NonInteractive -File $script `
    -ApplySandbox -Acknowledge 'SANDBOX_ACL_EXPERIMENT_ONLY')
$exitCode = $LASTEXITCODE
if ($exitCode -ne 2 -or $lines.Count -ne 2) {
    throw 'Sandbox was not created and validated by an elevated test process'
}
$record = $lines[0] | ConvertFrom-Json -ErrorAction Stop
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
if ($record.status -ne 'DISPOSABLE_ACL_SANDBOX_CREATED_NOT_PRODUCTION' -or
    $record.protected_paths_checked -ne 5 -or
    $record.dacl_rules_verified -cne $true -or
    $record.administrator_token_observed_unverified -cne $true -or
    $record.independent_administrator_authenticated -cne $false -or
    $record.ordinary_user_effective_denial_attested -cne $false -or
    $record.parent_delete_rights_protected -cne $false -or
    $record.production_provisioning_performed -cne $false -or
    $record.service_registered -cne $false -or
    $record.publisher_pin_provisioned -cne $false -or
    $record.receipt_published -cne $false -or
    $record.authorized_to_install -cne $false -or
    $record.authority -ne $noAuthority -or $lines[1] -ne $noAuthority) {
    throw 'Sandbox output asserted unsupported production authority'
}
$root = [IO.Path]::GetFullPath([string]$record.sandbox_root)
$temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (-not $root.StartsWith(($temp + 'pds-suite49-acl-sandbox-'),
    [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Sandbox path is outside the disposable temporary root'
}
$paths = @($root, (Join-Path $root 'app-binaries'),
    (Join-Path $root 'protected-state'),
    (Join-Path $root 'protected-state\active-receipts'),
    (Join-Path $root 'protected-state\service-state'))
foreach ($path in $paths) {
    $entry = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (-not $entry.PSIsContainer -or
        (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'Sandbox directory missing or redirected'
    }
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    if (-not $acl.AreAccessRulesProtected) { throw 'Sandbox DACL inheritance not disabled' }
    $aces = @($acl.GetAccessRules($true, $true,
        [Security.Principal.SecurityIdentifier]))
    if ($aces.Count -ne 2) { throw 'Sandbox DACL ACE count is not two' }
    $sids = @($aces | ForEach-Object { $_.IdentityReference.Value } | Sort-Object)
    if (($sids -join ',') -ne 'S-1-5-18,S-1-5-32-544') {
        throw 'Sandbox ACL principals differ from expected administrative groups'
    }
    foreach ($ace in $aces) {
        if ($ace.IsInherited -or
            $ace.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $ace.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl) {
            throw 'Sandbox DACL contained an unexpected rule'
        }
    }
}
Write-Host 'SLICE136_DISPOSABLE_WINDOWS_ACL_PROVISIONING_PASSED_NO_PRODUCTION_AUTHORITY'
exit 0
