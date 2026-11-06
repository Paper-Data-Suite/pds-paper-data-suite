# Issue #49 — Slice 83 validation and release gates

Scope: exactly four additive files at parent commit `849d965e57a61bee97dbb29ccfe039bd9c010add` on branch `49-evergreen-launch-and-supported-composition-upgrades`. No modification to existing modules, migrations, endpoints, launchers, journals or teacher-local state.

## Required execution gates

- Verify exact repository, origin, baseline HEAD, synced remote and completely clean additive scope; verify both ZIP digests and exact per-file source hashes.
- Ruff imports, formatting and lint for the new production module and regression test; strict mypy for production.
- Isolated Slice 83 tests, including complete Slice 78–82 protected service setup, one-shot claim preceding file callback, preserved capsule, reopened SQLite, replay refusal, forged marker and authorization refusal, changed predecessor/capsule, false-success callback, thrown/lost writer ACK, lost post-write readback, changed capsule, offline signed witness and corrupt durable row.
- Entire accumulated `test_issue49_slice*.py` inventory and `tests/test_cli.py`, plus `pip check`.
- Recheck exact four-file untracked scope, baseline and remote before adding, committing and pushing. Confirm final remote SHA and clean worktree. On any failure, **stop without reset, stash, rollback or retry**; leave the exact four files for a guarded continuation.

## Current qualification status

- Local Python AST/bytecode compilation: passed.
- Local simulated protected SQLite claim/readback/replay tests: passed (not real repository qualification).
- Full Windows Ruff, mypy and pytest: **pending independently observed Windows runner output**.
- Commit and push: **pending**.

### Non-qualification warning

`ProtectedLocalReceiptDispatcher.dispatch_once()` accepts the privileged file writer as a protocol callback. That interface does not establish actor isolation, a real OS file lock, safe ordinary-file handles or crash-safe replace. This release is a **guarded service integration boundary**, not proof that a complete privileged Windows file writer exists. Deployment remains blocked until a separately provisioned implementation is verified under the actual filesystem and recovery failure model.
