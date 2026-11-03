# Suite #49 Slice 129: independent read-only primary-token observation gate.
# Exit 0 means diagnostic expectations passed, NOT provision/install authority.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('x64', 'ARM64')]
    [string] $Architecture,
    [Parameter(Mandatory = $true)]
    [string] $Build,
    [Parameter(Mandatory = $true)]
    [string] $NoAuthority
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest
$exe = Join-Path $Build 'Release\pds_windows_pin_admin_preflight.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw 'Native token preflight executable missing.'
}
$bytes = [System.IO.File]::ReadAllBytes($exe)
if ($bytes.Length -lt 128 -or $bytes[0] -ne 77 -or $bytes[1] -ne 90) {
    throw 'Native token preflight executable is not MZ.'
}
$peOffset = [System.BitConverter]::ToInt32($bytes, 0x3c)
if ($peOffset -lt 64 -or $peOffset -gt ($bytes.Length - 24) -or
    $bytes[$peOffset] -ne 80 -or $bytes[$peOffset + 1] -ne 69 -or
    $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) {
    throw 'Native token preflight PE header invalid.'
}
$machine = [System.BitConverter]::ToUInt16($bytes, $peOffset + 4)
$expected = if ($Architecture -eq 'x64') { [uint16]0x8664 } else { [uint16]0xaa64 }
if ($machine -ne $expected) {
    throw 'Native token preflight target PE architecture mismatch.'
}
Write-Host "SLICE129_NATIVE_TOKEN_PREFLIGHT_COMPILED_$Architecture"

# Slice 130: separately built read-only SCM service security inventory.
$scmExe = Join-Path $Build 'Release\pds_windows_service_scm_probe.exe'
$cmake = Get-Command -Name 'cmake.exe' -CommandType Application -ErrorAction Stop
& $cmake.Source --build $Build --config Release --target pds_windows_service_scm_probe --parallel 2
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $scmExe -PathType Leaf)) {
    throw 'BLOCKED_SLICE130_NATIVE_SCM_COMPILATION'
}
$scmBytes = [System.IO.File]::ReadAllBytes($scmExe)
if ($scmBytes.Length -lt 128 -or $scmBytes[0] -ne 77 -or $scmBytes[1] -ne 90) {
    throw 'Slice 130 native SCM executable is not MZ.'
}
$scmOffset = [System.BitConverter]::ToInt32($scmBytes, 0x3c)
if ($scmOffset -lt 64 -or $scmOffset -gt ($scmBytes.Length - 24) -or
    $scmBytes[$scmOffset] -ne 80 -or $scmBytes[$scmOffset + 1] -ne 69 -or
    $scmBytes[$scmOffset + 2] -ne 0 -or $scmBytes[$scmOffset + 3] -ne 0) {
    throw 'Slice 130 native SCM PE signature invalid.'
}
if ([System.BitConverter]::ToUInt16($scmBytes, $scmOffset + 4) -ne $expected) {
    throw 'Slice 130 native SCM architecture mismatch.'
}
Write-Host "SLICE130_SCM_COMPILED_$Architecture"

$hostArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($hostArchitecture -ne $Architecture) {
    Write-Host "SLICE129_TOKEN_PREFLIGHT_CROSS_BUILD_ONLY_$Architecture"
    exit 0
}

$lines = @(& $exe)
$code = $LASTEXITCODE
if ($code -notin @(1, 2) -or $lines.Count -ne 2) {
    throw 'Native token preflight returned invalid status.'
}
$data = $lines[0] | ConvertFrom-Json -ErrorAction Stop
$signals = ($data.token_elevation_observed -ceq $true -and
    $data.high_integrity_observed -ceq $true -and
    $data.administrators_group_enabled_observed -ceq $true)
