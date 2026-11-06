# Issue #49 — Slice 129: Native administrator-token observation preflight

**Parent:** `41edc472a0f60032de7d69493287e24712fb503d`.

## Security goal and precise boundary

This slice introduces a standalone read-only Win32 diagnostic for the **current process primary token**. It observes whether the operating system reports token elevation, a high-or-higher integrity level, and enabled membership in Builtin Administrators (through a duplicated identification-level impersonation token). The executable produces only fixed-status JSON and a fixed no-authority line; it does not return user identities, SIDs, passwords, keys, or private evidence. No caller path, proposed policy bytes, or privilege escalation option is accepted.

Observing an administrator-looking primary token is **not independent administrator authentication**. The program is caller-owned and unsigned; the observation cannot establish an independently administered service identity, externally approved operator, protected provisioning, immutable policy or antirollback witness. There is **no provisioning**, **no protected writes**, **no rollback protection**, **no installation**, no receipt, no launch permission, and no change to ProgramData. The executable explicitly refuses `--provision` and any other argument with no side effects. Exit 1 means signals unavailable/insufficient; exit 2 means observational signals all present or unsupported argument refused. Neither exit means success or authorization.

## Native acceptance

CMake builds `pds_windows_pin_admin_preflight` as separate C++17 /W4 /WX /permissive- /sdl native code. The existing Windows build gate verifies PE architecture for x64 and ARM64, executes the probe on a matching native CPU, asserts all authorization/provisioning/rollback flags false, and explicitly tests refusal of `--provision`. The x64 CI runtime and native ARM64 CI runtime are both required; ARM64 cross-build alone does not suffice. Build outputs stay in disposable external temp locations. The source-contract Python tests are not a substitute for these Windows native tests.

## Subsequent work

A separately administered, signed, immutable installer or service must eventually establish independently authenticated administrator approval, durable protected publisher-pin storage, trust-root provenance, antirollback custody, and crash consistency. No production installer operation may consume this diagnostic's JSON as an authorization token. Until those independent proofs exist, refusal is mandatory.
