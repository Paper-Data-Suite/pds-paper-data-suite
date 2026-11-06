# Suite #49 Slice 139: OS-anchored parent DELETE access on ephemeral Windows CI.
# This script intentionally CREATES and ACL-protects only a random disposable
# child of Windows' OS-resolved CommonApplicationData directory on GitHub CI.
# Never invoked by the source-qualification runner or on a teacher machine.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_OS -cne 'Windows' -or
    $env:RUNNER_ENVIRONMENT -cne 'github-hosted') {
    throw 'REFUSED: only ephemeral hosted Windows CI may create OS-parent sandbox'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'REFUSED: elevated disposable administrator token unavailable'
}
$parent = [IO.Path]::GetFullPath([Environment]::GetFolderPath(
    [Environment+SpecialFolder]::CommonApplicationData)).TrimEnd('\')
if ($parent -notmatch '^[A-Za-z]:\\' -or $parent.Contains('..')) {
    throw 'REFUSED: canonical OS CommonApplicationData unavailable'
}
$parentEntry = Get-Item -LiteralPath $parent -Force -ErrorAction Stop
if (-not $parentEntry.PSIsContainer -or
    (($parentEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
    throw 'REFUSED: OS-known parent is redirected'
}
$parentSddlBefore = (Get-Acl -LiteralPath $parent -ErrorAction Stop).Sddl
$prefix = 'pds-suite49-osparent-sbx-'
$root = Join-Path $parent ($prefix + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $root) { throw 'REFUSED: random sandbox collision' }
$paths = @(
    $root,
    (Join-Path $root 'app-binaries'),
    (Join-Path $root 'protected-state'),
    (Join-Path $root 'protected-state\active-receipts'),
    (Join-Path $root 'protected-state\service-state')
)
$adminSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$inherit = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
# Mutation is restricted to these five randomly named disposable directories.
foreach ($path in $paths) {
    if (Test-Path -LiteralPath $path) { throw 'REFUSED: unexpected sandbox path' }
    [void][IO.Directory]::CreateDirectory($path)
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($old in @($acl.GetAccessRules($true, $false,
        [Security.Principal.SecurityIdentifier]))) {
        [void]$acl.RemoveAccessRuleSpecific($old)
    }
    foreach ($sid in @($systemSid, $adminSid)) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid, [Security.AccessControl.FileSystemRights]::FullControl,
            $inherit, [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $path -AclObject $acl -ErrorAction Stop
    $found = Get-Acl -LiteralPath $path -ErrorAction Stop
    $aces = @($found.GetAccessRules($true, $true,
        [Security.Principal.SecurityIdentifier]))
    if (-not $found.AreAccessRulesProtected -or $aces.Count -ne 2 -or
        @($aces | Where-Object {
            $_.IdentityReference.Value -notin @($adminSid.Value, $systemSid.Value) -or
            $_.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $_.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
            $_.IsInherited
        }).Count -ne 0) {
        throw 'REFUSED: sandbox DACL verification failed'
    }
}
$pwsh = (Get-Command -Name pwsh.exe -CommandType Application -ErrorAction Stop).Source
$ordinaryProbe = Join-Path $PSScriptRoot 'sandbox_ordinary_user_probe.ps1'
$externalProbe = Join-Path $PSScriptRoot 'sandbox_os_parent_probe.ps1'
foreach ($source in @($ordinaryProbe, $externalProbe)) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw 'REFUSED: fixed ordinary probe source missing'
    }
}
# A new local ordinary account is created only on this throwaway hosted runner.
$name = 'pdsacl_' + [guid]::NewGuid().ToString('N').Substring(0, 12)
if ($name.Length -gt 20) { throw 'REFUSED: invalid Windows test account length' }
$random = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($random)
$password = ConvertTo-SecureString ([Convert]::ToBase64String($random) + '!aA1') -AsPlainText -Force
$user = New-LocalUser -Name $name -Password $password `
    -Description 'Ephemeral OS-parent ACL test user' -PasswordNeverExpires `
    -UserMayNotChangePassword -ErrorAction Stop
$sid = $user.SID.Value
if ($sid -notmatch '^S-1-5-21-[0-9-]+$' -or
    @(Get-LocalGroupMember -SID $adminSid -ErrorAction Stop |
        Where-Object { $_.SID.Value -eq $sid }).Count -ne 0) {
    throw 'REFUSED: test account must be ordinary'
}
$testSid = [Security.Principal.SecurityIdentifier]::new($sid)
# Only root traversal (not write/delete) and control-directory Modify permitted.
$rootAcl = Get-Acl -LiteralPath $root -ErrorAction Stop
$traverse = [Security.AccessControl.FileSystemAccessRule]::new(
    $testSid, [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    [Security.AccessControl.InheritanceFlags]::None,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow)
$rootAcl.AddAccessRule($traverse)
Set-Acl -LiteralPath $root -AclObject $rootAcl -ErrorAction Stop
$control = Join-Path $root 'ordinary-control'
[void][IO.Directory]::CreateDirectory($control)
$controlAcl = Get-Acl -LiteralPath $control -ErrorAction Stop
$controlAcl.SetAccessRuleProtection($true, $false)
foreach ($old in @($controlAcl.GetAccessRules($true, $false,
    [Security.Principal.SecurityIdentifier]))) {
    [void]$controlAcl.RemoveAccessRuleSpecific($old)
}
foreach ($trusted in @($systemSid, $adminSid)) {
    $controlAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $trusted, [Security.AccessControl.FileSystemRights]::FullControl,
        $inherit, [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow))
}
$controlAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $testSid, [Security.AccessControl.FileSystemRights]::Modify,
    $inherit, [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow))
Set-Acl -LiteralPath $control -AclObject $controlAcl -ErrorAction Stop
[IO.File]::WriteAllText((Join-Path $control 'admin-prepared-control.txt'),
    'CI_ORDINARY_CONTROL_REACHABLE')
$credential = [PSCredential]::new("$env:COMPUTERNAME\$name", $password)
function Invoke-OrdinaryProbe([string] $Source) {
    $quotedSource = $Source.Replace("'", "''")
    $quotedRoot = $root.Replace("'", "''")
    $quotedSid = $sid.Replace("'", "''")
    $command = "& '$quotedSource' -SandboxRoot '$quotedRoot' -ExpectedSid '$quotedSid'; exit `$LASTEXITCODE"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process = Start-Process -FilePath $pwsh -ArgumentList @(
        '-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded) `
        -Credential $credential -PassThru -Wait -ErrorAction Stop
    if ($process.ExitCode -ne 0) {
        throw 'REFUSED: ordinary-user test process did not complete'
    }
}
# Slice 140: exactly one fixed, SYNTHETIC, disposable test artifact.
# Neither these bytes nor the hash are a PDS release or an authenticated signer.
$payloadPath = Join-Path $root 'app-binaries\synthetic-suite49-test-payload.bin'
$syntheticBytes = [Text.Encoding]::ASCII.GetBytes(
    'PDS_SUITE49_SYNTHETIC_PAYLOAD_V1_NOT_A_SIGNED_RELEASE')
$expectedPayloadSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($syntheticBytes)).ToLowerInvariant()
if (Test-Path -LiteralPath $payloadPath) {
    throw 'REFUSED: disposable synthetic artifact already exists'
}
[IO.File]::WriteAllBytes($payloadPath, $syntheticBytes)
$payloadFile = Get-Item -LiteralPath $payloadPath -Force -ErrorAction Stop
if ($payloadFile.PSIsContainer -or
    (($payloadFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -or
    $payloadFile.Length -ne $syntheticBytes.Length -or
    (Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        $expectedPayloadSha256) {
    throw 'REFUSED: staged synthetic test bytes disagree'
}
$payloadAcl = Get-Acl -LiteralPath $payloadPath -ErrorAction Stop
$payloadAces = @($payloadAcl.GetAccessRules($true, $true,
    [Security.Principal.SecurityIdentifier]))
if ($payloadAces.Count -ne 2 -or
    @($payloadAces | Where-Object {
        $_.IdentityReference.Value -notin @($adminSid.Value, $systemSid.Value) -or
        $_.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
        $_.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl
    }).Count -ne 0) {
    throw 'REFUSED: synthetic payload inherited untrusted access rules'
}
$payloadProbe = Join-Path $PSScriptRoot 'sandbox_protected_payload_probe.ps1'
if (-not (Test-Path -LiteralPath $payloadProbe -PathType Leaf)) {
    throw 'REFUSED: reviewed synthetic-payload probe missing'
}
Invoke-OrdinaryProbe $ordinaryProbe
Invoke-OrdinaryProbe $externalProbe
Invoke-OrdinaryProbe $payloadProbe
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
$ordinary = Get-Content -LiteralPath (Join-Path $control 'ordinary-proof.json') `
    -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
$external = Get-Content -LiteralPath (Join-Path $control 'os-parent-proof.json') `
    -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
$staged = Get-Content -LiteralPath (Join-Path $control 'payload-proof.json') `
    -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
if ($ordinary.status -ne 'DISPOSABLE_ORDINARY_TOKEN_DENIALS_OBSERVED_UNATTESTED' -or
    $ordinary.ordinary_user_sid -cne $sid -or
    $ordinary.positive_control_read_write -cne $true -or
    $ordinary.protected_directory_denials -ne 4 -or
    $ordinary.protected_object_delete_access_denials -ne 4 -or
    $ordinary.protected_parent_delete_child_access_denials -ne 4 -or
    $ordinary.no_delete_operation_performed -cne $true -or
    $ordinary.authorized_to_install -cne $false -or
    $ordinary.authority -ne $noAuthority -or
    $external.status -ne 'OS_ANCHORED_SANDBOX_DELETE_RIGHTS_DENIED_UNATTESTED' -or
    $external.ordinary_user_sid -cne $sid -or
    $external.ordinary_positive_control_delete_access -cne $true -or
    $external.sandbox_root_delete_access_denied -cne $true -or
    $external.os_parent_delete_child_access_denied -cne $true -or
    $external.no_delete_operation_performed -cne $true -or
    $external.os_parent_production_custody_verified -cne $false -or
    $external.installed_service_accepted -cne $false -or
    $external.authorized_to_install -cne $false -or
    $external.authority -ne $noAuthority -or
    $staged.status -ne 'SYNTHETIC_PAYLOAD_MUTATION_RIGHTS_DENIED_UNATTESTED' -or
    $staged.ordinary_user_sid -cne $sid -or
    $staged.positive_write_data_access -cne $true -or
    $staged.positive_append_data_access -cne $true -or
    $staged.positive_delete_access -cne $true -or
    $staged.synthetic_payload_mutation_denials -ne 4 -or
    $staged.payload_sha256 -cne $expectedPayloadSha256 -or
    $staged.no_payload_mutation_performed -cne $true -or
    $staged.release_artifact_signature_verified -cne $false -or
    $staged.protected_executable_custody_verified -cne $false -or
    $staged.installed_service_accepted -cne $false -or
    $staged.authorized_to_install -cne $false -or
    $staged.authority -ne $noAuthority) {
    throw 'REFUSED: evidence incomplete or asserts production authority'
}
if ((Get-Acl -LiteralPath $parent -ErrorAction Stop).Sddl -cne $parentSddlBefore) {
    throw 'REFUSED: OS parent ACL changed during sandbox test'
}
foreach ($path in $paths) {
    $entry = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (-not $entry.PSIsContainer -or
        (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'REFUSED: protected sandbox path replaced'
    }
}
# Independently re-read payload bytes after the standard user's handle probes.
$after = Get-Item -LiteralPath $payloadPath -Force -ErrorAction Stop
if ($after.PSIsContainer -or
    (($after.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -or
    $after.Length -ne $syntheticBytes.Length -or
    (Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        $expectedPayloadSha256 -or
    ([Convert]::ToBase64String([IO.File]::ReadAllBytes($payloadPath)) -cne
        [Convert]::ToBase64String($syntheticBytes))) {
    throw 'REFUSED: synthetic staged payload bytes changed'
}
$afterAcl = Get-Acl -LiteralPath $payloadPath -ErrorAction Stop
if ($afterAcl.Sddl -cne $payloadAcl.Sddl) {
    throw 'REFUSED: synthetic staged payload ACL changed'
}
# Slice 141: isolated RSA-PSS test-signing and independent verifier process.
# This uses a newly generated key for a SYNTHETIC file, never publisher trust.
$signer = Join-Path $PSScriptRoot 'sandbox_ephemeral_signer.ps1'
$verifier = Join-Path $PSScriptRoot 'sandbox_ephemeral_signature_verify.ps1'
foreach ($script in @($signer, $verifier)) {
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
        throw 'REFUSED: fixed synthetic cryptography script missing'
    }
}
$signed = @(& $pwsh -NoProfile -NonInteractive -File $signer `
    -SandboxRoot $root -Acknowledge 'EPHEMERAL_RSA_PSS_TEST_ONLY')
$signedCode = $LASTEXITCODE
if ($signedCode -ne 2 -or $signed.Count -ne 2) {
    throw 'REFUSED: ephemeral synthetic signing did not complete'
}
$signReport = $signed[0] | ConvertFrom-Json -ErrorAction Stop
if ($signReport.status -ne 'EPHEMERAL_RSA_PSS_SIGNATURE_AUTHORED_TEST_ONLY' -or
    $signReport.test_only_signature_written -cne $true -or
    $signReport.private_key_written_to_disk -cne $false -or
    $signReport.independently_authenticated_publisher -cne $false -or
    $signReport.trusted_production_key_provisioned -cne $false -or
    $signReport.authorized_to_install -cne $false -or
    $signReport.authority -ne $noAuthority -or $signed[1] -ne $noAuthority) {
    throw 'REFUSED: synthetic signer asserted unsupported publisher authority'
}
$trustPublicPath = Join-Path $root `
    'protected-state\service-state\test-only-publisher-public.spki'
$trustSigPath = Join-Path $root `
    'protected-state\service-state\test-only-payload.detached.sig'
$publicBefore = [IO.File]::ReadAllBytes($trustPublicPath)
# Capture a session-level pin in the administrator harness BEFORE the separate
# verifier process.  This does not authenticate the signer who created the key.
$sessionPublicKeySha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($publicBefore)).ToLowerInvariant()
$signatureBefore = [IO.File]::ReadAllBytes($trustSigPath)
$publicSddl = (Get-Acl -LiteralPath $trustPublicPath -ErrorAction Stop).Sddl
$signatureSddl = (Get-Acl -LiteralPath $trustSigPath -ErrorAction Stop).Sddl
$verified = @(& $pwsh -NoProfile -NonInteractive -File $verifier `
    -SandboxRoot $root -ExpectedPublicKeySha256 $sessionPublicKeySha256)
$verifiedCode = $LASTEXITCODE
if ($verifiedCode -ne 2 -or $verified.Count -ne 2) {
    throw 'REFUSED: separate synthetic RSA-PSS verifier did not qualify'
}
$verifyReport = $verified[0] | ConvertFrom-Json -ErrorAction Stop
if ($verifyReport.status -ne 'EPHEMERAL_RSA_PSS_VALID_AND_THREE_TAMPERS_DENIED' -or
    $verifyReport.valid_signature_verified -cne $true -or
    $verifyReport.changed_payload_rejected -cne $true -or
    $verifyReport.changed_signature_rejected -cne $true -or
    $verifyReport.substituted_public_key_rejected -cne $true -or
    $verifyReport.session_public_key_sha256_match -cne $true -or
    $verifyReport.self_signed_alternate_key_pair_rejected_by_pin -cne $true -or
    $verifyReport.independently_provisioned_publisher_pin_verified -cne $false -or
    $verifyReport.independent_publisher_provenance_verified -cne $false -or
    $verifyReport.trusted_release_artifact_verified -cne $false -or
    $verifyReport.production_rollback_protection_verified -cne $false -or
    $verifyReport.authorized_to_install -cne $false -or
    $verifyReport.authority -ne $noAuthority -or
    $verified[1] -ne $noAuthority) {
    throw 'REFUSED: test signature result promoted to production authority'
}
# Readback after the independent verifier; no protected artifacts may change.
if ((Get-Acl -LiteralPath $trustPublicPath -ErrorAction Stop).Sddl -cne
        $publicSddl -or
    (Get-Acl -LiteralPath $trustSigPath -ErrorAction Stop).Sddl -cne
        $signatureSddl -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($trustPublicPath)) -cne
        [Convert]::ToBase64String($publicBefore) -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($trustSigPath)) -cne
        [Convert]::ToBase64String($signatureBefore) -or
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
        [IO.File]::ReadAllBytes($payloadPath))).ToLowerInvariant() -cne
        $expectedPayloadSha256) {
    throw 'REFUSED: synthetic signed evidence or source bytes changed'
}
Write-Host 'SLICE142_EPHEMERAL_SESSION_PIN_BLOCKS_SELF_SIGNED_SUBSTITUTION'
Write-Host 'SLICE141_EPHEMERAL_RSA_PSS_VALID_AND_TAMPERS_REJECTED'
Write-Host 'SLICE140_EPHEMERAL_SYNTHETIC_PAYLOAD_MUTATION_RIGHTS_DENIED'
Write-Host 'SLICE139_EPHEMERAL_OS_ANCHORED_PARENT_DELETE_RIGHTS_DENIED'
Write-Host $noAuthority
# Account and sandbox persist solely for the lifetime of the ephemeral runner.
# No automatic removal, cleanup, rollback, or production installation occurs.
exit 0
