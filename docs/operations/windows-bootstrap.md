# Verified Windows bootstrap and update planning

This document defines the supported Windows bootstrap workflow for the Paper
Data Suite shell during the `0.1.0.dev0` development line. It is an operational
security contract, not a general-purpose Python package installer or updater.

The bootstrap composes one explicit suite release from one authenticated
`paper-data-suite` wheel and the exact PDS component releases declared by that
wheel's bundled compatibility manifest. It fails closed when identity,
compatibility, target ownership, or installed state is uncertain.

## Trust hierarchy

The suite wheel cannot securely contain its own SHA-256 digest. The bootstrap
therefore uses this trust chain:

```text
external bootstrap metadata
  -> exact paper-data-suite wheel SHA-256

authenticated paper-data-suite wheel
  -> bundled release compatibility manifest

bundled manifest
  -> exact Core and optional PDS component wheel identities
```

The caller must provide both:

```powershell
-SuiteWheel <local-suite-wheel>
-SuiteWheelSha256 <expected-64-hex-sha256>
```

The PowerShell workflow verifies that SHA-256 before it executes Python from the
suite wheel. A mismatch exits without creating the requested target environment.
The authoritative suite-wheel digest belongs in release/bootstrap metadata, not
inside the wheel's own embedded manifest.

## Supported platform and interpreter policy

The public workflow is:

```text
scripts/bootstrap_windows.ps1
```

It targets Windows PowerShell 5.1 and PowerShell 7.x. The current compatibility
manifest qualifies Python `>=3.11,<3.15`, specifically minors 3.11, 3.12, 3.13,
and 3.14. Package metadata's broader `>=3.11` declaration does not qualify
Python 3.15 or later for this suite composition.

Use `-PythonExe` to name a specific seed interpreter. Otherwise the workflow
uses `python.exe` from `PATH`. Bootstrap validates the selected interpreter but
does not install Python, upgrade Python, or modify system Python.

## Plan first; apply explicitly

Plan mode is the default. A normal plan:

- authenticates the suite wheel;
- creates a guarded temporary inspection environment;
- installs the authenticated suite wheel there with `--no-deps --no-index`;
- loads the bundled compatibility manifest from that authenticated wheel;
- inspects the requested target environment without executing its Python;
- compares installed PDS distributions with exact suite-qualified versions;
- acquires or reuses only component artifacts required by the plan;
- authenticates those component wheels;
- creates a transient exact-version PDS constraints file; and
- reports the result without mutating the target environment.

A plan ends with:

```text
No changes have been made.
```

Target mutation requires explicit `-Apply`. Interactive application asks for a
final confirmation. Automation and CI may use `-Apply -Yes`. `-Yes` without
`-Apply` is invalid.

## Target environment

The default target is version-qualified:

```text
%LOCALAPPDATA%\Paper Data Suite\envs\<suite-version>\
```

For the current development build:

```text
%LOCALAPPDATA%\Paper Data Suite\envs\0.1.0.dev0\
```

Use `-EnvironmentPath` to choose another dedicated path. The workflow rejects
protected or overlapping locations, including repository overlap, Windows
system roots, Program Files roots, existing reparse-point roots, and other paths
that fail its target-safety checks.

Bootstrap does not adopt an arbitrary existing virtual environment. An existing
target must be a recognizable PDS environment with the expected marker and
exact suite composition. An unmarked environment, malformed marker, wrong suite
version, wrong manifest identity, or incompatible PDS package is a blocker.

## Environment marker

After a successful apply, bootstrap prints both the exact `Activate.ps1`
command and the direct target `Scripts\pds.exe` path.

A successful environment is finalized with:

```text
.pds-suite-environment.json
```

The v1 marker contains only software-composition identity:

```json
{
  "compatibility_manifest_sha256": "<sha256>",
  "contract_version": "1",
  "record_type": "paper_data_suite_environment",
  "suite_version": "0.1.0.dev0"
}
```

It contains no workspace path, username, machine identifier, student data,
credentials, or telemetry identifier.

