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

# Separate unsigned signature witness: no signing key, publisher pin or installer privilege.
if (-not (Test-Path -LiteralPath (Join-Path $source 'signature_probe.cpp') -PathType Leaf)) {
    throw 'Native signature witness source unavailable.'
}
# Slice 126: compile a separate portable claimed-pin policy contract test.
& $cmake.Source --build $build --config Release --target pds_publisher_pin_contract_test --parallel 2
if ($LASTEXITCODE -ne 0) {
    throw 'BLOCKED_NATIVE_PUBLISHER_PIN_CONTRACT_COMPILATION_FAILED.'
}
# Slice 127: compile pure certificate/SPKI-to-claimed-pin comparison tests.
& $cmake.Source --build $build --config Release --target pds_publisher_pin_evidence_test --parallel 2
if ($LASTEXITCODE -ne 0) {
    throw 'BLOCKED_NATIVE_PUBLISHER_EVIDENCE_COMPILATION_FAILED.'
}
& $cmake.Source --build $build --config Release --target pds_windows_signature_probe --parallel 2
if ($LASTEXITCODE -ne 0) {
    throw 'BLOCKED_NATIVE_SIGNATURE_WITNESS_COMPILATION_FAILED.'
}
# Slice 128: a separate native, non-authorizing fixed-path custody probe.
if (-not (Test-Path -LiteralPath (Join-Path $source 'publisher_pin_custody_probe.cpp') -PathType Leaf)) {
    throw 'Publisher-pin custody probe source unavailable.'
}
& $cmake.Source --build $build --config Release --target pds_windows_publisher_pin_custody_probe --parallel 2
if ($LASTEXITCODE -ne 0) {
    throw 'BLOCKED_NATIVE_PIN_CUSTODY_PROBE_COMPILATION_FAILED.'
}
$pinCustodyExe = Join-Path $build 'Release\pds_windows_publisher_pin_custody_probe.exe'
if (-not (Test-Path -LiteralPath $pinCustodyExe -PathType Leaf)) {
    throw 'Native publisher-pin custody probe executable unavailable.'
}

