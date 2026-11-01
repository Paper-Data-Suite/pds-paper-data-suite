# Suite #49 — Slice 109: Windows service identity inventory (read-only)

## Context

Slices 106–108 establish directory-level *observation* and a separate
administrator provisioning handoff. On the Windows pilot, both system parents
passed the strict/parent ACL checks; all four named PDS child directories were
absent, and the reviewer correctly exited `2` without writes.

A future protected installer/service must not derive its authority from those
observations, a teacher CLI flag, `StartName`/`PathName` strings, package
metadata, or any user-writable receipt. Slice 109 introduces a **separate**
service-configuration observer, not a service installer or production gate.

## Read-only service identity inventory

Run:

```powershell
.\.venv\Scripts\python.exe -m paper_data_suite.evergreen_windows_service_identity_preflight
```

The inventory queries the Windows Service Control Manager through the
read-only `Get-CimInstance Win32_Service` interface using exactly one fixed,
**provisional** service name: `PaperDataSuiteService`. It does not accept
user-defined service names, executable paths, accounts, or command templates.
The proposed name is not an approved deployment identity and must be reconciled
with the independent installer design before any provisioning.

Return status and exit code:

| Status | Exit | Meaning |
| --- | ---: | --- |
| `SERVICE_NOT_INSTALLED` | 2 | No SCM entry for the provisional service name; expected before deployment |
| `SERVICE_METADATA_OBSERVED_UNVERIFIED` | 0 | A record exists; its configuration is **not authenticated** |
| `REFUSED` | 1 | SCM query failed, was ambiguous, or produced invalid evidence |

Observed metadata is deliberately minimized. The command reports a recognized
start mode/state and *category* of configured logon account. It does not emit
raw account names, registered executable paths, or full process command lines.
It observes but does not validate the path, service SID mode, actual process
token, SCM DACL, file ownership, executable bytes/signature, protected active
receipt head, or CAS/witness continuity. `production_authority` and
`active_receipt_authority` remain `false` in every successful observation.

## Separate administrative proof still required

Before a production service or installer is authorized, establish, independently:

1. Trusted administrative provisioning of four protected PDS directories,
   including owner, DACL and effective write-denial acceptance for ordinary users.
2. A reviewed fixed service identifier and its *real* Windows service SID,
   isolated account/token, explicit SCM DACL and controlled service lifecycle.
3. Pinned executable installation and verified file-level integrity from
   authenticated wheel/artifact provenance, not just a claimed `PathName`.
4. Privately owned service state and protected receipt-head storage with a
   verifiable transaction/witness update and crash-recovery protocol.
5. Installation-time and negative teacher-token acceptance demonstrating that
   ordinary teacher processes cannot reconfigure the service, alter executable
   bytes, replace receipts or cross the service privilege boundary.

No production installer, service creation, service startup, elevation, ACL
mutation, package write, launch grant or workspace change is part of this
slice. Slices 104–108 remain untouched. Existing Core #238–244 and Suite
#51–54 teacher-experience and workspace work are separate.

## Qualification

Ruff lint/format, strict mypy, synthetic SCM parsing/command tests, affected
Slices 104–109 regressions, `pip check`, then the real Windows **read-only**
service query. This is not installed-wheel, service-token, or production
activation qualification.
