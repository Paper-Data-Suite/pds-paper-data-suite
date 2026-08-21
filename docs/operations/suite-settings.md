# Suite settings and recent safe context

Paper Data Suite stores a deliberately small amount of suite-owned convenience
state so the `pds` shell can remember recent top-level applications across
invocations. This file is optional user configuration. It is not a second
workspace, classroom, student, assessment, grading, portfolio, grouping, or
support-data store.

The ownership boundary is:

```text
Core
  authoritative shared workspace and shared state

modules
  authoritative domain and workflow state

suite settings
  disposable non-sensitive shell convenience only
```

Deleting or resetting suite settings may remove convenience, but it must never
remove or change canonical PDS records.

## Commands

Inspect the bounded shell settings:

```powershell
pds settings show
```

Clear only recent top-level application context:

```powershell
pds settings clear-recent
```

Replace only the suite settings document with schema-v1 defaults:

```powershell
pds settings reset
```

Equivalent module-form commands are available through
`python -m paper_data_suite`.

`settings show` is read-only. A first-run invocation with no settings file uses
in-memory defaults and does not create the settings directory or file.

`settings clear-recent` and `settings reset` never call Core's workspace reset
service. They do not initialize, select, clear, validate, restore, or otherwise
mutate a workspace. They also do not change module-owned workflow context.

## Storage location

The settings file is outside canonical PDS workspaces and does not depend on the
current working directory.

The v1 path is:

| Platform | Path |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Paper Data Suite\settings.json` |
| macOS | `~/Library/Application Support/Paper Data Suite/settings.json` |
| Linux and other XDG-style systems | `${XDG_CONFIG_HOME:-~/.config}/paper-data-suite/settings.json` |

On Windows, if `LOCALAPPDATA` is unavailable, the fallback is
`~/AppData/Local/Paper Data Suite/settings.json`. On XDG-style systems, a
relative `XDG_CONFIG_HOME` is not accepted as a configuration root; the shell
falls back to `~/.config`.

Tests and installed-wheel acceptance isolate these roots so development does not
read or modify a real user's settings.

## Schema v1

The complete schema-v1 document is intentionally limited to three fields:

```json
{
  "record_type": "paper_data_suite_settings",
  "schema_version": "1",
  "recent_components": [
    "quillan",
    "scoreform"
  ]
}
```

There are no schema-v1 workspace, class, assignment, student, score, review,
grouping, grade, portfolio, behavior/support, scan, evidence, publication,
credential, telemetry, or arbitrary plugin fields.

### Persisted fields

| Field | Owner | Purpose | Allowed values | Privacy classification | Default | Stale-value behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `record_type` | Suite | Identify this document family | Exact value `paper_data_suite_settings` | Non-sensitive metadata | `paper_data_suite_settings` | Any other value is rejected |
| `schema_version` | Suite | Select the settings contract | Exact value `1` | Non-sensitive metadata | `1` | Unknown/newer versions fail closed and are not rewritten automatically |
| `recent_components` | Suite | Bounded MRU of top-level suite applications explicitly launched by the teacher | Zero to five exact `component_id` values from the active suite compatibility declaration that are `launchable_application` components | Non-sensitive navigation metadata | Empty list | Stored identity remains only a hint; `settings show` re-resolves current installed/compatibility status before presenting it |

The list is most-recent-first, contains no duplicates, and has a maximum length
of five. Re-launching an existing component moves it to the front. No timestamp
is stored, so the shell does not build a behavioral history beyond ordering.

The settings parser is strict. It rejects malformed JSON, duplicate JSON object
keys, missing or unknown fields, unsupported schema versions, invalid component
IDs, duplicate recent entries, and lists beyond the v1 limit. A settings document
does not become a generic JSON extension point merely because a future field
might be useful.

## Component identity and current availability

Settings store stable suite component IDs such as `quillan` and `scoreform`.
They do not store display names, console command strings, Python import paths,
URLs, executable paths, or shell fragments.

A stored recent component is never launch authority. When recent context is
presented, the shell resolves it against the current suite application inventory.
The current compatibility manifest and installed component state still decide
whether an application is available, not installed, incompatible, or otherwise
unavailable. Recent context cannot bypass those checks or execute an arbitrary
command.

Schema validation is against component identities qualified as launchable by the
active suite release declaration, not against whether the component happens to be
installed at that moment. This permits a legitimately recorded component to
remain readable after it is uninstalled. A component identity no longer admitted
by a future suite settings contract is rejected rather than silently trusted.

## Launch update boundary

The existing `pds launch <component-id>` workflow is the only v1 source of recent
component updates.

The ordering is:

```text
resolve exact manifest component
-> verify it is suite-launchable
-> build and resolve current application inventory
-> verify current launch availability
-> start the verified foreground application process
-> record that top-level component as recent
```

A component is not recorded because it appeared in `pds modules`, was inspected
by `doctor`, participated in backup/restore, or failed availability or launcher
checks.

The suite records recency only after the verified child application has actually
started. A process that starts and later exits with a nonzero status is still a
real top-level application interaction and is therefore recent. A process that
cannot be started is not recorded.

Settings are optional convenience state. If the application starts but the recent
setting cannot be saved, the shell reports a bounded warning while preserving the
application's own exit outcome. A settings failure must not make module-domain data
look corrupt or make settings persistence a prerequisite for application use.

## Workspace authority

The settings document contains no field equivalent to:

```text
selected_workspace
active_workspace
workspace_root
current_workspace
default_workspace
```

Core remains the sole authority for workspace normalization, resolution,
initialization, validation, persisted selection, and reset. `pds settings show`
states that boundary but does not independently resolve or cache a workspace path.

In particular:

```text
pds settings reset
    -> suite preference file only

