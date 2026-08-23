# Combined installed-suite acceptance

## Purpose

Paper Data Suite v0.1.0 has focused installed-wheel tests for package loading,
application discovery and launch, workspace setup, shared classroom setup, suite
settings, backup creation, backup verification, restore, and Windows bootstrap.
Those tests remain authoritative for their individual contracts.

The combined installed-suite acceptance adds a different guarantee: the exact
suite-qualified composition must work coherently in **one isolated installed
environment** against **one continuous synthetic Core workspace** from initial
health inspection through alternate-location restore.

The acceptance entry point is:

```text
python scripts/smoke_test_combined_suite_wheels.py \
    <suite-wheel> \
    --artifact-dir <directory-containing-declared-wheels>
```

It is an acceptance harness, not a production command or a second suite state
contract.

## Release authority

The harness loads:

```text
paper_data_suite/data/release_compatibility_v1.json
```

and derives the exact published PDS component composition from that manifest. The
supplied artifact directory is authenticated with the same suite artifact
verification service used by release auditing before any component wheel is
installed.

The harness does not:

- discover a `latest` component release;
- build sibling applications from their repository source;
- substitute another compatible-looking Core release;
- trust sibling repository `main`;
- maintain a second hard-coded release matrix.

The suite wheel under test is the freshly built candidate wheel supplied to the
script.

## Isolation contract

Each run creates one temporary virtual environment and one synthetic user-profile
root. It isolates at least:

```text
HOME
USERPROFILE
LOCALAPPDATA
APPDATA
XDG_CONFIG_HOME
```

and removes inherited `PYTHONPATH` and `PDS_WORKSPACE_ROOT` authority.

The teacher-facing workflow runs through the installed `pds` console launcher from
an empty working directory outside the repository, workspace, artifact directory,
backup destination, and restore destination. Import-root checks require
`paper_data_suite`, `pds_core`, Concord, Quillan, ScoreForm, and Vitrine to resolve
inside the temporary environment rather than from the checkout or user site.

A temporary test-owned `pdftoppm` command is placed on the isolated command PATH so
`pds doctor` can deterministically verify the currently declared Poppler command
prerequisite. This proves command discovery only; it is not a PDF rasterization or
Poppler functional test and the suite does not install system software.

Controlled foreign launchers are also placed earlier on PATH. Successful
`pds launch` acceptance therefore proves that ordinary PATH command-name collision
does not become suite launch authority.

## Continuous scenario

The run keeps the same installed environment and original synthetic workspace
through these stages:

```text
install exact composition
-> initial doctor
-> guided workspace setup
-> full shared classroom setup
-> safe setup rerun
-> configured doctor/provider diagnostics
-> module discovery
-> launch and quit every qualified application
-> suite settings and ownership checks
-> seed neutral opaque custody fixture
-> backup create
-> backup verify
-> alternate-location restore
-> restored workspace inspection
```

No stage creates a new virtual environment or silently replaces the original
workspace lineage.

## Synthetic shared classroom state

The current fixture uses only deliberately synthetic values, including:

```text
school year: 2026-2027
class: eng10
roster: two fictional synthetic students
starter standards pack: njsls_ela_2023
Academic Period: q1
```

The classroom workflow is driven through installed `pds setup`, including exact
uppercase `APPLY`. Public Core readers then verify the resulting school year,
class, guarded roster state, starter standards/profiles, and Academic Period
calendar.

The same setup is run again against current state to prove safe reuse without
roster replacement, duplicate standards, or an extra Academic Period revision.

## Health, providers, and application discovery

Configured `pds doctor` must exercise the qualified Core provider-diagnostics and
module-operations surfaces. For the current exact composition, routing and
publication providers for Concord, Quillan, and ScoreForm must validate.

The current suite release has no qualified module-operations readiness provider,
so the contract remains available while module readiness remains an explicit
`SKIP`. Launchability or provider validity is not promoted into invented readiness.

`pds modules` must expose exactly the manifest-qualified teacher applications.
Each is then started through `pds launch <component-id>` and immediately exited
through its supported menu path.

This is a launchability boundary test. It does not create native ScoreForm,
Quillan, Concord, or Vitrine domain records.

