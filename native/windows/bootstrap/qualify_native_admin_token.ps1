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


# Slice 131: independently compile and observe current-token OpenService access.
$accessExe = Join-Path $Build 'Release\pds_windows_service_access_probe.exe'
& $cmake.Source --build $Build --config Release --target pds_windows_service_access_probe --parallel 2
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $accessExe -PathType Leaf)) {
    throw 'BLOCKED_SLICE131_NATIVE_SERVICE_ACCESS_COMPILATION'
}
$accessBytes = [System.IO.File]::ReadAllBytes($accessExe)
if ($accessBytes.Length -lt 128 -or $accessBytes[0] -ne 77 -or $accessBytes[1] -ne 90) {
    throw 'Slice 131 access probe is not an MZ executable.'
}
$accessOffset = [System.BitConverter]::ToInt32($accessBytes, 0x3c)
if ($accessOffset -lt 64 -or $accessOffset -gt ($accessBytes.Length - 24) -or
    $accessBytes[$accessOffset] -ne 80 -or $accessBytes[$accessOffset + 1] -ne 69 -or
    $accessBytes[$accessOffset + 2] -ne 0 -or $accessBytes[$accessOffset + 3] -ne 0) {
    throw 'Slice 131 access probe PE header invalid.'
}
if ([System.BitConverter]::ToUInt16($accessBytes, $accessOffset + 4) -ne $expected) {
    throw 'Slice 131 access probe architecture mismatch.'
}
Write-Host "SLICE131_SCM_ACCESS_COMPILED_$Architecture"

