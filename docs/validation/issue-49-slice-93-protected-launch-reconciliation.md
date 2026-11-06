# Issue #49 — Slice 93 validation record

## Deliverable

Four additive files only: `evergreen_plan_launch_reconciliation.py`, its isolated regression module, this validation record, and the architecture note. Baseline: Slice 92 `792f079a16e1e967ae8b960762e3601c13b49799` on branch `49-evergreen-launch-and-supported-composition-upgrades`.

## Required Windows qualification

- Validate the exact source ZIP SHA-256 and per-member hashes before touching the repository.
- Refuse changed origin, branch, HEAD, remote branch, staged/tracked changes, unexpected untracked content, preexisting target files and symlink ancestors.
- Ruff import sort and formatting; read-only Ruff import/format/full lint; `mypy --strict` for the production module.
- Isolated `tests/test_issue49_slice93_launch_reconciliation.py`, then all `tests/test_issue49_slice*.py` and `tests/test_cli.py`; `pip check`.
- Recheck exact additive scope and remote HEAD before staging; stage only the four new members, require `diff --check`, commit/push only after every gate passes; verify resulting remote SHA and clean worktree. No reset, stash, force push, automatic retry or rollback.

## Regression scenarios

The isolated tests exercise the real protected chain through Slice 92 and the new read-only boundary. Required cases include successful independent double observation; lost launcher acknowledgment with no second launch; absent/unknown process observations without certification; reinspection without relaunch; changed process observation between reads; forged or missing persisted launch claim, upstream prelaunch record or caller-supplied claim; unauthorized service context; false process fences; forged process identities; signed-witness unavailability; reappearing capsule; changed installed successor; missing independent process reader; persisted SQLite certificate reopening; duplicate certification; corrupted stored certificate; and preexisting SQLite transaction.

## Acceptance limitation

The fixture's launcher/process service is synthetic. Regression qualification establishes correctness of the guarded Python coordinator and state machine **only**. It cannot prove actual privileged Windows process ownership, process-handle identity, signature validation, OS-level job isolation, service durability, or real start/crash outcomes. All such properties require independent production service and hostile-environment acceptance before enabling actual launch.

## Status

Package syntax and structural checks performed locally. Windows Ruff, mypy, isolated pytest, accumulated pytest, installed dependency consistency, commit and push: **pending execution in the trusted Windows checkout**.
