# Slice 137: CI-hosted, disposable second-account effective ACL denial acceptance.
# Never called by a source/commit runner or on a school/work machine.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_OS -cne 'Windows' -or
    $env:RUNNER_ENVIRONMENT -cne 'github-hosted') {
    throw 'REFUSED: second-account test is only for ephemeral hosted Windows CI'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'REFUSED: CI administrator token unavailable'
}
$pwsh = (Get-Command -Name pwsh.exe -CommandType Application -ErrorAction Stop).Source
$provision = Join-Path $PSScriptRoot 'sandbox_acl_provisioning.ps1'
$child = Join-Path $PSScriptRoot 'sandbox_ordinary_user_probe.ps1'
foreach ($file in @($provision, $child)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw 'Refused: exact source probe missing'
    }
}
# Actual write-capable ACL creation is isolated to the existing random temp sandbox.
$lines = @(& $pwsh -NoProfile -NonInteractive -File $provision `
    -ApplySandbox -Acknowledge 'SANDBOX_ACL_EXPERIMENT_ONLY')
$code = $LASTEXITCODE
if ($code -ne 2 -or $lines.Count -ne 2) {
    throw 'REFUSED: isolated administrator sandbox provisioning did not qualify'
}
$created = $lines[0] | ConvertFrom-Json -ErrorAction Stop
if ($created.status -ne 'DISPOSABLE_ACL_SANDBOX_CREATED_NOT_PRODUCTION' -or
    $created.authorized_to_install -cne $false -or
    $created.ordinary_user_effective_denial_attested -cne $false -or
    $created.authority -ne $noAuthority -or $lines[1] -ne $noAuthority) {
    throw 'REFUSED: sandbox provisioner claimed unauthorized installation authority'
}
$root = [IO.Path]::GetFullPath([string]$created.sandbox_root)
$temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (-not $root.StartsWith($temp + 'pds-suite49-acl-sandbox-',
    [StringComparison]::OrdinalIgnoreCase) -or
    $root.Substring(($temp + 'pds-suite49-acl-sandbox-').Length) -cnotmatch '^[0-9a-f]{32}$') {
    throw 'REFUSED: noncanonical disposable test root'
}
# A new, random and unprivileged LOCAL account, solely on the throwaway runner.
# Account and random password are never printed. No production principal exists.
$name = 'pdsacl_' + [guid]::NewGuid().ToString('N').Substring(0, 12)
if ($name.Length -gt 20) { throw 'REFUSED: test account name exceeds Windows limit' }
$random = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($random)
$secret = ([Convert]::ToBase64String($random) + '!aA1')
$password = ConvertTo-SecureString $secret -AsPlainText -Force
$user = New-LocalUser -Name $name -Password $password -Description 'PDS disposable CI ACL negative-test account' `
    -PasswordNeverExpires -UserMayNotChangePassword -ErrorAction Stop
$sid = $user.SID.Value
if ($sid -notmatch '^S-1-5-21-[0-9-]+$') { throw 'REFUSED: test account SID invalid' }
if (@(Get-LocalGroupMember -SID ([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')) `
    -ErrorAction Stop | Where-Object { $_.SID.Value -eq $sid }).Count -ne 0) {
    throw 'REFUSED: disposable test account unexpectedly administrator'
}
$testSid = [Security.Principal.SecurityIdentifier]::new($sid)
# Only the disposable sandbox root gets traversal, and an extra child gets
# Modify. None of the four already protected children gain any ordinary ACE.
$rootAcl = Get-Acl -LiteralPath $root -ErrorAction Stop
if (-not $rootAcl.AreAccessRulesProtected) { throw 'REFUSED: sandbox root ACL unprotected' }
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
$modify = [Security.AccessControl.FileSystemAccessRule]::new(
    $testSid, [Security.AccessControl.FileSystemRights]::Modify,
    ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit),
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow)
$controlAcl.AddAccessRule($modify)
foreach ($trustedSid in @('S-1-5-18', 'S-1-5-32-544')) {
    $trustedRule = [Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new($trustedSid),
        [Security.AccessControl.FileSystemRights]::FullControl,
        ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit),
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow)
    $controlAcl.AddAccessRule($trustedRule)
}
Set-Acl -LiteralPath $control -AclObject $controlAcl -ErrorAction Stop
[IO.File]::WriteAllText((Join-Path $control 'admin-prepared-control.txt'),
    'CI_ORDINARY_CONTROL_REACHABLE')
# Avoid fragile command-line quoting; only the fixed source script and the
# verified disposable path are inserted into an EncodedCommand.
$escapedScript = $child.Replace("'", "''")
$escapedRoot = $root.Replace("'", "''")
$escapedSid = $sid.Replace("'", "''")
$command = "& '$escapedScript' -SandboxRoot '$escapedRoot' -ExpectedSid '$escapedSid'; exit `$LASTEXITCODE"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$credential = [PSCredential]::new(("$env:COMPUTERNAME\$name"), $password)
$process = Start-Process -FilePath $pwsh -ArgumentList @('-NoProfile', '-NonInteractive',
    '-EncodedCommand', $encoded) -Credential $credential -PassThru -Wait -ErrorAction Stop
if ($process.ExitCode -ne 0) {
    throw 'REFUSED: second-account negative-access probe failed'
}
$positive = Join-Path $control 'ordinary-positive-write.txt'
$proofPath = Join-Path $control 'ordinary-proof.json'
if (-not (Test-Path -LiteralPath $positive -PathType Leaf) -or
    [IO.File]::ReadAllText($positive) -cne 'ORDINARY_WRITE_SUCCEEDED' -or
    -not (Test-Path -LiteralPath $proofPath -PathType Leaf)) {
    throw 'REFUSED: ordinary account could not pass positive access control'
}
$proof = Get-Content -LiteralPath $proofPath -Raw -ErrorAction Stop |
    ConvertFrom-Json -ErrorAction Stop
if ($proof.status -ne 'DISPOSABLE_ORDINARY_TOKEN_DENIALS_OBSERVED_UNATTESTED' -or
    $proof.ordinary_user_sid -cne $sid -or
    $proof.positive_control_read_write -cne $true -or
    $proof.protected_directory_denials -ne 4 -or
    $proof.independently_attested_teacher_identity -cne $false -or
    $proof.parent_deletion_protection_verified -cne $false -or
    $proof.installed_service_accepted -cne $false -or
    $proof.authorized_to_install -cne $false -or $proof.authority -ne $noAuthority) {
    throw 'REFUSED: second-account negative-acceptance evidence invalid'
}
$protected = @((Join-Path $root 'app-binaries'),
    (Join-Path $root 'protected-state'),
    (Join-Path $root 'protected-state\active-receipts'),
    (Join-Path $root 'protected-state\service-state'))
foreach ($path in $protected) {
    if (Test-Path -LiteralPath (Join-Path $path 'ordinary-should-never-write.txt')) {
        throw 'REFUSED: ordinary account wrote into protected sandbox'
    }
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    $aces = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $acl.AreAccessRulesProtected -or $aces.Count -ne 2 -or
        @($aces | Where-Object { $_.IdentityReference.Value -eq $sid }).Count -ne 0) {
        throw 'REFUSED: protected sandbox ACEs were changed'
    }
}
Write-Host 'SLICE137_EPHEMERAL_STANDARD_USER_POSITIVE_AND_FOUR_NEGATIVE_ACL_CHECKS_PASSED'
Write-Host $noAuthority
# The account and sandbox persist only within the disposable CI runner;
# no unreviewed user deletion, cleanup, rollback or production write.
exit 0
