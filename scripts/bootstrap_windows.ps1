param(
    [Parameter(Mandatory)] [string]$SuiteWheel,
    [Parameter(Mandatory)] [string]$SuiteWheelSha256,
    [string]$PythonExe = "python",
    [string]$EnvironmentPath,
    [string[]]$Components = @(),
    [switch]$AllComponents,
    [string]$ArtifactDirectory,
    [switch]$Apply,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Prefix = "pds-suite-bootstrap-"
$OriginalLocation = (Get-Location).Path
$ScriptRoot = $PSScriptRoot
$RepositoryRoot = Split-Path $ScriptRoot -Parent
$TemporaryRoot = $null
$FinalExitCode = 0
$CurrentPhase = "planning"
$CreatedTargetEnvironment = $false
$InstallationSucceeded = $false
$TargetEnvironment = $null
$TargetOwnershipNonce = $null
$TargetOwnershipSentinel = $null

function Write-BootstrapError {
    param([string]$Message)
    [Console]::Error.WriteLine($Message)
}

function Invoke-Required {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments
    )
    Write-Host "=== $Label ==="
    $SavedPythonPath = $env:PYTHONPATH
    try {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        & $FilePath @Arguments
        $ExitCode = $LASTEXITCODE
    }
    finally {
        if ($null -eq $SavedPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $SavedPythonPath
        }
    }
    if ($ExitCode -ne 0) {
        throw "$Label failed with exit code $ExitCode"
    }
}

function Invoke-Captured {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    $SavedPythonPath = $env:PYTHONPATH
    try {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        $Output = & $FilePath @Arguments
        $ExitCode = $LASTEXITCODE
    }
    finally {
        if ($null -eq $SavedPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $SavedPythonPath
        }
    }
    return @{
        ExitCode = $ExitCode
        Output = @($Output)
    }
}

