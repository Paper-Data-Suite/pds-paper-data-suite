# Suite #49 — Slice 137: independent ordinary-token denial in disposable Windows CI

**Exact parent:** `cc3c2cc73122afb26c63433b4fc3c41cdad962b8`.

## Purpose and real Windows negative-security test

Slice 136 created five administrator/SYSTEM-only ACL directories in a random
Windows temporary root and independently checked the descriptors. Slice 137
adds a separate, newly created **local standard user** on an **ephemeral hosted
Windows CI runner**. It requires that actual account to read a prepared control
file and create/read a second file inside an explicitly authorized control
child, then fail with `UnauthorizedAccessException` on writes into four
existing protected application/state directories. The administrator checks
that no protected write-test file exists and the protected ACEs remain the
original two trusted principals. Both the positive and negative controls must
succeed: merely failing to traverse the original user's temporary directory
is not accepted as a successful negative test.

No password, username, or account SID is printed. The CI controller generates
a random local username and random password in memory and checks local
Administrators membership. The child script verifies its actual Windows
identity SID and the absence of enabled Administrators membership. No
caller-supplied service name, target production directory, or credentials are
accepted. Only a known random sandbox root produced by Slice 136 may be used.

## Safety boundary

The new CI controller refuses execution unless it observes Windows and the
`GITHUB_ACTIONS=true`, `RUNNER_OS=Windows`, and
`RUNNER_ENVIRONMENT=github-hosted` environment labels. These labels are an
accident-prevention guard, **not** an authenticated security boundary; neither
script is appropriate for running on a school/work computer. A standard source
qualification, testing, commit or push **never calls the account-creation or
sandbox-write code**. The workflow runs only on an ephemeral `windows-2022`
runner. The random local account and disposable temporary sandbox are retained
until the hosted runner is discarded; there is no automatic deletion, service
registration, production ACL mutation, provisioning, receipt operation, or
installer execution.

There is an actual write attempt into each protected disposable directory;
if it unexpectedly succeeds, the job fails rather than hiding the failure.
These write attempts occur **only in ephemeral test directories**.

## Limits and future obligations

This is a separate ordinary-user access check against a **disposable
sandbox**, not installed-machine acceptance of a provisioned service. The
sandbox's ancestor directories and parent-delete rights are not independently
protected. A new local user is not a school teacher account, and this job does
not authenticate the administrator, protect an executable or publisher pin,
validate service SID, establish rollback-resistant witness custody, or
authorize installation. A successful CI test is evidence for sandbox effective
ACL denial under a real nonadministrator account, **not production authority**.

Future work must address protected parent deletion/replace resistance, service
identity, signed and pinned release installation, durable recovery, and a real
ordinary-user test on an independently administered installed machine.
