# Suite #49 — Slice 132: Fail-closed teacher-token SCM denial observation

**Parent:** `db3014984f2e8ee6477dc38053f50275343cb553`.

## Scope and security rationale

Slice 131 obtains individual service handles to observe eight current-token SCM
access decisions, but cannot identify whether its caller represents an ordinary
teacher or a privileged account. Slice 132 introduces a separate C++17 native
read-only witness that checks the **current process primary token** first, then
queries those eight service rights on fixed provisional `PaperDataSuiteService`.

A UAC-filtered administrator account is **not** an ordinary teacher. The token
check requires non-elevation, `TokenElevationTypeDefault`, medium integrity,
and **no Administrators SID in any token group** (including deny-only groups).
Unexpected token queries refuse. Only then does the probe request
`SERVICE_QUERY_STATUS` to establish presence, followed by eight individual
`OpenServiceW` rights checks. It closes all handles immediately; granting a
handle never causes service control, configuration, or deletion.

Every sensitive service right must be denied to produce
`ALL_EIGHT_SCM_DENIALS_OBSERVED_UNATTESTED`. A service absent from CI produces
`SERVICE_NOT_INSTALLED_NO_TEACHER_ACCEPTANCE`. Any grant, unexpected error,
nonordinary token or missing service refuses; these states must **not** be
reported as installed-service negative-security acceptance. Unknown arguments,
including `--accept`, are rejected before inspection.

## Independent identity and deployment obligations

The current process can inspect only its own primary token, not independently
authenticate an ordinary teacher principal. Even all eight observed denials are
**not production acceptance**: independent account verification, signed and
protected installation identity, service process SID/token, effective file and
SCM permissions, protected publisher-pin antirollback, and receipt/transaction
recovery are still required. The executable reports
`independent_teacher_identity_attested=false` and
`installed_service_identity_verified=false` in every result.

This slice has **no provisioning**, **no installation**, **no protected writes**,
no service registration or control, no impersonation, no privilege elevation,
and no receipt or launch authority. A caller-owned executable's JSON cannot be
used as an installer admission token.

## Qualification

The existing Windows workflow must compile the new target on **x64** and
**ARM64**, verify its PE machine type, and execute both normal and explicit
argument-refusal paths on genuine x64 and native ARM64 CPUs. ARM64 cross-build
alone never counts as runtime acceptance. CI may legitimately run as an admin
and/or encounter the provisional service absent. Those no-authority refusals
are accepted as diagnostic correctness, not successful teacher acceptance.

To complete real ordinary teacher negative acceptance later, an independently
administered installer must first provision the actual signed and protected
service, and an external administrator must verify that a separately authenticated ordinary teacher account executed the native denial check on
that installed machine. The current diagnostic may provide supporting
read-only evidence only; it cannot certify its own signer or identity.