$status = if ($code -eq 2) {
    'NATIVE_TOKEN_SIGNALS_OBSERVED_NO_AUTHORITY'
} elseif ($data.status -eq 'NATIVE_TOKEN_PREFLIGHT_UNAVAILABLE_NO_AUTHORITY') {
    'NATIVE_TOKEN_PREFLIGHT_UNAVAILABLE_NO_AUTHORITY'
} else {
    'NATIVE_TOKEN_PREFLIGHT_INSUFFICIENT_NO_AUTHORITY'
}
if ($data.status -ne $status -or
    ($code -eq 2) -cne $signals -or
    $data.independent_administrator_authenticated -cne $false -or
    $data.protected_provisioning_performed -cne $false -or
    $data.publisher_pin_provisioned -cne $false -or
    $data.rollback_protection_verified -cne $false -or
    $data.authorized_to_install -cne $false -or
    $data.authority -ne $NoAuthority -or
    $lines[1] -ne $NoAuthority) {
    throw 'Native token preflight claimed unsupported authority.'
}
$denyLines = @(& $exe --provision)
$denyCode = $LASTEXITCODE
if ($denyCode -ne 2 -or $denyLines.Count -ne 2) {
    throw 'Native token preflight did not refuse --provision.'
}
$denied = $denyLines[0] | ConvertFrom-Json -ErrorAction Stop
if ($denied.status -ne 'REFUSED_UNSUPPORTED_PROVISIONING_ARGUMENT' -or
    $denied.protected_provisioning_performed -cne $false -or
    $denied.independent_administrator_authenticated -cne $false -or
    $denied.authorized_to_install -cne $false -or
    $denyLines[1] -ne $NoAuthority) {
    throw 'Native token preflight refusal asserted unexpected authority.'
}
Write-Host "SLICE129_NATIVE_ADMIN_TOKEN_NO_AUTHORITY_PASSED_$Architecture"
$scmLines = @(& $scmExe)
$scmCode = $LASTEXITCODE
if ($scmCode -notin @(1, 2) -or $scmLines.Count -ne 2) {
    throw 'Slice 130 native SCM status invalid.'
}
$scm = $scmLines[0] | ConvertFrom-Json -ErrorAction Stop
$valid = ($scm.status -eq 'PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY' -or
    $scm.status -eq 'SCM_SECURITY_QUERY_REFUSED_NO_AUTHORITY' -or
    $scm.status -eq 'SCM_SECURITY_METADATA_OBSERVED_UNVERIFIED')
if (-not $valid -or
    (($scm.status -eq 'SCM_SECURITY_METADATA_OBSERVED_UNVERIFIED') -cne ($scmCode -eq 2)) -or
    $scm.native_read_only -cne $true -or
    $scm.service_identity_verified -cne $false -or
    $scm.effective_teacher_rights_verified -cne $false -or
    $scm.publisher_pin_provisioned -cne $false -or
    $scm.protected_state_write_performed -cne $false -or
    $scm.authorized_to_provision -cne $false -or
    $scm.authorized_to_install -cne $false -or
    $scm.authority -ne $NoAuthority -or $scmLines[1] -ne $NoAuthority) {
    throw 'Slice 130 SCM observation asserted unsupported authority.'
}
$scmDeniedLines = @(& $scmExe --install)
$scmDeniedCode = $LASTEXITCODE
if ($scmDeniedCode -ne 2 -or $scmDeniedLines.Count -ne 2) {
    throw 'Slice 130 SCM probe did not refuse install argument.'
}
$scmDenied = $scmDeniedLines[0] | ConvertFrom-Json -ErrorAction Stop
if ($scmDenied.status -ne 'REFUSED_UNSUPPORTED_SCM_ARGUMENT' -or
    $scmDenied.authorized_to_install -cne $false -or
    $scmDenied.authorized_to_provision -cne $false -or
    $scmDeniedLines[1] -ne $NoAuthority) {
    throw 'Slice 130 SCM install refusal invalid.'
}
Write-Host "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture"
exit 0
