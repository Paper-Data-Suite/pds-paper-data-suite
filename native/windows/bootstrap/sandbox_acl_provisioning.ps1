# Suite #49 Slice 136. DISPOSABLE ACL EXPERIMENT, NOT A PRODUCTION INSTALLER.
# This is the first write-capable Windows provisioning prototype. It never targets
# Program Files, ProgramData, SCM, registered services, receipts or classroom data.
[CmdletBinding()]
param(
    [switch] $ApplySandbox,
    [string] $Acknowledge = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$noAuthority = 'NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY'

function Refuse([string] $Reason) {
    [Console]::Error.WriteLine('REFUSED_SANDBOX_PROVISIONING: ' + $Reason)
    [Console]::Error.WriteLine($noAuthority)
    exit 1
}
if (-not $ApplySandbox -or $Acknowledge -cne 'SANDBOX_ACL_EXPERIMENT_ONLY') {
    Refuse 'explicit isolated-test acknowledgement required'
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Refuse 'Windows required'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Refuse 'current process is not an elevated administrator'
}
$root = ''
try {
    $temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ($temp -notmatch '^[A-Za-z]:\\' -or $temp.Contains('..')) {
        Refuse 'local canonical temporary root unavailable'
    }
    $tempEntry = Get-Item -LiteralPath $temp -Force -ErrorAction Stop
    if (-not $tempEntry.PSIsContainer -or
        (($tempEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Refuse 'redirected or missing temporary root'
    }
    $root = Join-Path $temp ('pds-suite49-acl-sandbox-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $root) { Refuse 'new sandbox name already exists' }

    # These are the only possible write targets. No arbitrary path is accepted.
    $paths = @(
        $root,
        (Join-Path $root 'app-binaries'),
        (Join-Path $root 'protected-state'),
        (Join-Path $root 'protected-state\active-receipts'),
        (Join-Path $root 'protected-state\service-state')
    )
    $admins = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    $system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $inherit = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path) { Refuse 'sandbox target already exists' }
        [void][IO.Directory]::CreateDirectory($path)
        # Preserve the OS-assigned owner; replace only the experimental DACL.
        $security = Get-Acl -LiteralPath $path -ErrorAction Stop
        $security.SetAccessRuleProtection($true, $false)
        $existing = @($security.GetAccessRules($true, $false,
            [Security.Principal.SecurityIdentifier]))
        foreach ($old in $existing) {
            [void]$security.RemoveAccessRuleSpecific($old)
        }
        foreach ($sid in @($admins, $system)) {
            $rule = [Security.AccessControl.FileSystemAccessRule]::new(
                $sid, [Security.AccessControl.FileSystemRights]::FullControl,
                $inherit, [Security.AccessControl.PropagationFlags]::None,
                [Security.AccessControl.AccessControlType]::Allow
            )
            $security.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $path -AclObject $security -ErrorAction Stop
        $found = Get-Acl -LiteralPath $path -ErrorAction Stop
        if (-not $found.AreAccessRulesProtected) {
            Refuse 'sandbox DACL unexpectedly inherits from parent'
        }
        $aces = @($found.GetAccessRules($true, $true,
            [Security.Principal.SecurityIdentifier]))
        if ($aces.Count -ne 2) { Refuse 'unexpected sandbox DACL ACE count' }
        $observed = @{}
        foreach ($ace in $aces) {
            $sid = $ace.IdentityReference.Value
            if ($sid -notin @($admins.Value, $system.Value) -or
                $ace.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
                $ace.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
                $ace.IsInherited -or $observed.ContainsKey($sid)) {
                Refuse 'sandbox DACL did not match the two principal experiment'
            }
            $observed[$sid] = $true
        }
        if ($observed.Count -ne 2) { Refuse 'required sandbox principals missing' }
    }
    $result = [ordered]@{
        status = 'DISPOSABLE_ACL_SANDBOX_CREATED_NOT_PRODUCTION'
        sandbox_root = $root
        protected_paths_checked = $paths.Count
        dacl_rules_verified = $true
        administrator_token_observed_unverified = $true
        independent_administrator_authenticated = $false
        ordinary_user_effective_denial_attested = $false
        parent_delete_rights_protected = $false
        production_provisioning_performed = $false
        service_registered = $false
        publisher_pin_provisioned = $false
        receipt_published = $false
        authorized_to_install = $false
        authority = $noAuthority
    }
    [Console]::Out.WriteLine(($result | ConvertTo-Json -Compress -Depth 3))
    [Console]::Out.WriteLine($noAuthority)
    exit 2
} catch {
    # Deliberately leave any partially created test sandbox for inspection;
    # do not roll back or remove unknown filesystem state automatically.
    Refuse 'sandbox test failed; inspect retained disposable test directory'
}
