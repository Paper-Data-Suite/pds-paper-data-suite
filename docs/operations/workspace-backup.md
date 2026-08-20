# Workspace backup creation

## Purpose

`pds backup create` creates one complete, timestamped copy of the currently
resolved Paper Data Suite workspace in an explicit external directory.

The backup feature is a suite-shell **opaque-custody** operation. It may enumerate,
copy, hash, and inventory workspace bytes, but it does not acquire semantic
ownership of Core- or module-owned records.

The controlling architecture rule is:

```text
opaque byte custody != semantic record ownership
```

Backup creation does not parse, normalize, repair, merge, or reinterpret records.
Unknown future module directories are backed up the same way as known ones.

## Commands

Interactive creation:

```powershell
pds backup create --destination "D:\PDS Backups"
```

Equivalent module invocation:

```powershell
python -m paper_data_suite backup create --destination "D:\PDS Backups"
```

For deliberate noninteractive use:

```powershell
pds backup create --destination "D:\PDS Backups" --yes
```

`--destination` is always required and names the **parent directory** under which
PDS creates a new timestamped backup. There is no `--source` option. The source is
always the workspace currently resolved by Core.

Running:

```powershell
pds backup
```

shows the available backup subcommands.

## Core qualification and source resolution

The suite first loads its bundled release-compatibility manifest and requires the
exact Core version qualified by that suite release. For the current development
manifest, that is `pds-core==0.6.0`; the broader package dependency
`pds-core>=0.6,<0.7` does not independently qualify other Core versions.

The suite then uses public `pds_core.workspace.inspect_workspace_root` behavior to
obtain the current workspace and its resolution source. Backup creation does not:

- initialize a missing workspace;
- select a different workspace;
- save another workspace preference;
- invoke Core's write-probing workspace validator merely to prove source
  writability; or
- require the source workspace to be writable.

The source must exist and be a directory. Actual readability is proven by the
inventory/copy operation itself.

## Review-before-copy boundary

Before creating any destination directory, the command performs a read-only
preflight and shows a bounded summary containing:

- resolved workspace;
- Core resolution source;
- destination parent;
- proposed final backup path;
- directory count;
- file count;
- total payload bytes;
- destination free bytes;
- minimum required free bytes; and
- backup format version.

The preview does not list individual files, student names, student IDs, grades,
roster rows, per-file hashes, or record contents.

Interactive creation requires exact uppercase:

```text
BACKUP
```

`Q`, end-of-input, or keyboard interruption cancels without creating a backup.
Other input is rejected and the confirmation prompt is repeated.

`--yes` bypasses only the prompt. It does not bypass compatibility, containment,
space, collision, filesystem-entry, source-drift, hashing, or verification checks.

## Sensitive-data warning

A whole-workspace backup contains the same potentially sensitive classroom data as
the source workspace.

PDS does **not** encrypt the backup. SHA-256 hashes provide integrity evidence;
they do not provide confidentiality and are not digital signatures.

PDS also does not upload or cloud-sync backups. If the explicit destination is
inside a OneDrive, Google Drive, Dropbox, network-sync, removable-media, or other
externally managed location, synchronization and access behavior belong to that
external storage system. Use only a teacher-controlled or institutionally approved
location appropriate for the data being copied.

No telemetry or remote backup service is used.

## Backup naming and layout

Completed backups use a UTC timestamp with microseconds:

```text
pds-workspace-backup-YYYYMMDDTHHMMSSffffffZ
```

For example:

```text
pds-workspace-backup-20260820T174812123456Z
```

A completed backup has this layout:

```text
<destination-parent>/
  pds-workspace-backup-<timestamp>/
    manifest.json
    workspace/
      <opaque workspace copy>
```

`manifest.json` is suite-owned backup metadata. It is deliberately outside the
`workspace/` payload so the payload remains the copied workspace tree rather than a
workspace modified by backup metadata.

If the exact timestamped final path already exists, creation fails. PDS never
chooses overwrite as a collision policy.

## Manifest v1 contract

The v1 manifest declares:

```text
record_type = "pds_workspace_backup_manifest"
schema_version = "1"
payload_root = "workspace"
hash_algorithm = "sha256"
```

Its fields are:

```text
record_type
schema_version
backup_id
created_at
suite_version
core_version
payload_root
hash_algorithm
directory_count
file_count
total_bytes
directories
files
exclusions
```

Each file entry contains only:

```text
path
size
sha256
```

The manifest does not store file contents or parsed academic/student data. It does
not record the absolute source workspace path.

### Deterministic serialization

For the same source byte tree, creation timestamp, suite/Core versions, and schema
version, manifest serialization is deterministic:

- directories are sorted;
- file entries are sorted by canonical relative path;
- paths use `/` separators;
- JSON keys are sorted;
- UTF-8 is used;
- SHA-256 digests use lowercase hexadecimal;
- serialization ends with one newline; and
- no process ID, random staging value, access time, or enumeration order enters the
  portable manifest.

`backup_id` derives from the timestamped backup name. Randomness is used only for
temporary `.incomplete-*` staging identity and is never persisted in the manifest.

### Portable path grammar

Manifest v1 paths are relative POSIX-style path strings. They may not contain:

- absolute/rooted syntax;
- `.` or `..` path segments;
- repeated or trailing `/` separators;
- backslashes;
- colons; or
- ASCII control characters.

Backslashes and colons are rejected even on platforms where they could be ordinary
filename characters. This prevents a backup created on one platform from producing
an ambiguous or traversal-capable path when a later restore is evaluated on
Windows. A workspace containing a path that cannot be represented safely in the v1
portable grammar is refused rather than silently omitting that entry.

## Whole-workspace inclusion policy

