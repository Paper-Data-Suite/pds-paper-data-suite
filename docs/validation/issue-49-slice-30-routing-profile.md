# Issue #49 — Slice 30 Acceptance: Staged Core PDS2 Routing Profile

Base branch: `49-evergreen-launch-and-supported-composition-upgrades`
Exact parent commit: `33de22b9a5575cf9419c0d6337b7bac4779d84af`
Scope: one additive module, one regression test file, architecture and validation documentation. No production wiring.

## Qualification

- Require explicit execution approval before any import or factory call; reject invalid timeouts and locations.
- Reauthenticate the declared provider and signed real-pip installation before and after the contract subprocess, including independently signed native bytes.
- Verify installed `pds-core` owns the public `pds_core.module_profiles` validator and that the declared provider belongs to its publisher-authenticated wheel.
- Validate the returned `ModuleProfile` and the exact current Core routing version, PDS2 QR schema, registration schema `1`, and `active` status without invoking callbacks.
- Preserve `NOT_DECLARED` for optional absent routing profiles; reject wrong module identity, provider exceptions, missing Core contract, and post-execution drift.
- Use a disposable directory under managed software and leave a separately located classroom workspace untouched.

## Local tests

- Slice 30 isolated: **18 passed**.
- Affected Slice 27–30 regression set: **71 passed**.
- A reconstructed complete local suite timed out at 42%; **not** counted as a full pass. The Windows runner performs full focused qualification before it will commit.
- The genuine offline-pip test demonstrates an authenticated/importable routing declaration is rejected without installed Core's public routing API.

## Windows acceptance and release guard

`run_slice30.ps1` checks exact parent commit and branch, clean tracked/staged/untracked state, exact payload hashes, additive path absence, Ruff import sorting/format/lint, strict mypy, all issue #49 `test_issue49_slice*.py` files, installed dependency consistency, staged whitespace and exact file scope. It commits and pushes only after those gates pass.

Expected Windows symlink skips are permission-dependent and do not represent passed execution of the skipped cases. Investigate any test, lint, typing or file-scope failure; never bypass gates to commit.

**Result cannot authorize production launch, integration execution, route dispatch, update activation or persisted active-install receipts.**
