# Suite #19E3A: explicit offline-first Windows disposable installed acceptance.
# No teacher workspace, user scanner folder, or producer command is inspected.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Wheelhouse,
    [switch]$AllowPyPI,
    [switch]$IncludeTeacherHome
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed. No classroom dispatch admission is granted."
    }
}

function Assert-NoReparse([string]$path) {
    $item = Get-Item -LiteralPath $path -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Linked/reparse acceptance paths are unsupported.'
    }
}

$checkout = (Get-Location).Path
if ((Split-Path $checkout -Leaf) -cne 'pds-paper-data-suite') {
    throw 'Run from the pds-paper-data-suite checkout.'
}
$developerPython = Join-Path $checkout '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $developerPython -PathType Leaf)) {
    throw 'The checkout Python virtual environment is unavailable.'
}
$wheelhousePath = [IO.Path]::GetFullPath($Wheelhouse)
if (-not [IO.Path]::IsPathRooted($Wheelhouse) -or
    -not (Test-Path -LiteralPath $wheelhousePath -PathType Container)) {
    throw 'An explicit existing absolute official-wheel directory is required.'
}
Assert-NoReparse $wheelhousePath
# Native rehearsal and the established A3 runtime gate require exactly 3.11.
# Use the Windows Python launcher instead of assuming checkout .venv is 3.11.
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($null -eq $pyLauncher) {
    throw 'Windows Python launcher is missing; install Python 3.11 explicitly.'
}
$pyVersion = (& py -3.11 --version 2>&1 | Out-String).Trim()
Assert-Exit 'Select Windows Python 3.11'
if (-not $pyVersion.StartsWith('Python 3.11.')) {
    throw 'The selected isolated interpreter must be Python 3.11.'
}
$branch = (& git branch --show-current).Trim()
Assert-Exit 'Read branch'
if ($branch -cne '19-teacher-home-returned-paper-workflow') {
    throw 'This acceptance is scoped to the reviewed issue #19 branch.'
}
$status = @(& git status --porcelain=v1 --untracked-files=all)
Assert-Exit 'Read working-tree status'
if ($status.Count -ne 0) {
    throw 'Acceptance requires clean committed source, not a dirty checkout.'
}
$parent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
Assert-NoReparse $parent
$session = Join-Path $parent ('suite19_e3a_synthetic_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $session -ErrorAction Stop | Out-Null
$snapshot = Join-Path $session 'committed-source'
$built = Join-Path $session 'built-suite'
$venv = Join-Path $session 'isolated-installed-venv'
$archive = Join-Path $session 'source.zip'
New-Item -ItemType Directory -Path $snapshot | Out-Null
New-Item -ItemType Directory -Path $built | Out-Null

# Git archive excludes ignored user files and build debris. This acceptance
# never builds, installs or runs producer handlers in the source checkout.
& git archive --format=zip HEAD -o $archive
Assert-Exit 'Archive the exact committed candidate'
Expand-Archive -LiteralPath $archive -DestinationPath $snapshot
$wheelProbe = Join-Path $snapshot 'scripts\issue18_qualify_official_wheels.py'
$nativeRehearsal = Join-Path $snapshot 'scripts\issue18_native_mixed_pdf_rehearsal.py'
$fixture = Join-Path $snapshot 'tests\fixtures\issue19_two_page_synthetic_pds2.pdf'
foreach ($path in @($wheelProbe, $nativeRehearsal, $fixture)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Required committed acceptance contract or fixture is missing.'
    }
}

# Run the existing #18 published-release SHA-256 and metadata audit before
# installing a single byte into the new disposable virtual environment.
Push-Location $snapshot
try {
    & $developerPython -m scripts.issue18_qualify_official_wheels --wheelhouse $wheelhousePath
    Assert-Exit 'Authentic official-wheel subset'
    Write-Host 'SUITE19_E3A_OFFICIAL_WHEELS_VERIFIED'
    & $developerPython -m build --wheel --no-isolation --outdir $built
    Assert-Exit 'Build Suite wheel from committed source snapshot'
} finally {
    Pop-Location
}
$suiteWheels = @(Get-ChildItem -LiteralPath $built -Filter 'paper_data_suite-*.whl' -File)
if ($suiteWheels.Count -ne 1 -or
    $suiteWheels[0].Name -cne 'paper_data_suite-0.1.0-py3-none-any.whl') {
    throw 'The built Suite wheel is not the exact expected package.'
}
$names = @(
    'pds_core-0.6.6-py3-none-any.whl',
    'scoreform-0.13.0-py3-none-any.whl',
    'quillan-0.10.6-py3-none-any.whl'
)
$published = @()
foreach ($name in $names) {
    $path = Join-Path $wheelhousePath $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'One pinned official wheel is missing.'
    }
    Assert-NoReparse $path
    $published += $path
}
& py -3.11 -m venv $venv
Assert-Exit 'Create disposable installed Python environment'
$installedPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $installedPython -PathType Leaf)) {
    throw 'Disposable Python was not created.'
}
$install = @('install', '--disable-pip-version-check')
if (-not $AllowPyPI.IsPresent) {
    $install += @('--no-index', '--find-links', $wheelhousePath)
}
$install += $published
$install += $suiteWheels[0].FullName
$install += @('pypdfium2>=5.13,<6', 'zxing-cpp>=2.3,<3', 'Pillow>=11,<13')
Write-Host ('DEPENDENCY_MODE=' + $(if ($AllowPyPI.IsPresent) { 'explicit PyPI permitted' } else { 'offline wheels only' }))
& $installedPython -m pip @install
Assert-Exit 'Install pinned candidates and bounded native dependencies'
& $installedPython -m pip check
Assert-Exit 'Installed dependency consistency'

