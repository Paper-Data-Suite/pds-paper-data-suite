# Paper Data Suite

Paper Data Suite is a local-first collection of interoperable classroom tools
for paper-compatible evidence capture, review, scoring, grading/reporting,
collaboration, portfolio curation, and teacher-controlled support workflows.

This repository is the suite-level repository. Its first implementation
milestone is intended to establish the `paper-data-suite` shell and `pds`
command as a bounded orchestration layer over PDS Core and installed modules.

## Current status

The suite shell is in initial pre-release development.

At this point, this repository contains planning and identity documentation only.
It is **not yet an installable Python package**, does not yet expose a `pds`
command, and has no supported release.

The active v0.1.0 milestone will define the shell's exact ownership and
integration boundaries before runtime implementation proceeds.

## Architecture direction

The v0.1.0 plan requires the suite shell to remain orchestration-only.

PDS Core remains the authority for shared workspace and cross-module
infrastructure. Individual PDS modules remain authoritative for their own
canonical records, business rules, and teacher workflows. The shell must use
public Core services and supported module integration surfaces rather than
copying or directly mutating module-owned state.

The comprehensive architectural contract will be established by the first
v0.1.0 implementation issue.

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

## Planning documents

- [`docs/development-plan.md`](docs/development-plan.md) — suite-wide pilot-readiness and
  development program.
- [`docs/pds-viz-identity.md`](docs/pds-viz-identity.md) — shared Paper Data Suite visual
  identity notes.

## Data safety

Repository examples, fixtures, tests, screenshots, and issue reports must use
synthetic data. Do not commit real student records, rosters, student work,
scans, grades, behavior/support records, credentials, or private school or
district information.

See [`SECURITY.md`](SECURITY.md) for the repository's current security and
privacy reporting policy.
