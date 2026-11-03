# Suite #49 Slice 141: TEST-ONLY ephemeral RSA-PSS detached-signature authoring.
# Only called in ephemeral hosted Windows CI. Not a release signer or trust root.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SandboxRoot,
    [string] $Acknowledge = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
function Refuse([string] $Reason) {
    [Console]::Error.WriteLine('REFUSED_EPHEMERAL_SIGNER: ' + $Reason)
    [Console]::Error.WriteLine($noAuthority)
    exit 1
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_OS -cne 'Windows' -or
    $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $Acknowledge -cne 'EPHEMERAL_RSA_PSS_TEST_ONLY') {
    Refuse 'explicit hosted Windows test consent required'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Refuse 'elevated hosted test token required'
}
$parent = [IO.Path]::GetFullPath([Environment]::GetFolderPath(
    [Environment+SpecialFolder]::CommonApplicationData)).TrimEnd('\')
$root = [IO.Path]::GetFullPath($SandboxRoot)
$prefix = $parent + '\pds-suite49-osparent-sbx-'
if ($parent -notmatch '^[A-Za-z]:\\' -or
    -not $root.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
    $root.Substring($prefix.Length) -cnotmatch '^[0-9a-f]{32}$' -or
    $root -cne $SandboxRoot) {
    Refuse 'noncanonical disposable OS-anchored sandbox'
}
$payloadPath = Join-Path $root 'app-binaries\synthetic-suite49-test-payload.bin'
$stateDir = Join-Path $root 'protected-state\service-state'
$publicPath = Join-Path $stateDir 'test-only-publisher-public.spki'
$signaturePath = Join-Path $stateDir 'test-only-payload.detached.sig'
foreach ($path in @($root, $stateDir, $payloadPath)) {
    $entry = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Refuse 'redirected sandbox file or ancestor'
    }
}
if ((Test-Path -LiteralPath $publicPath) -or
    (Test-Path -LiteralPath $signaturePath)) {
    Refuse 'ephemeral signature replay or existing files'
}
$expectedBytes = [Text.Encoding]::ASCII.GetBytes(
    'PDS_SUITE49_SYNTHETIC_PAYLOAD_V1_NOT_A_SIGNED_RELEASE')
$payload = [IO.File]::ReadAllBytes($payloadPath)
if ([Convert]::ToBase64String($payload) -cne
    [Convert]::ToBase64String($expectedBytes)) {
    Refuse 'source payload not exact fixed synthetic bytes'
}
$domain = [Text.Encoding]::ASCII.GetBytes(
    "PDS_SUITE49_EPHEMERAL_TEST_SIGNATURE_V1`n")
[byte[]] $message = New-Object byte[] ($domain.Length + $payload.Length)
[Array]::Copy($domain, 0, $message, 0, $domain.Length)
[Array]::Copy($payload, 0, $message, $domain.Length, $payload.Length)
$rsa = $null
try {
    # The ephemeral private key exists ONLY in this one process's memory.
    $rsa = [Security.Cryptography.RSA]::Create(3072)
    if ($rsa.KeySize -ne 3072) { Refuse 'RSA-3072 unavailable' }
    [byte[]] $public = $rsa.ExportSubjectPublicKeyInfo()
    [byte[]] $signature = $rsa.SignData(
        $message, [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pss)
    if ($signature.Length -ne 384 -or $public.Length -lt 380 -or
        $public.Length -gt 1024) { Refuse 'invalid ephemeral test key shape' }
    [IO.File]::WriteAllBytes($publicPath, $public)
    [IO.File]::WriteAllBytes($signaturePath, $signature)
    # These are ordinary inherited admin-only test files, not production trust.
    foreach ($path in @($publicPath, $signaturePath)) {
        $entry = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if ($entry.PSIsContainer -or
            (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            Refuse 'redirected signature artifact'
        }
        $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
        $aces = @($acl.GetAccessRules($true, $true,
            [Security.Principal.SecurityIdentifier]))
        if ($aces.Count -ne 2 -or @($aces | Where-Object {
            $_.IdentityReference.Value -notin @('S-1-5-18', 'S-1-5-32-544') -or
            $_.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $_.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl
        }).Count -ne 0) { Refuse 'test key files have unexpected ACLs' }
    }
    $report = [ordered]@{
        status = 'EPHEMERAL_RSA_PSS_SIGNATURE_AUTHORED_TEST_ONLY'
        test_only_signature_written = $true
        private_key_written_to_disk = $false
        independently_authenticated_publisher = $false
        trusted_production_key_provisioned = $false
        authorized_to_install = $false
        authority = $noAuthority
    }
    [Console]::Out.WriteLine(($report | ConvertTo-Json -Compress -Depth 3))
    [Console]::Out.WriteLine($noAuthority)
    exit 2
} catch {
    Refuse 'ephemeral signing failed; inspect disposable hosted runner'
} finally {
    if ($null -ne $rsa) { $rsa.Dispose() }
}
