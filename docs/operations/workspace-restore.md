# Workspace backup verification and restore

## Purpose

Paper Data Suite can independently verify a completed whole-workspace backup and
restore verified opaque workspace bytes to one explicit alternate location.

The commands are:

```powershell
pds backup verify <backup>
pds backup restore <backup> --destination <path>
```

Equivalent module invocations are:

```powershell
python -m paper_data_suite backup verify <backup>
python -m paper_data_suite backup restore <backup> --destination <path>
```

This work consumes the backup-v1 format documented in
[`workspace-backup.md`](workspace-backup.md). It does not define a second backup
format.

The controlling architecture rule remains:

```text
opaque byte custody != semantic record ownership
```

Verification and restore inspect filesystem shape, sizes, and bytes. They do not
parse, normalize, repair, migrate, merge, or reinterpret Core- or module-owned
records.

## Verification

`pds backup verify` is read-only and noninteractive.

A completed v1 backup must have the canonical layout:

```text
pds-workspace-backup-YYYYMMDDTHHMMSSffffffZ/
  manifest.json
  workspace/
```

Verification rejects incomplete `.incomplete-*` staging, malformed or
noncanonical manifests, backup-name/manifest identity disagreement, missing or
unexpected top-level state, unsupported filesystem redirection, and payload
inventory or hash disagreement.

The payload directory set and ordinary-file set must match the manifest exactly.
This includes hidden files, unknown future module trees, zero-byte files, and
empty directories.

Every file is checked by:

1. confirming the entry is an ordinary regular file;
2. comparing its size with the manifest;
3. streaming it in bounded chunks;
4. calculating SHA-256 independently; and
5. comparing the digest with the manifest.

A same-size byte change is therefore detected.

Verification does not resolve or select the active Core workspace and does not
require sibling PDS applications.

### Verification output

Successful verification reports bounded operational facts:

- backup root;
- backup ID;
- creation time;
- recorded suite version;
- recorded Core version;
- directory count;
- file count;
- payload bytes; and
- SHA-256 of the persisted manifest.

Normal output does not dump the complete file inventory, per-file digests,
student names, student IDs, grades, roster rows, or file contents.

## Integrity is not authenticity

SHA-256 proves agreement between the supplied manifest and payload bytes. It does
not prove who created the backup.

An actor capable of replacing both `manifest.json` and `workspace/` could create a
new internally consistent pair.

Verification therefore must not be described as:

```text
signed
authenticated
trusted
tamper-proof
```

unless a future contract introduces an authentication mechanism.

Likewise:

```text
integrity != runtime compatibility
```

The manifest's recorded suite/Core versions are provenance. A byte-valid backup
is not automatically guaranteed to be semantically usable by every currently
installed component.

## Restore destination contract

Restore requires:

```powershell
pds backup restore <backup> --destination <path>
```

`--destination` is the **exact final restored workspace root**.

This differs from backup creation, where `--destination` names the parent under
which a timestamped backup directory is generated.

If the command is:

```powershell
pds backup restore `
  "D:\PDS Backups\pds-workspace-backup-20260820T174812123456Z" `
  --destination "D:\PDS Recovery\restored-workspace"
```

the payload is restored directly as:

```text
D:\PDS Recovery\restored-workspace\
  <contents formerly under backup-root\workspace\>
```

PDS does not create an extra nested `workspace/` directory and does not copy
backup `manifest.json` into the restored workspace.

## Full verification before restore

Restore never copies from an unverified backup.

Before preview, PDS independently verifies the complete backup using the same
verification service as `pds backup verify`.

Immediately after confirmation, before destination mutation, PDS verifies the
reviewed backup again.

There is no:

```text
--force
--skip-verification
--ignore-hash-errors
```

escape hatch.

## Core qualification and active-workspace protection

Restore exactly qualifies Core through the suite release-compatibility contract
and uses the public Core workspace inspection service to identify the currently
resolved workspace.

Restore does not call Core to:

- initialize the destination;
- save the destination as selected;
- clear the current selection; or
- rewrite workspace metadata.

The resolved workspace path is protected even if that path does not currently
exist.

The restore destination must not:

- equal the resolved workspace;
- be inside the resolved workspace; or
- contain the resolved workspace.

This preserves:

```text
restore bytes != change active workspace
```

## Destination safety

The restore destination must be explicit and must not already exist.

An existing empty directory is refused just like an existing nonempty directory
or file. This issue intentionally defines no merge or overwrite semantics.

The destination must not overlap:

- the completed backup root;
- the backup `workspace/` payload; or
- the currently resolved Core workspace.

Path checks use canonical filesystem semantics rather than string prefixes and
account for path expansion, aliases, `..`, case/platform path behavior, and
missing destination ancestors.

An existing destination expressed through environment or user-home expansion is
still an existing destination and is refused during planning.

## Free-space preflight

Restore reuses the conservative backup threshold:

```text
required_free_bytes =
    total_payload_bytes
    + max(64 MiB, ceil(total_payload_bytes * 0.02))
```

Free space is inspected on the filesystem that will contain the destination.

The check is performed during preview planning and repeated after confirmation.
It remains a safeguard, not a reservation; a later disk-full error still fails
safely.

## Restore preview and authorization

The preview contains bounded facts including:

- source backup;
- backup ID and creation time;
- recorded suite/Core versions;
- manifest SHA-256;
- directory/file counts;
- payload bytes;
- currently resolved workspace and resolution source;
- exact restore destination;
- destination free bytes; and
- minimum required free bytes.