# No python -c: Windows PowerShell command-line quoting of embedded Python
# source can strip double quotes. Use an explicit no-BOM UTF-8 file instead.
$checkPy = Join-Path $session 'check_installed.py'
$source = @'
import importlib
import importlib.metadata as md
import pathlib
import sys

expected = {
    "paper-data-suite": ("0.1.0", "paper_data_suite"),
    "pds-core": ("0.6.6", "pds_core"),
    "scoreform": ("0.13.0", "scoreform"),
    "quillan": ("0.10.6", "quillan"),
}
root = pathlib.Path(sys.prefix).resolve(strict=True)
assert root != pathlib.Path(sys.base_prefix).resolve(strict=True)
assert (sys.platform, sys.version_info[:2]) == ("win32", (3, 11))
for dist, (version, module) in expected.items():
    assert md.version(dist) == version
    imported = importlib.import_module(module)
    location = pathlib.Path(imported.__file__).resolve(strict=True)
    assert location.is_relative_to(root)
print("SUITE19_E3A_INSTALLED_VENV_VERIFIED")
'@
[IO.File]::WriteAllText($checkPy, $source, ([System.Text.UTF8Encoding]::new($false)))
# Do not allow checkout/caller PYTHONPATH to shadow the isolated wheel install.
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $null
try {
    Push-Location $session
    try {
        & $installedPython $checkPy
        Assert-Exit 'Exact installed Suite/Core/producer imports'
        & $installedPython $wheelProbe --wheelhouse $wheelhousePath --installed
        Assert-Exit 'Actual Core producer profiles'
        & $installedPython -m paper_data_suite.returned_paper_synthetic_acceptance `
            --fixture $fixture --wheelhouse $wheelhousePath
        Assert-Exit 'E2 native PDF and E1 complete diagnostic'
        Write-Host 'SUITE19_E3A_NATIVE_FIXTURE_AND_READINESS_VERIFIED'
        foreach ($script in @(
            'issue18_real_producer_rehearsal.py',
            'issue18_positive_scoreform_rehearsal.py',
            'issue18_native_mixed_pdf_rehearsal.py'
        )) {
            $syntheticRoot = Join-Path $session (
                'case_' + [guid]::NewGuid().ToString('N')
            )
            $workspace = Join-Path $syntheticRoot 'suite18_synthetic_workspace'
            New-Item -ItemType Directory -Path $workspace -Force | Out-Null
            $scriptPath = Join-Path $snapshot ('scripts\' + $script)
            & $installedPython $scriptPath --synthetic-workspace $workspace
            Assert-Exit ('Real synthetic installed acceptance: ' + $script)
        }
        Write-Host 'SUITE19_E3A_REAL_PRODUCER_HANDLERS_VERIFIED'
        if ($IncludeTeacherHome.IsPresent) {
            $homeScript = Join-Path $snapshot `
                'scripts\issue19_g1_installed_teacher_home_rehearsal.py'
            if (-not (Test-Path -LiteralPath $homeScript -PathType Leaf)) {
                throw 'Committed G1 installed Home rehearsal is unavailable.'
            }
            & $installedPython $homeScript `
                --synthetic-parent $session --wheelhouse $wheelhousePath
            Assert-Exit 'G1 actual installed Teacher Home native journey'
            Write-Host 'SUITE19_G1_ACTUAL_INSTALLED_HOME_VERIFIED'
        }
    } finally {
        Pop-Location
    }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
Write-Host 'SUITE19_E3A_SYNTHETIC_INSTALLED_ACCEPTANCE_PASSED'
Write-Host 'SUITE19_E3A_DISPATCH_REMAINS_DEFAULT_DENY'
if ($IncludeTeacherHome.IsPresent) {
    Write-Host ('Only disposable synthetic records were used; ' + `
        'G1 exercised installed Teacher Home.')
} else {
    Write-Host ('Only disposable synthetic records were used; ' + `
        'teacher UI not exercised.')
}
Write-Host 'The separate #19E/19G live policy and Teacher Home gate remain pending.'
