# Issue #49 Slice 33 — External checkpoint witness verification

- Exact parent commit: `12bfc1b84e09859cf1418282af983ad587726ef6`.
- Branch: `49-evergreen-launch-and-supported-composition-upgrades`.
- Four additive files; no existing production Python, CLI, launch, workspace,
  provider, installation, or update implementation changes.
- Local focused acceptance: 23 Slice 33 tests passed with fixture-only Ed25519
  signing keys; the complete local historical suite was not run here.
- Positive cases: signed, fresh genesis statement; signed successor statement
  with exact predecessor; transport-issued fresh challenge and signed response.
- Negative cases: wrong witness/key/installation/challenge/head/generation;
  replay under another challenge; expired/future/excessive lease; revision
  rollback; missing witness; failing transport; duplicate JSON, noncanonical
  payload and unexpected fields.
- Windows acceptance: Ruff imports and formatting, Ruff lint, strict mypy,
  all `test_issue49_slice*.py` tests (expected 34 test files), pip dependency
  check, exact staged scope, whitespace, clean tracked diff, commit/push.
- No claim that signing a fresh reply provides an OS-protected store, or that
  this mechanism authorizes launch. No background network access is added.
