# Paper Data Suite

Paper Data Suite is a local-first collection of interoperable classroom tools
for paper-compatible evidence capture, review, scoring, grading/reporting,
collaboration, portfolio curation, and teacher-controlled support workflows.

This repository contains the suite-level orchestration package. The installable
distribution is `paper-data-suite`, the import package is `paper_data_suite`,
and the primary command is `pds`.

## Current status

The suite shell is in pre-release development at `0.1.0.dev0`.

The package foundation is installable, but there is **no supported public
v0.1.0 release yet**. The current `pds` command intentionally exposes only
minimal help and version behavior. Operational suite commands are added by later
v0.1.0 issues.

The package metadata requires Python 3.11 or newer and
`pds-core>=0.6,<0.7`. Those broad package requirements do **not** by themselves
qualify every matching interpreter or component release for the suite.

The package now carries a versioned machine-readable compatibility declaration.
For the current development build, suite qualification is explicit and
fail-closed:

- suite-qualified Python: `>=3.11,<3.15`;
- tested Python minors: 3.11, 3.12, 3.13, and 3.14;
- required Core: `pds-core==0.6.0`;
- optional qualified applications:
  - `pds-concord==0.2.0`;
  - `quillan==0.9.0`;
  - `scoreform==0.10.0`;
  - `pds-vitrine==0.2.0`.

Each qualified component row binds to one exact official GitHub Release wheel
and SHA-256 digest. An installed version absent from the active declaration is
not silently treated as compatible. Meridian is not currently qualified by this
development manifest because its audited source identity remains a development
version, and Portia does not yet have an executable application release.

The normative manifest contract is
[`docs/architecture/release-compatibility-manifest.md`](docs/architecture/release-compatibility-manifest.md).

## Verified Windows bootstrap

The repository now includes a verified Windows bootstrap and exact-version
update-planning workflow at `scripts/bootstrap_windows.ps1`. Plan mode is the
default and does not mutate the requested target environment. Applying a plan
requires explicit `-Apply`; noninteractive application also requires `-Yes`.

The bootstrap does not discover a "latest" PDS release. It starts from one
local suite wheel plus an **external expected SHA-256** for that wheel. Only
after authenticating the suite wheel does it trust the bundled compatibility
manifest and authenticate the exact Core/module wheels declared there.

For example:

```powershell
$suiteHash = (
  Get-FileHash -Algorithm SHA256 -LiteralPath $suiteWheel
).Hash.ToLowerInvariant()

.\scripts\bootstrap_windows.ps1 `
  -SuiteWheel $suiteWheel `
  -SuiteWheelSha256 $suiteHash `
  -AllComponents
```

The default target is the version-qualified directory
`%LOCALAPPDATA%\Paper Data Suite\envs\<suite-version>`. Existing incompatible,
unmarked, editable/source-linked, or otherwise uncertain PDS environments are
blocked rather than silently upgraded or repaired. Bootstrap does not install
Python, Poppler, or other system software and does not read or create a classroom
workspace.

The normative operational contract, trust hierarchy, apply behavior, failure
semantics, and recovery boundaries are documented in
[`docs/operations/windows-bootstrap.md`](docs/operations/windows-bootstrap.md).

## Architecture direction

The suite shell is an orchestration and teacher-convenience layer, not a second
Core or an alternate owner of module records.

PDS Core remains the authority for shared workspace and cross-module
infrastructure. Individual PDS modules remain authoritative for their own
canonical records, business rules, and teacher workflows. The shell must use
public Core services and supported component boundaries rather than copying or
directly mutating owner state.

The normative ownership and integration contract is
[`docs/architecture/suite-shell-boundaries.md`](docs/architecture/suite-shell-boundaries.md).

## Development setup

Create and activate a Python 3.11-or-newer virtual environment. On Windows
PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install a compatible official PDS Core 0.6.x wheel into the environment first.
For the current suite development manifest, the exact qualified Core release is
0.6.0. Do not infer exact suite qualification from the broad package dependency
range alone.

After Core is installed:

```powershell
python -m pip install -e ".[dev]"
```

The current foundation commands are:

```powershell
pds
pds --help
pds --version

python -m paper_data_suite
python -m paper_data_suite --help
python -m paper_data_suite --version
```

These commands do not create or select a workspace, discover sibling
applications, or perform classroom-data workflows.

## Development validation

Run:

```powershell
python -m pytest
python -m ruff check .
python -m mypy
python -m pip check
python .\scripts\validate_compatibility_manifest.py

Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue
python -m build
python -m twine check .\dist\*
```

Then validate and smoke-test the built wheel using the exact Core 0.6.0 wheel:

```powershell
python .\scripts\check_package.py <suite-wheel>
python .\scripts\smoke_test_wheel.py <suite-wheel> <core-wheel>
```

To authenticate all exact component wheels declared by the manifest:

```powershell
python .\scripts\verify_compatibility_artifacts.py `
  --artifact-dir <directory-containing-declared-wheels>
```

The built-wheel smoke test creates an isolated environment and proves that the
bundled compatibility resource loads beside Core without requiring or importing
sibling PDS applications. The artifact verifier inspects release wheels directly;
it does not install or import them.

Do not place a real classroom PDS workspace inside this repository.

## Documentation

- [`docs/architecture/suite-shell-boundaries.md`](docs/architecture/suite-shell-boundaries.md)
  — normative suite-shell ownership and integration contract.
- [`docs/architecture/release-compatibility-manifest.md`](docs/architecture/release-compatibility-manifest.md)
  — normative machine-readable suite release-qualification contract.
- [`docs/operations/windows-bootstrap.md`](docs/operations/windows-bootstrap.md)
  — normative verified Windows bootstrap and exact update-planning workflow.
- [`docs/development-plan.md`](docs/development-plan.md) — suite-wide
  pilot-readiness and development program.
- [`docs/pds-viz-identity.md`](docs/pds-viz-identity.md) — shared Paper Data
  Suite visual identity notes.

## Data safety

Repository examples, fixtures, tests, screenshots, and issue reports must use
synthetic data. Do not commit real student records, rosters, student work,
scans, grades, behavior/support records, credentials, or private school or
district information.

See [`SECURITY.md`](SECURITY.md) for the repository's current security and
privacy reporting policy.
