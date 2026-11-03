# Suite #49 — Slice 139: OS-parent deletion-right acceptance (ephemeral only)

**Exact parent:** `f65295c9d5d35389523076502671d994e95f770a`.

## Purpose and hard boundary

Slice 138 observed separate standard-user `DELETE` and immediate-parent
`FILE_DELETE_CHILD` denials inside a temporary sandbox. Those checks do not
address the sandbox's **external parent**: `%TEMP%` may be owned or writable by
an untrusted user. This slice tests a stronger, disposable root beneath
Windows' **OS-resolved CommonApplicationData** directory on a fresh, ephemeral
GitHub-hosted Windows Server runner. The new root's random name is prefixed
`pds-suite49-osparent-sbx-` and is **not** `Paper Data Suite` or the real
production PDS deployment tree. This non-production experiment is not a production installer and provides no production installer authority.

The test is intentionally **write-capable** only in the disposable hosted CI
environment. An elevated CI process creates five empty sample directories and
explicit protected DACLs allowing only SYSTEM and Administrators FullControl,
then adds one new standard user's traversal right to the root and Modify right
to a separate positive-control directory. A separate local ordinary Windows
account, authenticated by its process token SID, must pass the previously
qualified positive read/write control and four object-write denials and the
Slice 138 eight immediate deletion-related denials.

A second invocation under that same ordinary account requests only access
handles: `DELETE` on the **sandbox root** and `FILE_DELETE_CHILD` on the
OS-resolved CommonApplicationData **parent**. Both must return Win32
`ERROR_ACCESS_DENIED` (5). It first requires `DELETE` on a user-owned positive
control file to succeed; otherwise a broken access-check mechanism could falsely
report protective denials. Neither probe calls DeleteFile, RemoveDirectory,
`Remove-Item`, or a service-control API. Access checks do not exercise deletion.

The administrator-side harness compares the parent's security descriptor before
and after, confirms no sandbox directory became a reparse point, validates the
same ordinary SID across both proofs, and rejects any inconsistent or
installation-authorizing evidence. The source runner **never** executes these
account, filesystem, or ACL operations on a teacher workstation. The separate
CI workflow must fail, not skip, if elevation, secondary account, positive
control, or the ten relevant denial checks are unavailable.

## CI-only acceptance

[The dedicated GitHub workflow](../../.github/workflows/issue49-sandbox-os-parent-denial.yml)
invokes `qualify_sandbox_os_parent_ci.ps1` on a disposable `windows-2022` host.
Only the GitHub-hosted CI machine may create this OS-parent test. The workflow
needs a distinct local account and an elevated token; no username/password is
accepted from the teacher or displayed as output. Direct invocation outside
hosted Windows CI refuses before any write. A genuine missing or unexpected
access right fails the CI run; no synthetic approval fallback is allowed.

**No automatic deletion, cleanup, rollback, or service registration** occurs.
All test state is discarded with the ephemeral runner. There is no mutation of
`ProgramData\Paper Data Suite`, no production publisher pin, active receipt,
service registration, deployment, or classroom-data write.

## What this does not establish

A successful result tests one actual Windows Server CI image's parent ACL under
one generated local ordinary-user token. It does **not authenticate a real**
school administrator, prove OS-root custody on a teacher workstation,
protect against privileged attacks or reparse races in all ancestors,
authenticate signed artifacts, establish rollback-resistant state, or attest
an independently installed PDS service. Output retains
`os_parent_production_custody_verified=false` and
`authorized_to_install=false`; production installation authority remains absent.
