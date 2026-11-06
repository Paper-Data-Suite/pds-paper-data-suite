# Suite #49 — Slice 138: disposable parent-delete effective-access checks

**Exact parent:** `ceb3750bd1b87c18bec964a3f5661a1c416f28e6`.

## Why it matters

Slice 137 qualified independent second-account sandbox write denials in the
Windows 2022 hosted runner. A protected object's DACL is not alone enough to
establish that an ordinary user cannot delete it: the Windows file-deletion
model also considers `FILE_DELETE_CHILD` rights on the parent directory.
Slice 138 adds a **non-destructive handle-access test** under the same freshly
created ordinary local account. It checks `DELETE` on four protected sandbox
directories and `FILE_DELETE_CHILD` on the relevant immediate parent for each.
These checks are separate from the four existing `CreateNew` write denials.

An explicit positive-control `DELETE` access open against the ordinary user's
own permitted test file must succeed before any eight negative rights checks
are accepted. This prevents the testing harness from claiming all-denied
merely because the access-query code never works. All object and parent checks
must fail with Win32 `ERROR_ACCESS_DENIED` (5); an unexpected error or any
granted handle refuses the entire CI acceptance test. The access helper uses
`CreateFileW`, `OPEN_EXISTING`, `FILE_FLAG_BACKUP_SEMANTICS` and full sharing
but **does not call `DeleteFile`, `RemoveDirectory`, `Remove-Item` or exercise
any granted DELETE right**. All handles are immediately released.

## Scope and verification

The same CI workflow `issue49-sandbox-ordinary-user-denial.yml` runs the
existing administrator-owned, randomly generated, temporary sandbox and
standard-user negative process. The read-only source qualification runner
never creates accounts, runs the Windows helper, or changes any ACL. The parent
CI script verifies the child process's new strict fields, retains the prior
positive read/write and four write-denial checks, verifies the positive file
still has its exact original contents, and rechecks that the protected DACLs
have not changed.

This is evidence about a disposable test account and its specific sandbox
only. It does **not** prove protection of the sandbox *root* from a principal
with control over the external temporary **parent**. Parent deletion rights
at the OS deployment roots, reparse-race custody, independently authenticated
administrator consent, protected publisher trust, service SID/SCM custody,
rollback-resistant checkpoint/receipt state, and signed production artifacts
are entirely outstanding. No production installation, service registration,
receipt publication or activation authority is implied or emitted.

## Acceptance

- Source: Ruff, strict mypy and cumulative targeted pytest are mandatory.
- Windows CI: ordinary-account positive read/write and positive DELETE-handle
  open must succeed, four write attempts must be denied, eight non-destructive
  deletion-right opens must report `ERROR_ACCESS_DENIED`, and sandbox ACLs
  must remain intact. No missing-account/test skip is accepted.
- All passes are `NO_PRODUCTION_INSTALLER_PROVISIONING_SERVICE_OR_RECEIPT_AUTHORITY`.
- Windows CI must pass before Slice 138 is considered accepted.