The marker is written atomically only after installation succeeds, `pip check`
passes, and the authenticated inspection tooling verifies the installed PDS
composition and import layout. A marker therefore means bootstrap finalization
completed; it does not mean optional system prerequisites such as Poppler are
healthy.

## Component selection

Core is always required. Optional component IDs come from the authenticated
manifest rather than a hardcoded application list.

Select specific optional components with:

```powershell
-Components concord,quillan
```

Select every optional component qualified by the target manifest with:

```powershell
-AllComponents
```

Do not combine `-Components` and `-AllComponents`.

If an exact qualified optional component is already installed but is not
selected on a later run, bootstrap retains it. The workflow does not uninstall
PDS packages as part of bootstrap or update planning.

## Exact-version update policy

"Update planning" means comparing one current target environment with one
explicit authenticated target suite release. It does not mean finding the
latest release.

The planner uses these package actions:

```text
keep_exact
install_missing
skip_unselected_optional
blocked_incompatible
```

Any manifest-known PDS distribution installed at a different version is
`blocked_incompatible`, even when that component was not selected for the
current run. Bootstrap does not automatically upgrade, downgrade, uninstall, or
replace it.

An exact-version PDS installation that is editable or source-linked is also
blocked. A matching version string alone is not sufficient evidence of a
qualified released-wheel installation.

For a different suite release, prefer a new version-qualified environment
rather than rewriting the prior environment in place.

## Artifact sources and authentication

For every PDS-owned component, the authenticated manifest declares one exact:

- GitHub repository;
- release tag;
- wheel filename;
- SHA-256 digest;
- distribution name;
- version;
- `Requires-Python`; and
- public entry-point metadata.

When no `-ArtifactDirectory` is supplied, bootstrap downloads required
component wheels only from the exact declared GitHub Release URL:

```text
https://github.com/<repository>/releases/download/<tag>/<wheel>
```

It does not use `/latest/`, mutable branches, package-index "newest" selection,
mirrors, or nearest-version substitution for PDS-owned artifacts.

A caller-supplied `-ArtifactDirectory` is read-only input. Required files must
already have the exact declared filenames. Missing or mismatched artifacts fail;
they are not silently overwritten or replaced.

Every required PDS component wheel is authenticated before it can be given to
pip. Bootstrap verifies the exact filename, SHA-256, wheel readability,
`Name`, `Version`, `Requires-Python`, and declared public entry points.

## PDS constraints and third-party dependencies

Bootstrap generates a transient constraints file that pins every distribution
owned by the active suite manifest, including the suite itself, to its exact
qualified version. This prevents pip from substituting another PDS version while
resolving dependencies.

The constraints file is not a committed lockfile and does not pin the complete
third-party dependency graph.

PDS-owned wheels are exact and authenticated. Ordinary third-party dependencies
remain governed by each component wheel's `Requires-Dist` metadata and are
resolved by pip from the caller's configured package index. Bootstrap therefore
does **not** claim that the complete Python environment is hash-pinned.

## Apply order

A successful apply uses this order:

1. create or validate the dedicated target virtual environment;
2. install exact authenticated Core with no dependency resolution;
3. install the exact authenticated suite wheel with no dependency resolution;
4. install each selected missing optional PDS wheel from its exact local path
   under the transient PDS constraints;
5. run target-environment `python -m pip check`;
6. verify exact installed PDS versions and target-local import roots from the
   authenticated inspection environment; and
7. atomically finalize the environment marker.

All target pip operations use:

```text
<environment>\Scripts\python.exe -m pip
```

Bootstrap does not use `pip install --upgrade`, does not automatically upgrade
pip, and does not install development extras into the target.

## External prerequisites

The current manifest declares `pdftoppm` from Poppler for Quillan and ScoreForm
PDF scan rasterization. Bootstrap reports this prerequisite when either
component is selected, but it does not install Poppler or mutate system `PATH`.

Broad prerequisite health diagnostics belong to `pds doctor` work in Issue #6.
A successful bootstrap marker does not assert that `pdftoppm` is currently
available.

