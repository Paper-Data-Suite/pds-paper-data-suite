# Issue #49 — Slice 61: Explicit Offline Signed Staged-Candidate Audit

**Status:** opt-in diagnostic CLI, not active installation or launch eligibility.

## Purpose

Connect the existing Slice 58 signed catalog cache, Slice 59 metadata comparison,
and Slice 60 double-read publisher/pip/native stage correlation to a teacher-visible
`pds modules` operation. The normal `pds modules`, version-only preview, and
`pds launch` remain unchanged. Staged observations must not be represented as
an authenticated active environment or operational update.

## Invocation

```powershell
pds modules `
  --catalog-cache C:\PDS-Evidence\catalog.json `
  --trust-policy C:\PDS-Evidence\trust-policy.json `
  --trust-sha256 <independently-pinned-64-char-lowercase-hex> `
  --audit-staged-evidence C:\PDS-Evidence\candidate `
  --audit-stage-root C:\PDS-Software\candidate-venv `
  --audit-wheelhouse C:\PDS-Software\candidate-wheels
```

The directory `candidate` **must already exist** and contain exactly:

```
candidate/
  prepared.json
  registry-envelope.json
  lock-envelope.json
  native-envelope.json
  modules/
    <component-id>.json    # one per selected PDS publisher
```

Filenames are a fixed contract; module filenames come only from the root-signed
registry and the declared prepared wheel set. Unused or unexpected files are
refused rather than silently ignored. Paths cannot use symlink or Windows
reparse-point ancestors. Input files have strict size bounds and must be ordinary.
The lock and signed native envelope are independently audited by Slice 60; a
user-created unsigned manifest has no authority, irrespective of matching paths.

The SHA-256 pin is a caller-supplied string; *its independent provenance must be
established outside this command.* A user-controlled SHA-256 of a user-controlled
policy offers no trust. Production keys are not provisioned here.

## Verification order

1. Require all trust and audit options together; reject combination with the
   metadata-only comparison mode.
2. Validate filesystem paths and exact evidence directory inventory.
3. Read an independently digest-pinned public-key trust policy and revalidate the
   cached root-signed registry and delegated publisher records at current time.
4. Parse the bounded untrusted prepared record only to select expected evidence
   filenames for registered modules. It confers no release identity or approval.
5. Reject missing, extra, or unsafe publisher evidence files.
6. Invoke `inspect_catalog_bound_staged_bytes` with original signed envelopes.
   That helper re-verifies signatures and release identity, then performs twice
   the existing publisher-bound pip-file audit and root-signed native audit.
7. Return a deterministic, bounded report that explicitly states **NOT ACTIVE**,
   no execution authority, and no update/activation approval.

## Security and limits

No network or subprocess is started by the Slice 61 coordinator. No installation,
launch, local settings change, classroom data access, receipt persistence, witness
CAS, or activation is performed. Existing audit helpers are the security boundary
for the physical stage; same-user replacement after a read and the absence of a
protected active receipt prevent promotion to launch eligibility. Read-only
observation is not atomic authorization. Invalid input never falls back to the
historical Suite manifest or a version-only result.

## Next work

Protected active-state and activation receipts, independent checkpoint trust,
online/offline catalog provisioning and real single-module / whole-composition
update flow remain separate acceptance requirements.