$signatureExe = Join-Path $build 'Release\pds_windows_signature_probe.exe'
if (-not (Test-Path -LiteralPath $signatureExe -PathType Leaf)) {
    throw 'Compiled native signature witness missing.'
}
$signatureDigest = (Get-FileHash -LiteralPath $signatureExe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "SLICE125_UNSIGNED_SIGNATURE_WITNESS_SHA256: $signatureDigest"

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
# The separately compiled signer witness must match the same PE architecture.
$sigImage = [System.IO.File]::ReadAllBytes($signatureExe)
if ($sigImage.Length -lt 128 -or $sigImage[0] -ne 77 -or $sigImage[1] -ne 90) {
    throw 'Native signature witness is not a valid MZ image.'
}
$sigPeOffset = [System.BitConverter]::ToInt32($sigImage, 0x3c)
if ($sigPeOffset -lt 64 -or $sigPeOffset -gt ($sigImage.Length - 24) -or
    $sigImage[$sigPeOffset] -ne 80 -or $sigImage[$sigPeOffset + 1] -ne 69 -or
    $sigImage[$sigPeOffset + 2] -ne 0 -or $sigImage[$sigPeOffset + 3] -ne 0) {
    throw 'Native signature witness has an invalid PE header.'
}
$sigMachine = [System.BitConverter]::ToUInt16($sigImage, $sigPeOffset + 4)
if ($sigMachine -ne $expectedMachine) {
    throw 'Native signature witness target architecture mismatch.'
}
# Check the custody probe's actual PE machine type as well.
$pinImage = [System.IO.File]::ReadAllBytes($pinCustodyExe)
if ($pinImage.Length -lt 128 -or $pinImage[0] -ne 77 -or $pinImage[1] -ne 90) {
    throw 'Native publisher pin custody probe lacks MZ signature.'
}
$pinOffset = [System.BitConverter]::ToInt32($pinImage, 0x3c)
if ($pinOffset -lt 64 -or $pinOffset -gt ($pinImage.Length - 24) -or
    $pinImage[$pinOffset] -ne 80 -or $pinImage[$pinOffset + 1] -ne 69 -or
    $pinImage[$pinOffset + 2] -ne 0 -or $pinImage[$pinOffset + 3] -ne 0) {
    throw 'Native publisher pin custody probe has invalid PE header.'
}
$pinMachine = [System.BitConverter]::ToUInt16($pinImage, $pinOffset + 4)
if ($pinMachine -ne $expectedMachine) {
    throw 'Publisher pin custody probe PE architecture mismatch.'
}
Write-Host "SLICE128_NATIVE_PIN_CUSTODY_TARGET_VERIFIED_$Architecture"
Write-Host "SLICE125_NATIVE_SIGNATURE_TARGET_VERIFIED_$Architecture"
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

# All native publisher pin tests run only on a matching CPU, not emulation.
$pinContractExe = Join-Path $build 'Release\pds_publisher_pin_contract_test.exe'
if (-not (Test-Path -LiteralPath $pinContractExe -PathType Leaf)) {
    throw 'Native publisher pin contract test executable missing.'
}
$pinResult = @(& $pinContractExe)
$pinCode = $LASTEXITCODE
if ($pinCode -ne 0 -or $pinResult.Count -ne 1 -or
    $pinResult[0] -ne 'SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_TESTS_PASSED') {
    throw 'Native publisher pin schema or transition test failed.'
}
Write-Host "SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_PASSED_$Architecture"

# Native signer/pin evidence comparison cannot authenticate unprotected policy.
$evidenceExe = Join-Path $build 'Release\pds_publisher_pin_evidence_test.exe'
if (-not (Test-Path -LiteralPath $evidenceExe -PathType Leaf)) {
    throw 'Native publisher evidence contract executable missing.'
}
$evidenceResult = @(& $evidenceExe)
$evidenceCode = $LASTEXITCODE
if ($evidenceCode -ne 0 -or $evidenceResult.Count -ne 1 -or
    $evidenceResult[0] -ne 'SLICE127_NATIVE_PUBLISHER_EVIDENCE_TESTS_PASSED') {
    throw 'Native publisher certificate/SPKI evidence comparison tests failed.'
}
Write-Host "SLICE127_NATIVE_PUBLISHER_EVIDENCE_PASSED_$Architecture"

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

# The CI-built witness has no Authenticode signature: reject and retain no authority.
$sigLines = @(& $signatureExe)
$sigCode = $LASTEXITCODE
if ($sigLines.Count -ne 2 -or $sigCode -ne 1) {
    throw 'Unsigned native signature witness did not fail closed.'
}
$sig = $sigLines[0] | ConvertFrom-Json -ErrorAction Stop
if ($sig.status -ne 'NATIVE_SIGNATURE_NOT_TRUSTED' -or
    $sig.wintrust_chain_observed -cne $false -or
    $sig.signer_evidence_observed -cne $false -or
    $sig.publisher_pin_verified -cne $false -or
    $sig.authorized_to_install -cne $false -or
    $sig.authority -ne $noAuthority -or
    $sigLines[1] -ne $noAuthority) {
    throw 'Unsigned signature witness incorrectly claimed trusted installer authority.'
}
$sigRefused = @(& $signatureExe --install)
$sigRefusalCode = $LASTEXITCODE
if ($sigRefusalCode -ne 2 -or $sigRefused.Count -ne 2) {
    throw 'Native signature witness did not refuse install switch.'
}
$sigDenied = $sigRefused[0] | ConvertFrom-Json -ErrorAction Stop
if ($sigDenied.status -ne 'REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT' -or
    $sigDenied.signer_evidence_observed -cne $false -or
    $sigDenied.authorized_to_install -cne $false -or
    $sigRefused[1] -ne $noAuthority) {
    throw 'Native signature witness install denial invalid.'
}
Write-Host 'SLICE125_NATIVE_UNSIGNED_SIGNATURE_AND_INSTALL_REFUSAL_PASSED'

# No provisioning occurs in CI. Both absence and observation are non-authorizing.
$pinLines = @(& $pinCustodyExe)
$pinCode = $LASTEXITCODE
if ($pinLines.Count -ne 2 -or $pinCode -notin @(1, 2)) {
    throw 'Native publisher-pin custody probe returned invalid result.'
}
$pinResult = $pinLines[0] | ConvertFrom-Json -ErrorAction Stop
$pinExpected = if ($pinCode -eq 1) {
    'NATIVE_PIN_CLAIM_NOT_OBSERVED'
} else {
    'NATIVE_PIN_CLAIM_OBSERVED_CUSTODY_UNPROVEN'
}
if ($pinResult.status -ne $pinExpected -or
    $pinResult.native_read_only -cne $true -or
    $pinResult.publisher_pin_claim_observed -cne ($pinCode -eq 2) -or
    $pinResult.independent_provisioner_authenticated -cne $false -or
    $pinResult.rollback_protection_verified -cne $false -or
    $pinResult.publisher_pin_verified -cne $false -or
    $pinResult.authorized_to_install -cne $false -or
    $pinResult.authority -ne $noAuthority -or
    $pinLines[1] -ne $noAuthority) {
    throw 'Publisher pin custody probe asserted unexpected authority.'
}
$pinDeniedLines = @(& $pinCustodyExe --install)
$pinDeniedCode = $LASTEXITCODE
if ($pinDeniedCode -ne 2 -or $pinDeniedLines.Count -ne 2) {
    throw 'Publisher pin custody probe did not refuse --install.'
}
$pinDenied = $pinDeniedLines[0] | ConvertFrom-Json -ErrorAction Stop
if ($pinDenied.status -ne 'REFUSED_UNSUPPORTED_PUBLISHER_PIN_ARGUMENT' -or
    $pinDenied.authorized_to_install -cne $false -or
    $pinDenied.publisher_pin_verified -cne $false -or
    $pinDeniedLines[1] -ne $noAuthority) {
    throw 'Publisher pin custody probe install refusal invalid.'
}
Write-Host "SLICE128_NATIVE_PIN_CUSTODY_NO_AUTHORITY_PASSED_$Architecture"

if ($Architecture -eq 'ARM64' -and $RequireRuntime) {
    Write-Host 'SLICE123_NATIVE_ARM64_RUNTIME_PASSED'
}
Write-Host "SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_$Architecture"
exit 0