Manifest v1 has no user-configurable or module-specific source exclusions.
`exclusions` is therefore an explicit empty array.

Ordinary files are included regardless of extension, producer, hidden status, or
whether the shell recognizes their domain. Empty directories are preserved.

The shell does not omit paths such as `.pds/`, `classes/`, `settings/`, scans, or
module-owned work trees because it believes they are unimportant or derived.

## Links, junctions, reparse points, and special files

Backup v1 supports ordinary directories and regular files.

Traversal does not intentionally follow:

- symbolic links;
- Windows junction/mount-point redirection; or
- other recognized redirecting reparse entries.

Such source entries are refused rather than dereferenced or silently skipped.
Unsupported special filesystem entries are also refused.

Windows cloud-provider reparse metadata is not categorically treated as a junction:
the safety rule targets filesystem redirection rather than all reparse-backed local
files. Ordinary locally readable file bytes may therefore be hydrated by the host
filesystem when read.

## Source/destination containment

The destination is canonicalized and checked against the canonical Core workspace.
The backup destination and final backup root must remain outside the workspace.
PDS refuses equivalent/aliased paths, a destination inside the source, and a final
backup path that would contain the source.

For a destination that does not yet exist, preflight resolves its nearest existing
directory for free-space inspection without creating the requested destination.
After confirmation, PDS creates/re-resolves the destination and repeats containment
checks before creating staging state. This protects against a destination path that
resolves differently after review.

Containment is based on path semantics, not string-prefix comparison.

## Free-space preflight

V1 copies ordinary bytes without assuming compression. The conservative threshold
is:

```text
required_free_bytes =
    total_payload_bytes
    + max(64 MiB, ceil(total_payload_bytes * 0.02))
```

Creation is refused when reported destination free space is below this threshold.
The check is repeated after confirmation because free space may have changed.

The check is a safeguard, not a reservation. A later disk-full error still fails the
backup safely.

## Staging, verification, and publication

The final timestamped name is not used as a work directory. After confirmation,
PDS creates an exclusive sibling staging directory with a name conceptually like:

```text
.<backup-id>.incomplete-<nonce>
```

The nonce is temporary and not part of backup identity.

Within staging, PDS:

1. recreates the inventoried directory tree;
2. streams each regular source file into `workspace/` in bounded chunks;
3. calculates SHA-256 from the bytes written;
4. flushes/fsyncs each copied file;
5. re-inventories and re-hashes the source to detect observed drift;
6. independently inventories and re-hashes the staged payload;
7. builds and validates the deterministic manifest;
8. writes the manifest and reads it back for validation; and
9. only then promotes verified staging to the final timestamped backup name.

An existing completed backup is never deliberately replaced. A competing completed
PDS backup is non-empty, so a same-name publication race also fails rather than
replacing that completed tree on supported platforms.

On a handled failure, PDS removes the staging tree best-effort. If cleanup fails,
the command reports the remaining `.incomplete-*` location. An interrupted process
may likewise leave incomplete staging. That directory is **not** a completed backup
and must not be treated as one.

PDS does not automatically remove unrelated or older incomplete staging directories.

## Source consistency limits

Paper Data Suite currently has no suite-wide snapshot transaction or global lock
honored by every Core/module writer. Backup therefore does not claim to be an
operating-system point-in-time snapshot.

The implementation instead detects observed change through inventory and SHA-256
rechecks. If the workspace changes during creation, completion is refused and the
teacher is instructed to close active PDS workflows and retry.

For the strongest practical result, close active PDS application workflows before
starting a backup.

This drift-detection model is not a substitute for adversarial filesystem isolation
against another process with permission to rewrite paths during every individual
system call.

## Completion output

A successful command reports only bounded operational facts:

- source workspace;
- final backup path;
- directory/file counts;
- payload byte count;
- creation time; and
- SHA-256 of the serialized manifest.

It does not dump the manifest inventory or student-bearing file names.

Exit behavior is:

```text
0  completed backup or explicit cancellation
1  safely refused or failed backup
2  argparse/usage error
```

`Workspace backup complete` is printed only after verified staging has been
published at the final backup path.

## Restore boundary

Issue #10 implements **creation-time self-verification only**. It does not claim that
a backup can yet be restored.

The following backup/restore issue owns:

```text
pds backup verify
pds backup restore
```

That work must independently validate this manifest/inventory/hashes and restore only
to an explicit alternate safe location. A restored workspace must not become the
selected Core workspace automatically.

## Installed-wheel acceptance

`scripts/smoke_test_workspace_backup_wheel.py` validates backup creation from built
suite/Core wheels in an isolated virtual environment and user profile. It proves,
with synthetic data only, that:

- both console and module command surfaces are installed;
- no sibling PDS application is required;
- cancellation creates no backup;
- an inside-workspace destination is refused;
- an external backup leaves the source byte tree unchanged;
- hidden, binary, zero-byte, unknown-module, and empty-directory content is copied;
- the manifest independently matches the source inventory and hashes;
- no unlisted payload entry appears;
- the serialized manifest does not contain the source absolute path;
- a pre-existing deterministic backup identity is not overwritten; and
- the smoke working directory remains clean.

## Non-goals

Backup creation does not provide:

- restore;
- a standalone verification command;
- in-place active-workspace replacement;
- automatic selection of restored workspaces;
- ZIP/TAR archives;
- compression;
- encryption or password management;
- cloud-provider APIs;
- scheduled backups;
- retention/pruning;
- incremental/differential backups;
- deduplication;
- module-aware selective backup;
- user-defined exclusion globs;
- domain-record validation or repair;
- VSS or other operating-system snapshots; or
- a global cross-module write lock.