It also states that the current workspace will not be modified and that the
restored workspace will not be selected automatically.

Interactive restore requires exact uppercase:

```text
RESTORE
```

`Q`, end-of-input, or keyboard interruption cancels safely.

Other input does not authorize restoration.

For deliberate automation:

```powershell
pds backup restore <backup> --destination <path> --yes
```

`--yes` bypasses only the prompt. It does not bypass verification, Core
qualification, containment, free-space checks, destination nonexistence, drift
detection, staged verification, or publication collision checks.

## Staging and byte copy

Restore never copies directly into the requested final destination.

After post-confirmation revalidation, PDS creates one exclusive sibling staging
directory with a name conceptually like:

```text
.<destination-name>.pds-restore.incomplete-<nonce>
```

The nonce is operational state only.

Within staging, PDS:

1. recreates every manifest directory, including empty directories;
2. streams each manifest-qualified payload file in bounded chunks;
3. hashes the bytes actually written;
4. flushes/fsyncs copied files;
5. rejects source type/size/hash drift;
6. re-verifies the completed source backup after copying;
7. independently inventories the staging tree;
8. independently hashes every staged file; and
9. publishes only when the staged tree exactly matches the manifest.

No record serializer or module-specific validator participates.

## Backup drift

A completed backup can still be changed externally while restore is running.

Paper Data Suite has no global filesystem lock and does not claim adversarial
same-user filesystem isolation.

Instead it uses conservative observed-drift detection:

- full verification before preview;
- full verification again before mutation;
- streamed copy with per-file expected size/hash;
- full source-backup verification after copy; and
- independent staged-tree verification.

If observed backup state changes, restore fails rather than publishing a mixed
tree.

The backup is never modified to make it consistent.

## Publication and collision behavior

A successful final destination appears only after the staging tree has passed
verification.

Immediately before publication PDS checks again that the final destination does
not exist. A destination already present at that boundary is refused and is not
merged, overwritten, or deleted.

The source backup and current Core workspace remain unchanged.

## Failure cleanup

On handled failure PDS removes only staging owned by the current restore attempt,
best-effort.

It never deletes:

- the source backup;
- the current workspace;
- a pre-existing final destination; or
- another pre-existing incomplete staging directory.

If owned staging cannot be removed, the failure reports the remaining incomplete
staging path. That path is not a completed restored workspace.

Abrupt process or operating-system failure may also leave incomplete staging.
PDS does not automatically prune unrelated historical staging.

## Successful completion

Only after verified publication does the command print:

```text
Workspace restore complete
```

The result explicitly states:

```text
The currently resolved workspace was not changed.
The restored workspace was not selected automatically.
```

A teacher can inspect current selection separately:

```powershell
pds workspace show
```

If the recovered copy should become active, that is a distinct intentional Core
operation:

```powershell
pds workspace set "<restore-destination>"
```

Restore never chains or invokes that command automatically.

## Privacy boundary

Verification and restore operate over potentially sensitive classroom data.

Default output is deliberately bounded and does not print:

- complete manifest inventory;
- per-file hashes;
- file contents;
- roster rows;
- student names or IDs;
- grades or scores; or
- parsed owner records.

A failure may identify one offending relative path when needed for remediation,
but it does not print file contents.

PDS does not upload backups, restored workspaces, or telemetry.

Restore does not add encryption.

## Version provenance and migration

A successful byte restore means the copied tree matches the verified backup.

It does not mean historical records have been migrated to the currently installed
Core/module versions.

Restore does not:

- bump schema versions;
- run owner migrations;
- repair malformed records;
- infer semantic compatibility; or
- import sibling modules to validate their records.

Any required migration remains owned by the corresponding component contract.

## Exit behavior

```text
0  successful verification/restore or explicit restore cancellation
1  safely refused or failed verification/restore
2  argparse/usage error
```

Success is never reported before all relevant verification/publication checks
complete.

## Installed-wheel acceptance

`scripts/smoke_test_workspace_restore_wheel.py` validates verification and restore
from built suite/Core wheels in an isolated virtual environment and synthetic user
profile.

It proves, with synthetic data only, that:

- only the suite and exact Core wheel are required;
- console and module verify/restore command surfaces are installed;
- a completed backup verifies independently;
- manifest SHA-256 reporting matches persisted bytes;
- normal output does not leak a synthetic sensitive filename;
- restore cancellation creates no final destination;
- the active workspace cannot be used as restore destination;
- a successful alternate restore is byte/tree identical to the synthetic source;
- backup `manifest.json` is not injected into the restored workspace;
- Core's selected workspace remains unchanged;
- an existing destination is refused and preserved;
- incomplete backup staging is refused;
- same-size tampered backup bytes fail verification;
- no restore staging remains after successful completion; and
- the smoke working directory remains clean.

## Non-goals

Verification/restore does not provide:

- in-place active-workspace replacement;
- merge into an existing directory;
- overwrite flags;
- automatic `pds workspace set`;
- automatic Core selection mutation;
- semantic merge;
- selective class/student/module restore;
- module-aware record repair;
- schema migration;
- runtime-compatibility inference;
- ZIP/TAR extraction semantics;
- compression;
- encryption/password management;
- digital signatures/authenticated manifests;
- cloud upload/download;
- scheduled recovery;
- retention/pruning;
- VSS or operating-system snapshots; or
- a global cross-module lock.
