# Suite #49 Slice 141: independent-process TEST-ONLY RSA-PSS verification.
# The public key was made in the same ephemeral CI test, NOT pinned externally.
[CmdletBinding()]
param([Parameter(Mandatory = $true)] [string] $SandboxRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
function Refuse([string] $Reason) {
    [Console]::Error.WriteLine('REFUSED_EPHEMERAL_SIGNATURE_VERIFIER: ' + $Reason)
    [Console]::Error.WriteLine($noAuthority)
    exit 1
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_OS -cne 'Windows' -or
    $env:RUNNER_ENVIRONMENT -cne 'github-hosted') {
    Refuse 'hosted Windows CI required'
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
foreach ($path in @($root, $stateDir, $payloadPath, $publicPath, $signaturePath)) {
    $entry = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Refuse 'redirected test artifact or ancestor'
    }
}
$expectedBytes = [Text.Encoding]::ASCII.GetBytes(
    'PDS_SUITE49_SYNTHETIC_PAYLOAD_V1_NOT_A_SIGNED_RELEASE')
$payload = [IO.File]::ReadAllBytes($payloadPath)
if ([Convert]::ToBase64String($payload) -cne
    [Convert]::ToBase64String($expectedBytes)) {
    Refuse 'synthetic payload differs from expected bytes'
}
$public = [IO.File]::ReadAllBytes($publicPath)
$signature = [IO.File]::ReadAllBytes($signaturePath)
if ($public.Length -lt 380 -or $public.Length -gt 1024 -or
    $signature.Length -ne 384) { Refuse 'unexpected test key or signature length' }
# Encapsulate strict SPKI parsing and domain-separated RSA-PSS verification.
# This class does not consume caller-selected paths or any production key.
$source = @'
using System;
using System.Security.Cryptography;
using System.Text;
public static class PdsEphemeralRsaPss141 {
    public static bool Verify(byte[] spki, byte[] payload, byte[] signature) {
        try {
            using (RSA rsa = RSA.Create()) {
                rsa.ImportSubjectPublicKeyInfo(spki, out int consumed);
                if (consumed != spki.Length || rsa.KeySize != 3072 ||
                    signature.Length != 384) return false;
                byte[] prefix = Encoding.ASCII.GetBytes(
                    "PDS_SUITE49_EPHEMERAL_TEST_SIGNATURE_V1\n");
                byte[] message = new byte[prefix.Length + payload.Length];
                Buffer.BlockCopy(prefix, 0, message, 0, prefix.Length);
                Buffer.BlockCopy(payload, 0, message, prefix.Length, payload.Length);
                return rsa.VerifyData(message, signature, HashAlgorithmName.SHA256,
                                      RSASignaturePadding.Pss);
            }
        } catch (CryptographicException) { return false; }
          catch (ArgumentException) { return false; }
    }
}
'@
try {
    Add-Type -TypeDefinition $source -ErrorAction Stop
    if (-not [PdsEphemeralRsaPss141]::Verify($public, $payload, $signature)) {
        Refuse 'valid detached RSA-PSS signature did not verify'
    }
    [byte[]] $badPayload = [byte[]]$payload.Clone()
    $badPayload[0] = [byte]($badPayload[0] -bxor 1)
    if ([PdsEphemeralRsaPss141]::Verify($public, $badPayload, $signature)) {
        Refuse 'altered payload accepted'
    }
    [byte[]] $badSignature = [byte[]]$signature.Clone()
    $badSignature[0] = [byte]($badSignature[0] -bxor 1)
    if ([PdsEphemeralRsaPss141]::Verify($public, $payload, $badSignature)) {
        Refuse 'altered signature accepted'
    }
    $alternate = [Security.Cryptography.RSA]::Create(3072)
    try {
        $wrongKey = $alternate.ExportSubjectPublicKeyInfo()
        if ([PdsEphemeralRsaPss141]::Verify($wrongKey, $payload, $signature)) {
            Refuse 'wrong public key accepted'
        }
    } finally { $alternate.Dispose() }
    $report = [ordered]@{
        status = 'EPHEMERAL_RSA_PSS_VALID_AND_THREE_TAMPERS_DENIED'
        valid_signature_verified = $true
        changed_payload_rejected = $true
        changed_signature_rejected = $true
        substituted_public_key_rejected = $true
        independent_publisher_provenance_verified = $false
        trusted_release_artifact_verified = $false
        production_rollback_protection_verified = $false
        authorized_to_install = $false
        authority = $noAuthority
    }
    [Console]::Out.WriteLine(($report | ConvertTo-Json -Compress -Depth 3))
    [Console]::Out.WriteLine($noAuthority)
    exit 2
} catch {
    Refuse 'test-only signature verification failed'
}
