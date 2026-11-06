# Issue #49 Slice 88 qualification record — pending Windows acceptance

## Proposed additive scope

- `paper_data_suite/evergreen_plan_capsule_postdelete_reconciliation.py`
- `tests/test_issue49_slice88_capsule_postdelete_reconciliation.py`
- `docs/architecture/issue-49-capsule-postdelete-reconciliation.md`
- `docs/validation/issue-49-slice-88-capsule-postdelete-reconciliation.md`

Baseline: branch `49-evergreen-launch-and-supported-composition-upgrades` at `b6e7b6e1731b0e3b4ec8cedce90b815883465b70`, both HEAD and remote, fully clean before application. Never overwrite existing paths.

## Mandatory runtime qualification

The guarded Windows runner uses installed venv Python to run Ruff import sorting, formatting and full lint; `mypy --strict` for the production module; the isolated Slice 88 regression; all accumulated Issue #49 regressions plus `tests/test_cli.py`; and `pip check`. Commit/push is guarded by exact four-file additive scope, unchanged HEAD, and unchanged remote.

The tests use the real protected service SQLite reservation-to-dispatch chain and signed Ed25519 witness protocol with synthetic independent readers. They cover one-shot certification, read-only classification, retained original capsule, unknown capsule, signed witness mismatch, missing/falsified protected chain, OS delete termination/fence refusal, mistaken capsule/target/receipt identity, changed samples, reopened SQLite durability, replays, invalid stored certificate, unauthorized service actors and absence of any delete/launch method.

## Local vs Windows evidence

Local checks can verify Python compilation, ZIP integrity, schema alignment, synthetic policy/SQLite checks and runner refusal. They **cannot** establish Windows ACL/fence, privileged service identity, crash-safe deletion, actual filesystem directory fsync, or the complete regression gates. The qualification record becomes acceptance evidence only when Windows console output demonstrates every gate and exact commit/push plus clean worktree. No automatic retry, rollback, reset, stash or force push.
