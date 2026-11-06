# Suite #49 — Slice 131: Native SCM current-token access observation

**Parent:** `7a4df6d05ffb540ef0b4691cebc0ef410311d02d`.

## Exact security purpose

Slice 130 inspects the provisional `PaperDataSuiteService` service-object
owner/DACL and configured service SID type. Slice 131 instead asks Windows
Service Control Manager to evaluate eight individual access requests against
the **current process** token. It opens and immediately closes service handles;
requests for `SERVICE_CHANGE_CONFIG`, `DELETE`, `WRITE_DAC`, `WRITE_OWNER`,
`SERVICE_START`, `SERVICE_STOP`, `SERVICE_PAUSE_CONTINUE`, and
`SERVICE_USER_DEFINED_CONTROL` never result in the corresponding operation.
`ERROR_ACCESS_DENIED` is recorded as a denial; unexpected errors refuse the
observation. The service name and computer are fixed. No arbitrary paths,
security principals or user-supplied service identifiers are accepted.

A provisional service absent from CI is expected to report
`PROVISIONAL_SERVICE_NOT_INSTALLED_NO_AUTHORITY`. For an existing service,
`SCM_CURRENT_TOKEN_ACCESS_OBSERVED_UNVERIFIED` means the current token's eight
open-rights checks completed. It does **not** mean the service is protected,
that denial occurred, or that the token belongs to an ordinary teacher.
The test process is **not authenticated** as an independent teacher account.
`independent_teacher_token_verified`, `service_identity_verified`,
`authorized_to_provision`, and `authorized_to_install` always remain false.

## Native qualification and limits

The existing Windows workflow compiles the C++17 executable with `/W4 /WX`
for **x64** and **ARM64**, verifies the actual PE machine type, and executes
both observational and `--configure` refusal paths on matching CPUs. The x64
and genuine ARM64 runtime jobs must pass. No privileged operation is ever
attempted; only handle acquisition checks effective open rights. The ARM64
cross-build on an x64 host cannot be counted as ARM64 runtime qualification.

This read-only diagnostic has **no provisioning**, **no installation**,
**no protected writes**, no service registration or control, and no receipt
or composition activation. It is an unsigned caller-owned observation and
cannot authorize privileged installation. CI has no installed provisional
service; its absence is a negative baseline, not installed-machine security
acceptance.

## Mandatory separate acceptance before deployment

A separately administered, protected and signed real service/installer must
first exist. The corresponding effective-access checks must then run as a
**real ordinary teacher** account against that actual service and must deny
unauthorized configuration, deletion, owner/DACL change and control rights.
The future process must independently establish user identity, executable
custody, authenticated publisher pin, protected checkpoint antirollback,
service process token/SID and crash-safe protected receipts. A local command's
JSON, even when accurate, is never an admission token.
