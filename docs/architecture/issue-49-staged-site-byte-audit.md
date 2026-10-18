# Issue #49 Slice 8 — Read-only staged purelib file and RECORD audit

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

**Scope:** additive verifier, no live launcher/doctor/bootstrap/update behavior changes.

## Verified inputs, and what the result means

`paper_data_suite.evergreen_staged_install.audit_staged_site_packages` accepts
raw signed registry and dependency-lock envelopes, an **independently pinned**
trusted keyring, a caller-supplied prepared-record byte string, a previously
prepared offline wheelhouse, and a private staging directory. It invokes
`verify_prepared_record_against_wheelhouse` to authenticate the exact lock and
wheelhouse again. It then inspects `stage_root/site-packages` **without**
importing staged packages or launching a process.

For purelib wheels with direct site-packages paths, it compares the complete
staged file set with exact authenticated wheel members. Every non-`RECORD`
installed file must match its wheel byte-for-byte (SHA-256 and length). All
staged `RECORD` CSV entries must be complete, hash/size validated, attributed
to the correct wheel, and free from path traversal, duplicate paths, untracked
files, blank hashes except the `RECORD` entry itself, and unknown hash schemes.
An unrelated installed distribution, added `.pth`, injected Python file,
deleted module, or changed metadata rejects the stage. The wheel content is
rehashed under the same open file descriptor before and after archive parsing;
the stage inspection does not trust an earlier mutable file observation alone.

The returned `StagedSiteAudit` is a **one-time, read-only observation of a
restricted staged file layout**, not evidence of a fully installed Python
interpreter, verified generated console executables, `pip check` results, an
atomic activation, production trust keys, a durable monotonic checkpoint, or
an active software composition. Its plain dataclass can also be instantiated
by callers; downstream authorization must NEVER trust it on its own.

## Supported layout and deliberately refused cases

The caller supplies a private `stage_root` with one `site-packages` directory.
The function refuses direct inspection of the running interpreter prefix.
All stage files must be regular, with no detectable symlinks/reparse points
anywhere inside the audited tree; archives must not contain `.data/` scheme
files in this slice. Generated `.pyc`, launch scripts outside `site-packages`,
external `.data` installation destinations, editable installs, and installed
files not identical to the authenticated wheel payload are intentionally
**unsupported**, not silently approved. This is a first stage-integrity gate,
not the final installer or a general verifier for a live pip environment.

A later release slice must qualify real pip staging layouts (including Windows
console scripts, compiled artifacts and `.data` relocations when necessary),
verify complete package metadata/entry point ownership and PDS module publisher
signatures, and run **offline** installation/health checks in isolated stages.
Before active launch, signed-lock inputs must be backed by protected deployed
trust and rollback continuity, installed receipts, and recoverable activation.

## Security limitations

- Check-before-use race prevention is best-effort. A same-user attacker who can
  mutate staged bytes after the audit can invalidate the result. Activation
  must revalidate/protect installed files or use a safe immutable switch.
- Parent directories and Windows mount/junction policy must be controlled by
  the future staging orchestrator; the audit rejects detectable reparse points
  in the stage tree but is not a fully isolated OS sandbox.
- Signed **dependency locks** cannot substitute for specific signed PDS module
  release authorizations; do not grant module launch simply from this audit.
- Offline access to already-authorized installed modules must eventually depend
  on verified active receipts, not the expiration of online update metadata.

No `.venv`, teacher workspace, OneDrive classroom record, installed software,
network service, update command, release manifest, or production launcher is
modified or read by this implementation.
