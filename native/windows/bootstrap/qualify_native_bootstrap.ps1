# Suite #49 Slice 122. Windows native bootstrap build/runtime qualification.
# Does NOT install, elevate, sign, register services, write receipts, or mutate classroom data.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('x64', 'ARM64')]
    [string] $Architecture,
    [ValidateSet('Visual Studio 17 2022', 'Visual Studio 18 2026')]
    [string] $Generator = 'Visual Studio 17 2022',
    [switch] $RequireRuntime
)

$ErrorActionPreference = 'Stop'
# Expected nonzero native diagnostic exits are evaluated explicitly below.
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest

$noAuthority = 'NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY'
$source = $PSScriptRoot
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Native bootstrap qualification requires Windows.'
}
if (-not (Test-Path -LiteralPath (Join-Path $source 'bootstrap_probe.cpp') -PathType Leaf)) {
    throw 'Native bootstrap source unavailable.'
}
if (-not (Test-Path -LiteralPath (Join-Path $source 'CMakeLists.txt') -PathType Leaf)) {
    throw 'Native bootstrap CMake project unavailable.'
}
$cmake = Get-Command -Name 'cmake.exe' -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $cmake) {
    throw 'BLOCKED_NATIVE_TOOLCHAIN_NOT_INSTALLED: CMake executable is missing.'
}

# This directory is disposable and outside the source tree or classroom workspace.
# It is intentionally retained for inspection; no cleanup or rollback command runs.
$root = Join-Path ([System.IO.Path]::GetTempPath()) ('pds-suite49-native122-' + [guid]::NewGuid().ToString('N'))
$build = Join-Path $root 'build'
New-Item -ItemType Directory -Path $build -Force | Out-Null
Write-Host "SLICE122_BUILD_ROOT: $root"
Write-Host "SLICE122_TARGET_ARCH: $Architecture"

& $cmake.Source -S $source -B $build -G $Generator -A $Architecture
if ($LASTEXITCODE -ne 0) {
    throw 'BLOCKED_NATIVE_CMAKE_CONFIGURE_FAILED: VS2022 C++ toolchain or Windows SDK unavailable.'
}
& $cmake.Source --build $build --config Release --target pds_windows_bootstrap_probe pds_checkpoint_contract_test --parallel 2
if ($LASTEXITCODE -ne 0) {
    throw 'BLOCKED_NATIVE_COMPILATION_FAILED: the native bootstrap source did not compile.'
}

$exe = Join-Path $build 'Release\pds_windows_bootstrap_probe.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw 'Native bootstrap executable missing after successful build.'
}
# Verify the actual Portable Executable machine type rather than trusting a filename.
$bytes = [System.IO.File]::ReadAllBytes($exe)
if ($bytes.Length -lt 128 -or $bytes[0] -ne 77 -or $bytes[1] -ne 90) {
    throw 'Compiled native bootstrap is not a valid MZ image.'
}
$peOffset = [System.BitConverter]::ToInt32($bytes, 0x3c)
if ($peOffset -lt 64 -or $peOffset -gt ($bytes.Length - 24)) {
    throw 'Compiled native bootstrap has an invalid PE header offset.'
}
if ($bytes[$peOffset] -ne 80 -or $bytes[$peOffset + 1] -ne 69 -or
    $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) {
    throw 'Compiled native bootstrap has an invalid PE signature.'
}
$machine = [System.BitConverter]::ToUInt16($bytes, $peOffset + 4)
$expectedMachine = if ($Architecture -eq 'x64') { [uint16]0x8664 } else { [uint16]0xaa64 }
if ($machine -ne $expectedMachine) {
    throw ('Native binary target architecture mismatch: expected 0x{0:X4}, observed 0x{1:X4}.' -f $expectedMachine, $machine)
}
$digest = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "SLICE122_NATIVE_BINARY_SHA256: $digest"
Write-Host "SLICE122_NATIVE_COMPILED_$Architecture"

$contractExe = Join-Path $build 'Release\pds_checkpoint_contract_test.exe'
if (-not (Test-Path -LiteralPath $contractExe -PathType Leaf)) {
    throw 'Native checkpoint contract test executable is missing.'
}

$hostArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($Architecture -ne $hostArchitecture) {
    if ($RequireRuntime) {
        throw "BLOCKED_NATIVE_RUNTIME_ARCH_MISMATCH: target $Architecture on host $hostArchitecture."
    }
    Write-Host "SLICE122_CROSS_COMPILED_ONLY: $Architecture (host $hostArchitecture)"
    return
}

# Execute native C++ parser/relationship negative tests on the actual target CPU.
# Cross-compiled ARM64 is tested by the separate native Windows 11 ARM64 job.
$contractOutput = @(& $contractExe)
$contractExit = $LASTEXITCODE
if ($contractExit -ne 0 -or $contractOutput.Count -ne 1 -or
    $contractOutput[0] -ne 'SLICE124_NATIVE_CHECKPOINT_CONTRACT_TESTS_PASSED') {
    throw 'Native C++ checkpoint contract tests failed or returned unexpected output.'
}
Write-Host "SLICE124_NATIVE_CHECKPOINT_CONTRACT_PASSED_$Architecture"

function Assert-NoAuthorityOutput {
    param([string[]] $Lines, [int] $Code, [string] $ExpectedStatus)
    if ($Lines.Count -ne 2) {
        throw 'Native diagnostic must produce exactly two output lines.'
    }
    $data = $Lines[0] | ConvertFrom-Json -ErrorAction Stop
    if ($data.status -ne $ExpectedStatus -or
        $data.native_read_only -cne $true -or
        $data.protected_write_performed -cne $false -or
        $data.administrator_authenticated -cne $false -or
        $data.service_identity_verified -cne $false -or
        $data.production_authority -cne $false -or
        $data.active_receipt_authority -cne $false -or
        $data.authority -ne $noAuthority -or
        $Lines[1] -ne $noAuthority) {
        throw 'Native diagnostic output asserted unexpected authority or status.'
    }
    if ($Code -notin @(1, 2)) {
        throw "Native diagnostic produced unexpected status code $Code."
    }
}

# No state is provisioned in CI; refused/observational are both acceptable.
$lines = @(& $exe)
$code = $LASTEXITCODE
if ($lines.Count -ne 2) {
    throw 'Native no-argument diagnostic returned invalid output.'
}
$observed = ($lines[0] | ConvertFrom-Json -ErrorAction Stop).status
if ($observed -notin @('NATIVE_WINDOWS_CHECKPOINT_CUSTODY_NOT_ESTABLISHED', 'NATIVE_WINDOWS_CHECKPOINT_BYTES_OBSERVED_ONLY')) {
    throw 'Native diagnostic status is not recognized.'
}
Assert-NoAuthorityOutput -Lines $lines -Code $code -ExpectedStatus $observed
if (($observed -eq 'NATIVE_WINDOWS_CHECKPOINT_CUSTODY_NOT_ESTABLISHED' -and $code -ne 1) -or
    ($observed -eq 'NATIVE_WINDOWS_CHECKPOINT_BYTES_OBSERVED_ONLY' -and $code -ne 2)) {
    throw 'Native no-argument diagnostic status and exit code disagree.'
}
Write-Host "SLICE122_NATIVE_READ_ONLY_DIAGNOSTIC: $observed"

# Explicit negative-security smoke: an unsigned diagnostic must refuse mutation flags.
$bad = @(& $exe --apply)
$badCode = $LASTEXITCODE
Assert-NoAuthorityOutput -Lines $bad -Code $badCode -ExpectedStatus 'REFUSED_UNSUPPORTED_NATIVE_BOOTSTRAP_ARGUMENT'
if ($badCode -ne 2) {
    throw 'Native executable did not refuse an attempted --apply request.'
}
Write-Host 'SLICE122_NATIVE_APPLY_FLAG_REFUSED'
if ($Architecture -eq 'ARM64' -and $RequireRuntime) {
    Write-Host 'SLICE123_NATIVE_ARM64_RUNTIME_PASSED'
}
Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"
exit 0
