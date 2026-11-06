# Issue #49 Slice 91 validation — protected prelaunch uncertainty

## Delivered files

- `paper_data_suite/evergreen_plan_prelaunch_uncertainty.py` — the append-once prelaunch marker coordinator (no process launcher).
- `tests/test_issue49_slice91_prelaunch_uncertainty.py` — end-to-end protected SQLite, signed witness, runtime and physical readback regression tests using the established Slice 78–90 fixture chain.
- This validation note and the accompanying architecture note.

## Required Windows qualification

The guarded runner requires an entirely clean checkout of `Paper-Data-Suite/pds-paper-data-suite`, the exact Issue #49 branch and remote at the fully qualified Slice 90 commit `3229a74728d97106ca97472c5e6f14cfdcc57213`. It verifies the four exact ZIP members and SHA-256 digests and refuses overwriting a pre-existing file. It then executes Ruff import sorting/formatting, read-only Ruff checks, strict mypy of the new production module, isolated Slice 91 pytest, the complete accumulated Issue #49 and CLI regression tests, and `pip check`.

If any gate fails, leave the four files untracked and refuse commit/push; no reset, stash, rollback, automatic retry, force push, or overwrite. After complete success, stage exactly four additive files, commit, push, verify remote equality, and require a clean worktree.

## Negative and persistence cases

Tests cover one-shot arming and persisted readback; replay refusal before any additional probes; forged or missing launch-intent and readiness records; forged authority and digests; unauthorized actor; vanished or reappearing capsule; changed installed successor; incomplete deletion termination or launcher fences; changed executable identity; invalid witness key; independent callback failure; changed evidence between samples; nested transaction refusal; malformed SQLite rows; reopened protected SQLite; and absence of any launch or filesystem mutation APIs.

## Limitations

These tests are synthetic contract tests, not a privileged Windows service evaluation. No process execution is implemented or authorized. The only permitted result is a protected non-dispatching uncertainty marker. Future execution requires a separately reviewed process-dispatch boundary, physical provenance, OS-level exclusive fencing, crash/durability tests, and explicit production acceptance.
