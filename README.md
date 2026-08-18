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

The package requires Python 3.11 or newer and a compatible PDS Core 0.6.x
installation.

## Architecture direction

The suite shell is an orchestration and teacher-convenience layer, not a second
Core or an alternate owner of module records.

PDS Core remains the authority for shared workspace and cross-module
infrastructure. Individual PDS modules remain authoritative for their own
canonical records, business rules, and teacher workflows. The shell must use
public Core services and supported component boundaries rather than copying or
directly mutating owner state.

The normative contract is
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
The exact suite release matrix and verified bootstrap workflow are defined by
later v0.1.0 issues; do not infer exact suite qualification from the broad
package dependency range alone.

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

Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue
python -m build
python -m twine check .\dist\*
```

Then validate and smoke-test the built wheel using a compatible Core wheel:

```powershell
python .\scripts\check_package.py <suite-wheel>
python .\scripts\smoke_test_wheel.py <suite-wheel> <core-wheel>
```

The wheel smoke test creates an isolated environment and proves that the suite
foundation works beside Core without requiring sibling PDS applications.

Do not place a real classroom PDS workspace inside this repository.

## Documentation

- [`docs/architecture/suite-shell-boundaries.md`](docs/architecture/suite-shell-boundaries.md)
  — normative suite-shell ownership and integration contract.
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
