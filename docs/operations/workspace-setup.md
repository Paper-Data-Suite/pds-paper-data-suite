# Workspace selection and validation

## Purpose

The Paper Data Suite shell provides one guided entry point for selecting and validating the shared local workspace while preserving PDS Core as the workspace authority.

The shell owns presentation and orchestration only:

```text
teacher
  -> pds workspace ...
      -> suite review/presentation
          -> public pds_core.workspace services
              -> Core-owned workspace state
```

The suite does not define a second workspace schema, write Core configuration JSON directly, parse Core's private workspace marker, or route shared workspace setup through sibling applications.

The active suite compatibility manifest remains the release authority. The current `0.1.0.dev0` composition qualifies `pds-core 0.6.0` exactly even though the package dependency range is `pds-core>=0.6,<0.7`. Workspace operations fail closed when the installed Core release does not match that exact qualification.

## Commands

The public commands are:

```powershell
pds workspace setup
pds workspace show
pds workspace validate
pds workspace validate <path>
pds workspace set <path>
pds workspace reset
```

Equivalent module forms are available through:

```powershell
python -m paper_data_suite workspace ...
```

`setup` is the teacher-facing review-before-write workflow. The other commands are deterministic direct operations useful for diagnostics, scripting, recovery, and explicit administration.

## Core resolution precedence

The shell does not implement workspace precedence itself. It consumes Core's resolved path and source.

Core currently resolves in this order:

```text
explicit invocation path
  > PDS_WORKSPACE_ROOT
  > saved Core workspace configuration
  > Core default workspace root
```

The shell translates Core's bounded source values into teacher-facing labels such as `environment override`, `saved workspace selection`, and `Core default location` without changing their meaning.

## `pds workspace show`

`show` is informational only. It reports the Core-resolved path, selection source, filesystem accessibility facts, Core configuration path, default workspace path, and a bounded presentation state.

It does not create a missing workspace, save a preference, inspect student records, enumerate classes, or initialize Core metadata.

A missing resolved path is not by itself a command failure. `show` may complete successfully and report `not created yet`.

## `pds workspace validate [<path>]`

`validate` checks whether an existing path can be used by Core without creating or selecting it.

With no path, it validates the currently resolved workspace. With an explicit path, it validates only that candidate.

The shell delegates to Core with creation disabled. Therefore:

- a missing candidate fails and remains absent;
- an existing writable empty directory can pass;
- an existing writable non-empty directory can pass if Core accepts it;
- a regular file, filesystem root, unwritable directory, or other Core-rejected candidate fails;
- no workspace preference is changed;
- no missing directory is initialized.

Core may perform its own temporary writeability probe as part of validation. The suite does not create a separate probe.

## `pds workspace set <path>`

`set` is an explicit noninteractive mutation command. It asks Core to initialize the supplied path and then asks Core to save that path as the workspace preference.

The operation may create:

```text
the workspace directory
Core workspace metadata
Core baseline directories
Core saved workspace configuration
```

It does not move, copy, merge, or delete a previous workspace, and it does not create school years, classes, rosters, standards, Academic Periods, or module-owned records.

After saving, the suite re-inspects through Core. Success is reported only when Core actually resolves the intended path.

## `PDS_WORKSPACE_ROOT` environment override

`PDS_WORKSPACE_ROOT` outranks the saved Core preference.

If it is active, the shell displays that fact prominently. The guided workflow may initialize or validate the environment-selected path, but it does not edit or remove the environment variable.

A direct attempt to run:

```text
pds workspace set <different-path>
```

while the environment override is active fails before initializing the alternate candidate. Saving a different Core preference would not make that path active, so the shell refuses to claim otherwise.

`pds workspace reset` may still clear a saved preference while an environment override exists. The environment-controlled path remains active afterward.

## `pds workspace reset`

`reset` clears only Core's saved workspace preference. It is idempotent when no saved preference exists.

It never deletes workspace files or Core metadata. After reset the shell re-inspects and shows the actual current Core resolution, which may be an environment override or Core's default location.