## Settings and ownership boundary

Successful launches naturally update the privacy-minimized suite settings MRU.
The harness verifies that settings remain outside the Core workspace and contain
only the strict schema-v1 fields and qualified component IDs.

`pds doctor`, `pds modules`, application launch/quit, settings inspection, and
settings `clear-recent` must not alter Core workspace bytes.

The harness also performs a source-level import audit of the production
`paper_data_suite` package. Suite production code may use release metadata and
public executable boundaries, but it must not import sibling application packages
to implement suite behavior.

The controlling ownership rule remains:

```text
suite orchestration != module semantic ownership
```

## Opaque custody, backup, and restore

After the semantic shell-only checks, the harness adds a neutral test-owned future
workspace tree containing opaque bytes, a zero-byte file, a hidden synthetic file,
and an empty directory. It deliberately does not pretend those bytes are valid
records belonging to any current PDS module.

The workspace is snapshotted independently before backup. Acceptance then proves:

- `pds backup create --yes` leaves source bytes unchanged;
- the completed backup payload is byte-for-byte identical to the source snapshot;
- backup manifest suite/Core provenance matches the active manifest;
- persisted manifest SHA-256 matches command output;
- `pds backup verify` succeeds without changing source state;
- `pds backup restore --yes` publishes one fresh alternate workspace;
- the restore contains no backup `manifest.json` and no extra `workspace/` nesting;
- restored bytes are identical to the reviewed source snapshot;
- Core's saved selected workspace remains the original workspace;
- no incomplete restore staging remains.

The restored workspace is then inspected with an invocation-scoped
`PDS_WORKSPACE_ROOT` override. Public Core services must still read the expected
school year, class, roster, standards, and Academic Period state. `pds doctor`
must also operate against the restored copy. Removing the override must reveal the
unchanged original saved selection.

Backup and restore remain opaque byte custody. The harness does not parse
module-owned records to establish backup correctness.

## CI matrix

GitHub Actions runs the dedicated `combined-installed-suite` job with
`fail-fast: false` across:

```text
ubuntu-latest  / Python 3.11
ubuntu-latest  / Python 3.12
ubuntu-latest  / Python 3.13
ubuntu-latest  / Python 3.14
windows-latest / Python 3.11
windows-latest / Python 3.12
windows-latest / Python 3.13
windows-latest / Python 3.14
```

Each matrix cell independently:

1. builds the candidate suite wheel;
2. downloads exact component wheels from manifest release tags;
3. authenticates the component artifacts;
4. validates the candidate distribution;
5. runs the complete combined installed-suite harness; and
6. checks repository hygiene afterward.

This job supplements the existing general validation, release-artifact, and
Windows-bootstrap jobs. It does not replace their focused evidence.

## Local validation

With a freshly built suite wheel and an artifact directory containing every exact
component wheel declared by the active manifest:

```text
python scripts/verify_compatibility_artifacts.py \
    --artifact-dir <artifact-directory>

python scripts/smoke_test_combined_suite_wheels.py \
    <suite-wheel> \
    --artifact-dir <artifact-directory>
```

A successful run ends with:

```text
Combined installed-suite acceptance passed.
```

Stage labels are intentionally bounded so CI failures identify the failed part of
the continuous workflow without dumping student rows, file inventories, arbitrary
module records, credentials, or environment contents.

## Non-goals

This acceptance does not prove or implement:

- ScoreForm assessment creation, OMR scoring, or scan processing;
- Quillan assignment/review/rating workflows;
- Concord Activity, Session, GroupPlan, Group, membership, moderation, or scoring;
- Vitrine Candidate, Selection, Portfolio, Snapshot, Edition, or export workflows;
- Meridian or Portia functionality;
- mixed-module scan ingestion or PDS2 dispatch workflows;
- publication creation/consumption;
- module readiness or attention providers;
- group-planning interoperability;
- LMS/SIS integration;
- cloud synchronization or telemetry;
- a GUI;
- final v0.1.0 release approval.

Those remain owned by their repositories or later milestones. The final skeptical
security, privacy, usability, and release review belongs to suite issue #14.
