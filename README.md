# Paper Data Suite

Paper Data Suite is a local-first collection of interoperable classroom tools
for paper-compatible evidence capture, review, scoring, grading/reporting,
collaboration, portfolio curation, and teacher-controlled support workflows.

This repository is the suite-level repository. Its first implementation
milestone is intended to establish the `paper-data-suite` shell and `pds`
command as a bounded orchestration layer over PDS Core and installed modules.

## Current status

The suite shell is in initial pre-release development.

At this point, this repository contains planning and architecture documentation
only. It is **not yet an installable Python package**, does not yet expose a
`pds` command, and has no supported release.

The active v0.1.0 milestone will build the first runtime implementation within
the ownership and integration boundaries established for the suite shell.

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

## Development bootstrap

The initial development checkout uses Python 3.11 as the conservative baseline
shared by the current PDS module releases. The installable package and its
formal Python compatibility metadata will be established separately by the
package-foundation issue.

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

There is intentionally no `pip install -e .` step yet because this repository
does not contain package metadata.

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