## Failure and cleanup behavior

Bootstrap does not claim transactional rollback for pip operations.

If a run creates a brand-new target and later fails, recursive cleanup is
permitted only when that exact run still proves ownership with its random
bootstrap sentinel and the target passes protected-path and reparse-point
checks. If cleanup succeeds, the incomplete newly created target is removed.

A target that existed before the run is never recursively removed. On a failure
in an existing environment, bootstrap reports the partial state and leaves the
environment available for explicit inspection or replacement.

Caller-owned artifact directories are never recursively removed or rewritten.
Guarded temporary inspection/download roots are created under the operating
system temporary directory with a suite-specific prefix and are removed only
after containment and cleanup-safety checks.

## Source-shadowing defenses

Bootstrap removes inherited `PYTHONPATH` around authenticated suite planning and
uses isolated Python mode (`-I`) for suite-side inspection commands. Existing
target environments are inspected as filesystem/metadata state rather than by
executing their interpreter merely to discover package versions.

Finalization verifies that required PDS import roots resolve beneath the target
`site-packages`. Editable/source-linked PDS distributions and import roots that
resolve outside the target are rejected.

## Privacy and workspace boundary

Windows bootstrap operates only on software-environment state. It does not read,
create, select, or mutate a PDS classroom workspace. It does not inspect classes,
rosters, scans, assignments, grades, behavior/support records, shared work, or
module work directories.

It does not write telemetry, credentials, user identifiers, recent-workspace
state, or student data. Logs should contain only bounded software, artifact,
interpreter, target-environment, and prerequisite information needed to explain
the plan or failure.

## Exit categories

The PowerShell workflow uses stable nonzero categories:

```text
0  successful plan or completed apply
2  invalid arguments or malformed planning input
3  blocked plan or unsafe target, including unsupported suite Python
4  suite/component artifact authentication or acquisition failure
5  installation, finalization, or cleanup failure
```

A nonzero result should be treated as a failed bootstrap/update operation.

## Examples

Plan Core plus all currently qualified optional components using a caller-owned
artifact directory:

```powershell
$suiteHash = (
  Get-FileHash -Algorithm SHA256 -LiteralPath $suiteWheel
).Hash.ToLowerInvariant()

.\scripts\bootstrap_windows.ps1 `
  -SuiteWheel $suiteWheel `
  -SuiteWheelSha256 $suiteHash `
  -AllComponents `
  -ArtifactDirectory $artifactDirectory
```

Apply the same exact plan noninteractively:

```powershell
.\scripts\bootstrap_windows.ps1 `
  -SuiteWheel $suiteWheel `
  -SuiteWheelSha256 $suiteHash `
  -AllComponents `
  -ArtifactDirectory $artifactDirectory `
  -Apply `
  -Yes
```

Plan against an explicit dedicated environment without optional components:

```powershell
.\scripts\bootstrap_windows.ps1 `
  -SuiteWheel $suiteWheel `
  -SuiteWheelSha256 $suiteHash `
  -EnvironmentPath 'C:\PDS Environments\0.1.0.dev0'
```

## Deliberate non-goals

Issue #5 does not implement:

- latest-release discovery or background update checks;
- silent upgrades, downgrades, or uninstall-based repair;
- Python installation or automatic pip upgrade;
- system-wide installation;
- `PATH`, execution-policy, PowerShell-profile, or registry mutation;
- Poppler or other third-party system-software installation;
- a transitive dependency lockfile;
- PyPI publication or a package mirror;
- workspace/class/roster/standards/Academic Period setup;
- `pds doctor` diagnostics;
- installed-module discovery or launching;
- backup/restore; or
- any real-student-data workflow.

Issue #6 owns broader environment diagnostics. Issue #7 owns installed-module
discovery and launching. Issue #13 will consume this bootstrap path for combined
installed-suite acceptance. The v0.1.0 release audit in Issue #14 must publish
or otherwise bind the final suite wheel SHA-256 externally and reauthenticate
the final bootstrap and component artifacts.
