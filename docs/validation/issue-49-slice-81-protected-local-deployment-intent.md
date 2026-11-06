# Issue #49 Slice 81 — Validation and safety record

## Exact additive scope

- `paper_data_suite/evergreen_plan_local_deployment_intent.py`: independently controlled one-shot local receipt deployment *intent*; no local filesystem writes.
- `tests/test_issue49_slice81_local_deployment_intent.py`: real Slice 78–80 SQLite and synthetic Ed25519 witness scenarios. Covers successful preflight, retained predecessor/capsule, exact persisted records, restart/replay, actor refusal, wrong identities and target pins, changed local predecessor, revoked service evidence, missing protected rows, prior signed head, witness outage, invalid pins, transaction refusal and corrupted rows.
- `docs/architecture/issue-49-protected-local-deployment-intent.md`: reasoning, trust boundary, crash states and next physical-writer boundary.
- This file.

## Guarded Windows qualification

1. Verify the original four-member source ZIP and each member SHA-256, exact Slice 80 predecessor Git HEAD `be723ba5338f5880707289e18e0a74c70e40ed29`, branch, remote URL/head, clean worktree, no existing target paths and no symlink ancestors.
2. Write only four new paths. Run Ruff import sorting and formatting correction, followed by read-only Ruff checks and strict mypy for the new production module.
3. Run isolated Slice 81 tests, complete accumulated Issue #49 and CLI tests, and `pip check`. A new failure must stop before commit; no reset, stash, automatic rerun or unbounded rollback.
4. Reverify no tracked/staged changes and exact four-file scope. Commit and push only after all gates succeed, then independently verify remote commit and clean worktree.

## Qualification limitations

Packaging checks and isolated synthetic dependency smoke tests are not substitutes for installed-repository Windows acceptance. Real role-separated service administration, protected OS filesystem custody, physical package readback, hardening against symlinks/reparse points, crash recovery of local replacement, capsule clearance and launcher readiness remain **unimplemented**. The intent must not be represented as local publication or activation.