pds workspace reset
    -> Core-owned saved workspace selection
```

These commands are independent and are tested as separate dispatch paths.

## Privacy boundary

The settings model has no public surface for retaining classroom or learner-domain
objects. It must not contain or derive:

```text
student names or IDs
rosters or class-level workflow context
assignments or student responses
answers, scores, Grades, proficiency, or rubric ratings
student writing, teacher feedback, or teacher notes
raw scans, evidence, QR/PDS2 payloads, or route records
Concord Activity/Session/GroupPlan/Group/GroupMembership state
grouping signals or planning bands
Meridian evidence decisions or Grade state
Vitrine Candidate/Selection/Portfolio state
Portia behavior/support observations or narratives
publication contents
credentials, tokens, passwords, or environment dumps
```

Settings code does not inspect module storage or filesystem modification times to
infer what the teacher was working on. The suite may remember that Quillan was a
recently launched component; Quillan itself owns any class, assignment, submission,
student, review, or feedback context within Quillan. The same rule applies to every
other module.

The settings file is ordinary local configuration and is not encrypted. PDS does
not synchronize, upload, analyze, or send telemetry from it. If an operating system
or user-controlled storage product synchronizes the configuration directory, that
is external storage behavior, not a PDS synchronization feature.

## Missing, malformed, and unsupported settings

A missing file is normal first-run state:

```text
load
-> schema-v1 defaults in memory
-> no file or directory creation
```

Malformed JSON, an invalid v1 document, or an unsupported future schema produces a
bounded settings error. The shell does not silently discard or rewrite that file.
The recovery command is:

```powershell
pds settings reset
```

Reset stages and atomically publishes a fresh default settings document. It does
not require reinstalling Core, recreating a workspace, restoring a backup, or
repairing module records.

## Persistence and filesystem safety

Writes serialize and validate the complete document before touching the canonical
file. Persistence then uses a temporary file in the same settings directory,
flushes and `fsync`s the complete UTF-8 bytes, and atomically replaces the
canonical file with `os.replace` where supported by the platform. JSON formatting
is deterministic and ends with one newline.

Handled serialization or staging/replacement failures do not intentionally
truncate a previously valid canonical document. Temporary artifacts are cleaned up
where safe. On POSIX systems, newly staged settings files are restricted to mode
`0600` before publication.

The v1 store intentionally uses a simple last-complete-write model; it does not
claim multi-process transactional merging or locking. Canonical domain integrity
never depends on this preference file.

The implementation refuses a settings target that is a directory or direct
symbolic link and refuses a direct symbolic-link settings directory. Temporary
files are constrained to the selected settings directory. This is a practical
per-user configuration defense, not a second backup-grade filesystem subsystem.

## Backup and restore

Whole-workspace backup and restore operate on the Core-selected canonical workspace.
Suite settings live outside that workspace and are therefore not included in the
workspace backup format.

`pds backup restore` does not update suite recent context and never selects the
restored workspace. A later explicit `pds workspace set <restored-location>` still
uses Core as the only workspace-selection authority, and that selection is not
mirrored into suite settings.

## Import and read-only behavior

Importing `paper_data_suite` or `paper_data_suite.settings` does not resolve a
workspace, discover sibling modules, create the settings directory, create the
settings file, or perform network or classroom-data access.

Reading settings is an explicit operation. Current installed-application probing is
performed only when a CLI presentation such as `pds settings show` needs to label
stored component IDs with current availability.

## Future boundaries and sequencing

This v1 facility is only the privacy-minimized persistence foundation for top-level
suite navigation. It does not implement the later v0.2.0 recent-work/continue-task
workflow in issue #24. That later work must separately define owner-provided work
references, stale-reference handling, privacy limits, and safe actions rather than
expanding this file into a cross-module learner or task database.

Issue #12 also does not adopt unreleased Core APIs or change the exact Core row in
the active suite compatibility manifest. After #12 and the authenticated Core
v0.6.2 release work are both complete, issue #38 owns qualification of Core v0.6.2
and adoption of the current shared-service contracts. Combined installed-suite
acceptance follows that qualification step.

## Validation

Focused tests cover strict schema validation, missing/read-only state, MRU behavior,
privacy exclusions, atomic replacement, filesystem redirects, import isolation,
Core/module noninterference, CLI management, current-inventory revalidation, and
application-launch recency semantics.

The dedicated installed-wheel smoke is:

```powershell
python .\scripts\smoke_test_settings_wheels.py `
  <suite-wheel> `
  --artifact-dir <directory-containing-declared-wheels>
```

It installs the suite and exact currently qualified PDS composition outside the
source checkout, isolates the per-user configuration roots, proves import/help/
first-run show do not create settings, records recent components through real
installed `pds launch` boundaries, verifies deterministic MRU ordering, and proves
`clear-recent` and `reset` leave Core workspace selection and canonical workspace
bytes unchanged.