# Slice 132: compile a separate ordinary-primary-token/SCM denial witness.
$teacherExe = Join-Path $Build 'Release\pds_windows_teacher_denial_probe.exe'
& $cmake.Source --build $Build --config Release --target pds_windows_teacher_denial_probe --parallel 2
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $teacherExe -PathType Leaf)) {
    throw 'BLOCKED_SLICE132_NATIVE_TEACHER_DENIAL_COMPILATION'
}
$teacherBytes = [System.IO.File]::ReadAllBytes($teacherExe)
if ($teacherBytes.Length -lt 128 -or $teacherBytes[0] -ne 77 -or $teacherBytes[1] -ne 90) {
    throw 'Slice 132 teacher denial probe is not an MZ executable.'
}
$teacherOffset = [System.BitConverter]::ToInt32($teacherBytes, 0x3c)
if ($teacherOffset -lt 64 -or $teacherOffset -gt ($teacherBytes.Length - 24) -or
    $teacherBytes[$teacherOffset] -ne 80 -or $teacherBytes[$teacherOffset + 1] -ne 69 -or
    $teacherBytes[$teacherOffset + 2] -ne 0 -or $teacherBytes[$teacherOffset + 3] -ne 0) {
    throw 'Slice 132 teacher denial probe PE header invalid.'
}
if ([System.BitConverter]::ToUInt16($teacherBytes, $teacherOffset + 4) -ne $expected) {
    throw 'Slice 132 teacher denial probe architecture mismatch.'
}
Write-Host "SLICE132_TEACHER_DENIAL_COMPILED_$Architecture"

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
# Cross-compiled ARM64 is never represented as executed runtime coverage.
# The native ARM64 CI job separately executes this same diagnostic.
if ($hostArchitecture -eq $Architecture) {
    $accessLines = @(& $accessExe)
    $accessCode = $LASTEXITCODE
    if ($accessCode -notin @(1, 2) -or $accessLines.Count -ne 2) {
        throw 'Slice 131 service access observation returned invalid status.'
    }
    $access = $accessLines[0] | ConvertFrom-Json -ErrorAction Stop
    $complete = ($access.status -eq 'SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED')
    if (($complete -cne ($accessCode -eq 2)) -or
        $access.native_read_only -cne $true -or
        $access.access_query_complete -cne $complete -or
        $access.independent_teacher_token_verified -cne $false -or
        $access.service_identity_verified -cne $false -or
        $access.protected_state_write_performed -cne $false -or
        $access.authorized_to_provision -cne $false -or
        $access.authorized_to_install -cne $false -or
        $access.authority -ne $NoAuthority -or
        $accessLines[1] -ne $NoAuthority) {
        throw 'Slice 131 current-token observation asserted unsupported authority.'
    }
    if ($access.status -notin @(
        'PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY',
        'SCM_CURRENT_TOKEN_ACCESS_QUERY_REFUSED_NO_AUTHORITY',
        'SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED')) {
        throw 'Slice 131 unexpected service access status.'
    }
    $refusedLines = @(& $accessExe --configure)
    $refusedCode = $LASTEXITCODE
    if ($refusedCode -ne 2 -or $refusedLines.Count -ne 2) {
        throw 'Slice 131 service access probe did not refuse --configure.'
    }
    $refused = $refusedLines[0] | ConvertFrom-Json -ErrorAction Stop
    if ($refused.status -ne 'REFUSED_UNSUPPORTED_SERVICE_ACCESS_ARGUMENT' -or
        $refused.access_query_complete -cne $false -or
        $refused.authorized_to_provision -cne $false -or
        $refused.authorized_to_install -cne $false -or
        $refusedLines[1] -ne $NoAuthority) {
        throw 'Slice 131 current-token refusal asserted unsupported authority.'
    }
    Write-Host "SLICE131_NATIVE_SCM_CURRENT_TOKEN_NO_AUTHORITY_PASSED_$Architecture"
}
# Real source-only witness, not a separately authenticated ordinary user.
$teacherLines = @(& $teacherExe)
$teacherCode = $LASTEXITCODE
if ($teacherCode -notin @(1, 2) -or $teacherLines.Count -ne 2) {
    throw 'Slice 132 teacher denial probe returned invalid status.'
}
$teacher = $teacherLines[0] | ConvertFrom-Json -ErrorAction Stop
$allowedStatuses = @(
    'ORDINARY_TOKEN_QUERY_REFUSED_NO_ACCEPTANCE',
    'CURRENT_TOKEN_NOT_ORDINARY_NO_ACCEPTANCE',
    'SERVICE_NOT_INSTALLED_NO_TEACHER_ACCEPTANCE',
    'SERVICE_RIGHTS_QUERY_REFUSED_NO_ACCEPTANCE',
    'DANGEROUS_SCM_RIGHT_GRANTED_NO_ACCEPTANCE',
    'ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED'
)
$denials = $teacher.status -eq 'ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED'
if ($teacher.status -notin $allowedStatuses -or
    ($teacherCode -eq 2) -cne $denials -or
    $teacher.native_read_only -cne $true -or
    $teacher.independent_teacher_identity_attested -cne $false -or
    $teacher.installed_service_identity_verified -cne $false -or
    $teacher.publisher_pin_provisioned -cne $false -or
    $teacher.protected_write_performed -cne $false -or
    $teacher.authorized_to_install -cne $false -or
    $teacher.authority -ne $NoAuthority -or
    $teacherLines[1] -ne $NoAuthority) {
    throw 'Slice 132 teacher witness claimed unsupported authority.'
}
if ($denials -and ($teacher.service_present -cne $true -or
    $teacher.ordinary_primary_token_observed -cne $true -or
    $teacher.access_checks_complete -cne $true -or
    $teacher.all_eight_dangerous_rights_denied -cne $true -or
    $teacher.any_dangerous_right_granted -cne $false)) {
    throw 'Slice 132 denial status contradicts its evidence.'
}
$teacherDeniedLines = @(& $teacherExe --accept)
$teacherDeniedCode = $LASTEXITCODE
if ($teacherDeniedCode -ne 2 -or $teacherDeniedLines.Count -ne 2) {
    throw 'Slice 132 teacher witness did not refuse --accept.'
}
$teacherDenied = $teacherDeniedLines[0] | ConvertFrom-Json -ErrorAction Stop
if ($teacherDenied.status -ne 'REFUSED_UNSUPPORTED_TEACHER_ACCEPTANCE_ARGUMENT' -or
    $teacherDenied.authorized_to_install -cne $false -or
    $teacherDenied.independent_teacher_identity_attested -cne $false -or
    $teacherDeniedLines[1] -ne $NoAuthority) {
    throw 'Slice 132 teacher witness argument refusal invalid.'
}
Write-Host "SLICE132_NATIVE_TEACHER_DENIAL_NONAUTHORITY_PASSED_$Architecture"
Write-Host "SLICE130_NATIVE_SCM_NONAUTHORITY_PASSED_$Architecture"
exit 0