## Guided `pds workspace setup`

The guided workflow is deliberately low-density:

1. show the current Core-resolved path and source;
2. let the teacher keep the current location, choose another path, validate only, or quit;
3. inspect and normalize the candidate through Core;
4. show whether the candidate is missing, empty, existing/non-empty, or invalid/unusable;
5. preview what Core will do;
6. require the exact confirmation word `USE` before persistent mutation;
7. initialize and, when appropriate, save through Core;
8. re-inspect and display the actual final resolution.

Blank confirmation, `Q`, Ctrl+C, or EOF cancels safely before mutation. Cancellation is not treated as an operational failure.

An existing non-empty directory receives an explicit warning because Core initialization may add PDS structure beside unrelated files. The suite performs only a shallow emptiness check for this presentation distinction; it does not list or read directory contents.

## Empty versus invalid

The suite uses a small presentation vocabulary over public Core facts:

```text
missing
empty directory
existing non-empty directory
invalid / unusable
```

These labels are not a second workspace schema.

A directory is not invalid merely because it has no:

```text
school year
classes
rosters
standards
Academic Periods
module records
scans
publications
```

A synchronized folder is likewise not rejected merely because it is synchronized. This issue contains no OneDrive-, Dropbox-, Google Drive-, or network-share-specific policy.

## Partial completion and failure

Workspace initialization and saved-selection persistence are separate Core operations. The suite does not pretend they are transactionally atomic.

If initialization fails, the new preference is not saved.

If initialization succeeds but saving fails, the shell reports partial completion:

```text
workspace initialization succeeded
saved selection did not complete
```

It does not manually delete Core-created directories or metadata in an attempt to roll back work it does not own.

If saving succeeds but Core subsequently resolves another path, the shell reports failure and shows the actual Core-resolved state rather than claiming success.

## Relationship to `pds doctor`

The responsibilities remain distinct:

```text
pds workspace
  -> select, initialize, validate, and reset workspace context

pds doctor
  -> read-only broader environment and workspace health diagnosis
```

A newly initialized workspace may legitimately have no active school year and therefore produce later doctor warnings. That does not mean workspace initialization failed.

## Relationship to later setup

Workspace setup intentionally stops before shared classroom configuration.

Later work owns:

```text
school-year setup
class creation
roster import
standards setup
Academic Period setup
```

The expected sequence is:

```text
select/initialize Core workspace
  -> configure shared classroom state
```

## Backup and migration boundary

Selecting a different workspace does not migrate data.

The shell does not automatically:

```text
copy an old workspace
move an old workspace
merge two workspaces
delete an old workspace
create a backup
restore a backup
```

Backup and restore are separate suite workflows.

## Installed-wheel acceptance

The repository includes a dedicated installed workspace smoke test:

```powershell
python .\scripts\smoke_test_workspace_wheel.py `
  <suite-wheel> `
  <exact-core-0.6.0-wheel>
```

The smoke test creates a fresh virtual environment and synthetic user home outside the repository, installs only the built suite wheel and exact Core wheel, strips source-shadowing and real workspace overrides, and verifies:

- installed package import comes from the isolated environment;
- initial `workspace show` does not create Core's default location;
- validation of a missing candidate fails without creating it;
- guided module-form setup creates and selects a synthetic workspace;
- Core baseline directories exist after Core initialization;
- Core reports the selected path through its public inspection API;
- installed `pds`/`pds.exe workspace show` observes the saved selection;
- installed reset removes only the preference and preserves the workspace;
- direct installed `workspace set` can reselect the initialized workspace;
- an active `PDS_WORKSPACE_ROOT` prevents a different `set` before candidate mutation;
- a final reset leaves the initialized workspace intact;
- the smoke working directory remains clean.

The smoke environment overrides `HOME`, `USERPROFILE`, `APPDATA`, and `XDG_CONFIG_HOME` and removes inherited `PDS_WORKSPACE_ROOT` and `PYTHONPATH` variants. It therefore must not consume or mutate the teacher's actual workspace preference or classroom data.