function Test-PathContainedBy {
    param(
        [string]$Candidate,
        [string]$Root
    )
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    if ([string]::IsNullOrWhiteSpace($Root)) { return $false }
    $CandidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $RootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ($CandidateFull.Equals(
        $RootFull,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        return $true
    }
    return $CandidateFull.StartsWith(
        $RootFull + '\',
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-SafeTargetEnvironmentPath {
    param([string]$Path)

    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $Drive = [IO.Path]::GetPathRoot($Resolved).TrimEnd('\')
    $HomePath = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath('UserProfile')
    ).TrimEnd('\')
    $LocalAppData = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath('LocalApplicationData')
    ).TrimEnd('\')
    $AppData = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath('ApplicationData')
    ).TrimEnd('\')
    $Windows = $env:WINDIR
    $ProgramFiles = [Environment]::GetFolderPath('ProgramFiles')
    $ProgramFilesX86 = [Environment]::GetFolderPath('ProgramFilesX86')

    $ExactForbidden = @(
        $Drive,
        $HomePath,
        $LocalAppData,
        $AppData,
        $OriginalLocation.TrimEnd('\'),
        $ScriptRoot.TrimEnd('\'),
        $RepositoryRoot.TrimEnd('\')
    )
    if ($ExactForbidden -contains $Resolved) {
        throw "Refusing protected target environment path: $Resolved"
    }

    if (Test-Path -LiteralPath $Resolved) {
        $ExistingTarget = Get-Item -LiteralPath $Resolved -Force
        if (
            ($ExistingTarget.Attributes -band [IO.FileAttributes]::ReparsePoint) `
                -ne 0
        ) {
            throw "Refusing reparse-point target environment path: $Resolved"
        }
    }

    foreach ($SystemRoot in @($Windows, $ProgramFiles, $ProgramFilesX86)) {
        if (-not [string]::IsNullOrWhiteSpace($SystemRoot)) {
            if (Test-PathContainedBy $Resolved $SystemRoot) {
                throw "Refusing system target environment path: $Resolved"
            }
        }
    }

    if (
        (Test-PathContainedBy $Resolved $RepositoryRoot) -or
        (Test-PathContainedBy $RepositoryRoot $Resolved)
    ) {
        throw "Refusing repository-overlapping target environment path: $Resolved"
    }
}

function Initialize-OwnedTargetRoot {
    if ([string]::IsNullOrWhiteSpace($TargetEnvironment)) {
        throw "Target environment path is unavailable."
    }
    if (Test-Path -LiteralPath $TargetEnvironment) {
        throw "Target already exists: $TargetEnvironment"
    }

    New-Item -ItemType Directory -Path $TargetEnvironment | Out-Null
    $script:CreatedTargetEnvironment = $true
    $script:TargetOwnershipNonce = [guid]::NewGuid().ToString('N')
    $script:TargetOwnershipSentinel = Join-Path `
        $TargetEnvironment `
        '.pds-bootstrap-owned.tmp'
    [IO.File]::WriteAllText(
        $TargetOwnershipSentinel,
        $TargetOwnershipNonce,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Remove-ValidatedTemporaryRoot {
    if ($null -eq $TemporaryRoot) { return }
    if (-not (Test-Path -LiteralPath $TemporaryRoot)) { return }

    $Resolved = (Resolve-Path -LiteralPath $TemporaryRoot).Path.TrimEnd('\')
    $Temp = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    ).TrimEnd('\')
    $HomePath = [System.IO.Path]::GetFullPath(
        [Environment]::GetFolderPath('UserProfile')
    ).TrimEnd('\')
    $Drive = [System.IO.Path]::GetPathRoot($Resolved).TrimEnd('\')
    $Forbidden = @(
        $OriginalLocation.TrimEnd('\'),
        $ScriptRoot.TrimEnd('\'),
        $HomePath,
        $Drive
    )

    if (-not $Resolved.StartsWith(
        $Temp + '\',
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing cleanup outside OS temp: $Resolved"
    }
    if (-not (Split-Path $Resolved -Leaf).StartsWith($Prefix)) {
        throw "Refusing cleanup with unexpected prefix: $Resolved"
    }
    if ($Forbidden -contains $Resolved) {
        throw "Refusing protected cleanup: $Resolved"
    }
    $Item = Get-Item -LiteralPath $Resolved -Force
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse-point cleanup root: $Resolved"
    }
    Remove-Item -LiteralPath $Resolved -Recurse -Force
}

function Remove-ValidatedCreatedTargetEnvironment {
    if (-not $CreatedTargetEnvironment) { return }
    if ([string]::IsNullOrWhiteSpace($TargetEnvironment)) { return }
    if (-not (Test-Path -LiteralPath $TargetEnvironment)) { return }

    $Resolved = (Resolve-Path -LiteralPath $TargetEnvironment).Path.TrimEnd('\')
    Assert-SafeTargetEnvironmentPath $Resolved

    $Item = Get-Item -LiteralPath $Resolved -Force
    if (-not $Item.PSIsContainer) {
        throw "Refusing cleanup of non-directory target: $Resolved"
    }
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse-point target cleanup root: $Resolved"
    }
    if (
        [string]::IsNullOrWhiteSpace($TargetOwnershipNonce) -or
        [string]::IsNullOrWhiteSpace($TargetOwnershipSentinel)
    ) {
        throw "Refusing target cleanup without ownership proof: $Resolved"
    }
    if (-not (
        Test-Path -LiteralPath $TargetOwnershipSentinel -PathType Leaf
    )) {
        throw "Refusing target cleanup without ownership sentinel: $Resolved"
    }
    $SentinelItem = Get-Item -LiteralPath $TargetOwnershipSentinel -Force
    if (($SentinelItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing linked ownership sentinel: $TargetOwnershipSentinel"
    }
    $ObservedNonce = [IO.File]::ReadAllText($TargetOwnershipSentinel).Trim()
    if ($ObservedNonce -ne $TargetOwnershipNonce) {
        throw "Refusing target cleanup with invalid ownership sentinel: $Resolved"
    }

    Remove-Item -LiteralPath $Resolved -Recurse -Force
    Write-Host "Removed incomplete newly created environment: $Resolved"
}

if ($AllComponents -and $Components.Count -gt 0) {
    Write-BootstrapError "Use either -AllComponents or -Components, not both."
    exit 2
}
if ($Yes -and -not $Apply) {
    Write-BootstrapError "-Yes is valid only together with -Apply."
    exit 2
}

if ($SuiteWheelSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
    Write-BootstrapError (
        "SuiteWheelSha256 must be exactly 64 hexadecimal characters."
    )
    exit 2
}

if (-not (Test-Path -LiteralPath $SuiteWheel -PathType Leaf)) {
    Write-BootstrapError "Suite wheel does not exist: $SuiteWheel"
    exit 4
}
$ResolvedSuiteWheel = (Resolve-Path -LiteralPath $SuiteWheel).Path
if ([IO.Path]::GetExtension($ResolvedSuiteWheel) -ne '.whl') {
    Write-BootstrapError "SuiteWheel must be a .whl file."
    exit 4
}

$ExpectedSuiteSha256 = $SuiteWheelSha256.ToLowerInvariant()
$ActualSuiteSha256 = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $ResolvedSuiteWheel
).Hash.ToLowerInvariant()
if ($ActualSuiteSha256 -ne $ExpectedSuiteSha256) {
    Write-BootstrapError (
        "Suite wheel SHA-256 mismatch: expected $ExpectedSuiteSha256, " +
        "got $ActualSuiteSha256. No suite code was executed."
    )
    exit 4
}
Write-Host "Suite wheel SHA-256: PASS"

try {
    $ResolvedPython = (Get-Command $PythonExe -ErrorAction Stop).Source
    $SeedPythonVersion = & $ResolvedPython -I -c (
        'import platform; print(platform.python_version())'
    )
    if ($LASTEXITCODE -ne 0 -or -not $SeedPythonVersion) {
        throw "Could not determine seed Python version."
    }
    $SeedPythonVersion = $SeedPythonVersion.Trim()

    $TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
        "$Prefix$([guid]::NewGuid().ToString('N'))"
    )
    New-Item -ItemType Directory -Path $TemporaryRoot | Out-Null

    $InspectionEnvironment = Join-Path $TemporaryRoot "inspection"
    Invoke-Required "Create temporary inspection environment" $ResolvedPython @(
        '-m', 'venv', $InspectionEnvironment
    )
    $InspectionPython = Join-Path $InspectionEnvironment 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $InspectionPython -PathType Leaf)) {
        throw "Inspection environment did not create Scripts\python.exe."
    }

    Invoke-Required "Install authenticated suite for inspection" $InspectionPython @(
        '-m', 'pip', 'install',
        '--disable-pip-version-check',
        '--no-deps',
        '--no-index',
        $ResolvedSuiteWheel
    )

    $ManifestResult = Invoke-Captured $InspectionPython @(
        '-I', '-m', 'paper_data_suite.bootstrap_cli',
        'manifest-summary', '--json'
    )
    if ($ManifestResult.ExitCode -ne 0) {
        throw "Authenticated suite manifest inspection failed."
    }
    $ManifestSummary = (
        $ManifestResult.Output -join [Environment]::NewLine
    ) | ConvertFrom-Json

    if ([string]::IsNullOrWhiteSpace($EnvironmentPath)) {
        $LocalAppData = [Environment]::GetFolderPath('LocalApplicationData')
        if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
            throw "Windows LocalApplicationData could not be resolved."
        }
        $EnvironmentPath = Join-Path $LocalAppData (
            "Paper Data Suite\envs\$($ManifestSummary.suite_version)"
        )
    }
    $TargetEnvironment = [IO.Path]::GetFullPath($EnvironmentPath)
    $CurrentPhase = "target-validation"
    Assert-SafeTargetEnvironmentPath $TargetEnvironment
    $CurrentPhase = "planning"

    $SelectedComponents = @($Components)
    if ($AllComponents) {
        $SelectedComponents = @($ManifestSummary.optional_component_ids)
    }

    $CommonPlanArguments = @(
        '--environment-path', $TargetEnvironment,
        '--seed-python-version', $SeedPythonVersion
    )
    foreach ($Component in $SelectedComponents) {
        $CommonPlanArguments += @('--component', $Component)
    }

    $PlanArguments = @(
        '-I', '-m', 'paper_data_suite.bootstrap_cli', 'plan'
    ) + $CommonPlanArguments
    $SavedPythonPath = $env:PYTHONPATH
    try {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        & $InspectionPython @PlanArguments
        $PlanExitCode = $LASTEXITCODE
    }
    finally {
        if ($null -eq $SavedPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $SavedPythonPath
        }
    }

    if ($PlanExitCode -eq 3) {
        $FinalExitCode = 3
    }
    elseif ($PlanExitCode -eq 2) {
        $FinalExitCode = 2
    }
    elseif ($PlanExitCode -ne 0) {
        throw "Bootstrap planning failed with exit code $PlanExitCode."
    }

    $PlanSummary = $null
    if ($FinalExitCode -eq 0) {
        $PlanJsonArguments = $PlanArguments + @('--json')
        $PlanJsonResult = Invoke-Captured `
            $InspectionPython `
            $PlanJsonArguments
        if ($PlanJsonResult.ExitCode -ne 0) {
            throw "Machine-readable bootstrap planning failed."
        }
        $PlanSummary = (
            $PlanJsonResult.Output -join [Environment]::NewLine
        ) | ConvertFrom-Json
    }

    if ($FinalExitCode -eq 0) {
        $CurrentPhase = "artifact"

        $RequirementArguments = @(
            '-I', '-m', 'paper_data_suite.bootstrap_cli',
            'artifact-requirements'
        ) + $CommonPlanArguments + @('--json')
        $RequirementResult = Invoke-Captured `
            $InspectionPython `
            $RequirementArguments
        if ($RequirementResult.ExitCode -ne 0) {
            $RequirementDetails = (
                $RequirementResult.Output -join [Environment]::NewLine
            )
            throw (
                "Artifact requirement planning failed with exit code " +
                "$($RequirementResult.ExitCode): $RequirementDetails"
            )
        }
        $RequirementSummary = (
            $RequirementResult.Output -join [Environment]::NewLine
        ) | ConvertFrom-Json

        $UsingCallerArtifactDirectory = -not (
            [string]::IsNullOrWhiteSpace($ArtifactDirectory)
        )
        if ($UsingCallerArtifactDirectory) {
            if (-not (
                Test-Path -LiteralPath $ArtifactDirectory -PathType Container
            )) {
                throw "Artifact directory does not exist: $ArtifactDirectory"
            }
            $ArtifactRoot = (
                Resolve-Path -LiteralPath $ArtifactDirectory
            ).Path
            Write-Host "Artifact source: caller-supplied read-only directory"
        }
        else {
            $ArtifactRoot = Join-Path $TemporaryRoot "artifacts"
            New-Item -ItemType Directory -Path $ArtifactRoot | Out-Null
            Write-Host "Artifact source: guarded temporary downloads"
        }

        foreach ($Requirement in @($RequirementSummary.required_artifacts)) {
            $ArtifactPath = Join-Path $ArtifactRoot $Requirement.wheel
            if ($UsingCallerArtifactDirectory) {
                Write-Host (
                    "Reuse exact local artifact: " +
                    "$($Requirement.component_id) -> $ArtifactPath"
                )
                if (-not (
                    Test-Path -LiteralPath $ArtifactPath -PathType Leaf
                )) {
                    throw (
                        "Required local artifact is missing: " +
                        "$ArtifactPath"
                    )
                }
            }
            else {
                Write-Host (
                    "Download exact declared artifact: " +
                    "$($Requirement.component_id) -> $($Requirement.url)"
                )
                Invoke-WebRequest `
                    -UseBasicParsing `
                    -Uri $Requirement.url `
                    -OutFile $ArtifactPath `
                    -ErrorAction Stop
                if (-not (
                    Test-Path -LiteralPath $ArtifactPath -PathType Leaf
                )) {
                    throw "Artifact download did not create $ArtifactPath."
                }
            }
        }

        $ConstraintsPath = Join-Path $TemporaryRoot "pds-constraints.txt"
        $VerificationArguments = @(
            '-I', '-m', 'paper_data_suite.bootstrap_cli',
            'verify-artifacts'
        ) + $CommonPlanArguments + @(
            '--artifact-dir', $ArtifactRoot,
            '--constraints-path', $ConstraintsPath,
            '--json'
        )
        $VerificationResult = Invoke-Captured `
            $InspectionPython `
            $VerificationArguments
        if ($VerificationResult.ExitCode -ne 0) {
            $VerificationDetails = (
                $VerificationResult.Output -join [Environment]::NewLine
            )
            throw (
                "Artifact authentication failed with exit code " +
                "$($VerificationResult.ExitCode): $VerificationDetails"
            )
        }
        $VerificationSummary = (
            $VerificationResult.Output -join [Environment]::NewLine
        ) | ConvertFrom-Json

        Write-Host ""
        Write-Host "Authenticated component artifacts:"
        $VerifiedArtifacts = @($VerificationSummary.verified_artifacts)
        if ($VerifiedArtifacts.Count -eq 0) {
            Write-Host "  none required by this plan"
        }
        else {
            foreach ($Artifact in $VerifiedArtifacts) {
                Write-Host (
                    "  $($Artifact.distribution) $($Artifact.version): PASS"
                )
            }
        }

        Write-Host ""
        Write-Host "Transient PDS constraints:"
        foreach ($Constraint in @($VerificationSummary.constraints)) {
            Write-Host "  $Constraint"
        }
        Write-Host ""
        Write-Host (
            "Component artifact preparation completed without " +
            "target-environment mutation."
        )

        if ($Apply) {
            $ApplyApproved = $Yes
            if (-not $Yes) {
                $Confirmation = Read-Host (
                    "Apply this exact plan to $TargetEnvironment? [y/N]"
                )
                $ApplyApproved = (
                    $Confirmation -in @('y', 'Y', 'yes', 'YES', 'Yes')
                )
            }

            if (-not $ApplyApproved) {
                Write-Host "Apply cancelled. No target changes were made."
            }
            else {
                $CurrentPhase = "installation"
                Write-Host ""
                Write-Host "=== Apply verified bootstrap plan ==="

            $EnvironmentAction = [string]$PlanSummary.environment.action
            if ($EnvironmentAction -eq 'create_environment') {
                if (Test-Path -LiteralPath $TargetEnvironment) {
                    throw (
                        "Target appeared after planning; refusing to create or " +
                        "adopt it: $TargetEnvironment"
                    )
                }
                Initialize-OwnedTargetRoot
                Invoke-Required "Create target environment" $ResolvedPython @(
                    '-m', 'venv', $TargetEnvironment
                )
            }
            elseif ($EnvironmentAction -ne 'keep_environment') {
                throw "Plan cannot be applied: environment action is $EnvironmentAction"
            }

            $TargetPython = Join-Path $TargetEnvironment 'Scripts\python.exe'
            if (-not (Test-Path -LiteralPath $TargetPython -PathType Leaf)) {
                throw "Target environment is missing Scripts\python.exe."
            }

            $ArtifactsByComponent = @{}
            foreach ($Artifact in $VerifiedArtifacts) {
                $ArtifactsByComponent[$Artifact.component_id] = $Artifact.path
            }

            $PackagePlans = @($PlanSummary.packages)
            $CorePlan = $PackagePlans | Where-Object {
                $_.component_id -eq 'core'
            }
            $SuitePlan = $PackagePlans | Where-Object {
                $_.component_id -eq 'suite'
            }

            if ($CorePlan.action -eq 'install_missing') {
                $CoreWheel = $ArtifactsByComponent['core']
                if ([string]::IsNullOrWhiteSpace($CoreWheel)) {
                    throw "Authenticated Core artifact is unavailable."
                }
                Invoke-Required "Install exact authenticated Core" $TargetPython @(
                    '-m', 'pip', 'install',
                    '--disable-pip-version-check',
                    '--no-deps',
                    '--no-index',
                    '--constraint', $ConstraintsPath,
                    $CoreWheel
                )
            }

            if ($SuitePlan.action -eq 'install_missing') {
                Invoke-Required "Install exact authenticated suite" $TargetPython @(
                    '-m', 'pip', 'install',
                    '--disable-pip-version-check',
                    '--no-deps',
                    '--no-index',
                    '--constraint', $ConstraintsPath,
                    $ResolvedSuiteWheel
                )
            }

            foreach ($PackagePlan in $PackagePlans) {
                if (
                    $PackagePlan.component_id -in @('core', 'suite') -or
                    $PackagePlan.action -ne 'install_missing'
                ) {
                    continue
                }
                $ComponentWheel = $ArtifactsByComponent[$PackagePlan.component_id]
                if ([string]::IsNullOrWhiteSpace($ComponentWheel)) {
                    throw (
                        "Authenticated artifact is unavailable for " +
                        "$($PackagePlan.component_id)."
                    )
                }
                Invoke-Required (
                    "Install exact authenticated $($PackagePlan.display_name)"
                ) $TargetPython @(
                    '-m', 'pip', 'install',
                    '--disable-pip-version-check',
                    '--constraint', $ConstraintsPath,
                    $ComponentWheel
                )
            }

            Invoke-Required "pip check" $TargetPython @(
                '-m', 'pip', 'check'
            )

            $FinalizeArguments = @(
                '-I', '-m', 'paper_data_suite.bootstrap_cli',
                'finalize-environment'
            ) + $CommonPlanArguments + @('--json')
            $FinalizeResult = Invoke-Captured `
                $InspectionPython `
                $FinalizeArguments
            if ($FinalizeResult.ExitCode -ne 0) {
                $FinalizeDetails = (
                    $FinalizeResult.Output -join [Environment]::NewLine
                )
                throw (
                    "Installed composition verification/finalization failed: " +
                    $FinalizeDetails
                )
            }
            $FinalizeSummary = (
                $FinalizeResult.Output -join [Environment]::NewLine
            ) | ConvertFrom-Json

            if ($CreatedTargetEnvironment) {
                if (-not (
                    Test-Path -LiteralPath $TargetOwnershipSentinel -PathType Leaf
                )) {
                    throw "Target ownership sentinel disappeared before completion."
                }
                $ObservedNonce = [IO.File]::ReadAllText(
                    $TargetOwnershipSentinel
                ).Trim()
                if ($ObservedNonce -ne $TargetOwnershipNonce) {
                    throw "Target ownership sentinel changed before completion."
                }
                Remove-Item -LiteralPath $TargetOwnershipSentinel -Force
                $TargetOwnershipSentinel = $null
                $TargetOwnershipNonce = $null
            }
            $InstallationSucceeded = $true
            Write-Host ""
            Write-Host "Installed PDS composition:"
            foreach ($Package in @($FinalizeSummary.verified_packages)) {
                Write-Host "  $($Package.distribution) $($Package.version)"
            }
            Write-Host "pip check: PASS"
            Write-Host "Environment marker: $($FinalizeSummary.marker_path)"
            Write-Host "Bootstrap completed successfully."
            Write-Host "Environment: $TargetEnvironment"
            $ActivationScript = Join-Path `
                $TargetEnvironment `
                'Scripts\Activate.ps1'
            Write-Host "Activate: & `"$ActivationScript`""
            Write-Host (
                "Launch: " +
                (Join-Path $TargetEnvironment 'Scripts\pds.exe')
            )
            }
        }
    }
}
catch {
    Write-BootstrapError "Bootstrap failed: $($_.Exception.Message)"
    if ($CurrentPhase -eq "artifact") {
        $FinalExitCode = 4
    }
    elseif ($CurrentPhase -eq "target-validation") {
        $FinalExitCode = 3
    }
    else {
        $FinalExitCode = 5
    }
}
finally {
    if ($CreatedTargetEnvironment -and -not $InstallationSucceeded) {
        try {
            Remove-ValidatedCreatedTargetEnvironment
        }
        catch {
            Write-BootstrapError (
                "Incomplete target cleanup failed: $($_.Exception.Message)"
            )
            $FinalExitCode = 5
        }
    }
    try {
        Remove-ValidatedTemporaryRoot
    }
    catch {
        Write-BootstrapError "Bootstrap cleanup failed: $($_.Exception.Message)"
        if ($FinalExitCode -eq 0) { $FinalExitCode = 5 }
    }
}

exit $FinalExitCode
