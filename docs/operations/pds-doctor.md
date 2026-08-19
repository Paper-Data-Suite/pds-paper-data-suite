# `pds doctor` environment diagnostics

`pds doctor` is the read-only health check for an installed Paper Data Suite
environment. It compares the running environment with the release-compatibility
manifest bundled in the installed `paper-data-suite` package and delegates shared
workspace health to public PDS Core services.

The command is diagnostic only. It does not install or update packages, install
system software, create or select a workspace, change user configuration, repair
Core state, clear locks, or modify module-owned records.

## Commands

Run the normal resolved-workspace check with:

```powershell
pds doctor
```

Inspect one workspace for this invocation only with:

```powershell
pds doctor --workspace "D:\School\Paper Data Suite"
```

The `--workspace` value is passed to Core's public workspace inspection service.
It is not saved and the directory is not initialized or created.

The equivalent module invocation is:

```powershell
python -m paper_data_suite doctor
python -m paper_data_suite doctor --workspace "D:\School\Paper Data Suite"
```

## Status and exit semantics

Each check has one of four statuses:

- `PASS` — the check completed and the required condition is satisfied;
- `WARN` — a non-blocking condition needs attention or stronger verification;
- `FAIL` — a required condition is missing, incompatible, corrupt, or unusable;
- `SKIP` — the check is not applicable or cannot run safely with the currently
  available contract/prerequisites.

A completed report exits with:

- `0` when there are no `FAIL` results, including warning-only reports;
- `1` when one or more `FAIL` results exist;
- argparse's normal `2` for invalid command-line syntax.

A failure in one independent area does not normally abort later diagnostics.
Workspace-dependent checks become `SKIP` if Core cannot provide an accessible
workspace rather than producing secondary failures.

## Release authority

The bundled release-compatibility manifest is the authority for:

- qualified Python minors;
- exact suite and component versions;
- required versus optional components;
- declared public entry-point metadata;
- component capabilities;
- manifest-declared external command prerequisites.

`doctor` does not infer compatibility from repository `main`, package-manager
"latest" results, or the fact that a newer package happens to install.

A broad package dependency such as `pds-core>=0.6,<0.7` is not equivalent to the
exact Core release qualified by the active suite manifest.

## Diagnostic coverage

The current command checks, in stable sections:

### Runtime

The running Python `major.minor` must be one of the tested minors in the bundled
manifest. The report also identifies the running interpreter path.

### Suite identity

The installed `paper-data-suite` distribution must match the bundled suite
manifest version.

When the managed-environment marker `.pds-suite-environment.json` is present,
`doctor` validates its suite version and compatibility-manifest SHA-256 using the
suite's existing marker parser. A missing marker is a warning so development or
manual installations remain diagnosable; an invalid or contradictory marker is a
failure. `doctor` never creates or repairs the marker.

### Packages

Every component row in the active manifest is compared with installed distribution
metadata without importing optional applications. Required components must be
present at the exact qualified version. Optional components may be absent, but an
installed optional component at another version is a failure.

### Python dependencies

`doctor` runs the read-only equivalent of:

```text
<running Python> -m pip check
```

with captured output and a bounded timeout. It does not run any pip installation
or upgrade command.

### Public entry points

For exactly qualified installed components, `doctor` compares installed metadata
with the manifest's expected entry-point group, name, target, and owning
distribution. It detects missing, mismatched, duplicate, and foreign/conflicting
metadata without loading optional provider code.

### Core public contracts

The suite verifies that the public Core services it requires for this command are
available. Workspace, school-year, and registry state are consumed through public
Core APIs rather than by duplicating Core storage formats or private validators.

### External prerequisites

External commands are checked generically from the manifest and only when an exact
qualified installed component actually requires them on the current platform.

For the current manifest this includes `pdftoppm` for the qualified ScoreForm and
Quillan PDF-rasterization workflows on supported platforms. If those applications
are absent, their external prerequisite is not treated as a suite blocker.

Python imaging packages are not duplicated in a suite-owned dependency table;
ordinary declared dependency integrity remains the responsibility of package
metadata plus `pip check`, while functional imaging smoke tests remain module-owned.

### Workspace and active school year

Core resolves the workspace using its normal precedence unless `--workspace` is
supplied. The suite reports Core's bounded path/source/existence/directory/writable
status without claiming stronger workspace authenticity than Core's public
inspection contract proves.

For an accessible workspace, the active school year is read through Core. No year
is a warning; malformed/unreadable school-year state is a failure.

### Core registry

For an accessible workspace, `doctor` uses Core's bounded non-mutating registry
status with deep publication-manifest verification disabled by default. It reports
canonical validity, contract compatibility when available, catalog state/currency,
coordination state, and bounded warning/error finding codes/counts.

The suite does not rebuild the catalog, remove locks, repair records, or read raw
student evidence merely to prove environment health.

## Reduced provider fidelity in the current qualified Core contract

The current suite-qualified Core contract does not expose a failure-isolated
health inventory for routing/publication provider execution, nor a shared
module-operations readiness contract.

`doctor` therefore reports those capabilities as `SKIP` with reduced diagnostic
fidelity. It does **not** call Core's strict runtime discovery and does not import
module-private internals to simulate the missing contracts.

When a future suite composition qualifies Core contracts that expose these neutral
surfaces, the suite can consume them without changing ownership: Core validates
Core-defined provider contracts, modules own readiness facts, and the suite owns
aggregation and teacher-facing `PASS`/`WARN`/`FAIL`/`SKIP` presentation.

## Privacy and bounded output

Normal doctor output must not expose student names, answers, scores, writing,
behavior narratives, scans, portfolio artifacts, raw module records, credentials,
or arbitrary environment dumps.

Core registry findings are summarized with bounded codes/counts rather than raw
record payloads. Exception tracebacks are not part of the user-facing diagnostic
contract.

## Installed-wheel acceptance

Release validation must exercise `doctor` from the built wheel, not only from the
repository source tree.

`scripts/smoke_test_wheel.py` creates an isolated virtual environment, installs the
built suite wheel beside the exact Core wheel supplied to the script, removes
`PYTHONPATH`, runs from a separate empty directory, and exercises both:

```text
python -m paper_data_suite doctor
pds doctor
```

The smoke environment points workspace resolution at a deliberately absent
synthetic path so the diagnostic run cannot read a developer's real classroom
workspace. The command must leave that path and the working directory unchanged.

Run the existing package validation flow with:

```powershell
python .\scripts\check_package.py <suite-wheel>
python .\scripts\smoke_test_wheel.py <suite-wheel> <core-wheel>
```

The smoke script exits nonzero if its acceptance assertions fail.
