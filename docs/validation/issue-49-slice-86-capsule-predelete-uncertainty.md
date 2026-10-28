# Issue #49 — Slice 86 validation and Windows qualification

## Delivered files (additive only)

- `paper_data_suite/evergreen_plan_capsule_predelete_uncertainty.py`
- `tests/test_issue49_slice86_capsule_predelete_uncertainty.py`
- `docs/architecture/issue-49-capsule-predelete-uncertainty.md`
- `docs/validation/issue-49-slice-86-capsule-predelete-uncertainty.md`

## Required exact baseline

- Repository: `Paper-Data-Suite/pds-paper-data-suite`
- Branch: `49-evergreen-launch-and-supported-composition-upgrades`
- Parent: `7090c660a5d9a51416b017e243b3971c0925e68c`
- Clean index/worktree and absent four target paths; no reset, stash, overwrite, force push or automatic retry.

## Acceptance gates

1. Verify the two archive SHA-256 digests, the four immutable source-member digests, Python AST and exact Git identity/remote baseline.
2. Ruff import sorting, formatting, lint, and strict mypy on the production module.
3. Isolated Slice 86 regression (real Slice 78–85 SQLite + simulated signed Ed25519 witness): append-once exact marker, no file mutation, reopened database, forged preflight fields, unprivileged actors, absent protected convergence/preflight, changed/missing capsule, loss of capsule locks, signed-head/key loss, predecessor receipt, writer-in-flight, physical drift, corrupt database row, and invalid transaction.
4. Run all accumulated Issue #49 and `tests/test_cli.py` regressions, then `pip check`.
5. Recheck four-file additive scope and exact Git/remote baseline before committing exactly four files and pushing normally. Any failure halts without rollback or automatic retry.

## Key limits

Windows qualification is pending until the guarded runner completes on the actual repository. Synthetic physical callbacks are **not** evidence of an operating-system privileged deletion service. The Slice 86 feature NEVER deletes the capsule, changes an active receipt, grants launcher readiness, or resolves unknown post-crash filesystem state. A later deletion implementation requires separate production acceptance and independent post-delete reconciliation.
