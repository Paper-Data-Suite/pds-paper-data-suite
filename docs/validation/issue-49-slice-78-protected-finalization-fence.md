# Issue #49 — Slice 78 validation plan

## Exact additive scope

- `paper_data_suite/evergreen_plan_finalization_fence.py`: independent SQLite reservation with canonical witness request binding; no installed-local writes.
- `tests/test_issue49_slice78_protected_finalization_fence.py`: synthetic predecessor/successor receipts, isolated SQLite store and independent callback doubles; one-shot admission, restart, refusal, replay and corruption checks.
- `docs/architecture/issue-49-protected-finalization-fence.md`: explicit independent authority and durable state protocol.
- This validation record.

## Guarded Windows acceptance

1. Verify origin `https://github.com/Paper-Data-Suite/pds-paper-data-suite.git`, exact `49-evergreen-launch-and-supported-composition-upgrades` branch, exact Slice 77 parent SHA `b7552935a4630c1a396ace4be344b7f4c9e3a1de`, identical remote ref, clean worktree and index. Refuse existing targets or symlink ancestors.
2. Verify source ZIP digest, exact four-file names, per-member SHA-256, regular-file entries, syntax and size bounds before applying. Write only four new files.
3. Run Ruff import fix then formatting and read-only Ruff checks, strict mypy on the new production file, isolated Slice 78 tests, all accumulated Issue #49 regressions and CLI tests, and `pip check`.
4. Confirm no tracked changes, staged files or extra untracked files. Stage exactly the four new files, verify add-only scope and whitespace; commit and push only after all checks pass. Never reset, stash, force push, repair failing tests automatically, roll back a witness CAS, or delete a pending recovery capsule.

## Required negative cases

- forged or noncanonical review/request; wrong installation, transaction, SHA-256, successor generation or witness revision;
- service evidence mismatch in any protected digest; absent or false independently stopped writers, installed-byte reaudit or operator consent;
- missing or denying service identity/authorization, broken evidence provider;
- duplicate admission with identical bytes or changed request; durable restart/reopened DB;
- corrupted durable rows, SQLite transaction conflict and unexpected errors;
- no classroom path changes and no receipt publication, launch, capsule-clear or rollback methods.

## Remaining limitations

The synthetic local tests do not demonstrate independently administered OS permissions, persistent production SQLite durability, valid networked attestation, global writer quiescence, actual protected active receipt publication, end-to-end Windows wheel/launcher functionality, or a complete production update. Full Windows installed-repository qualification is **pending** until the guarded runner succeeds. Existing unprivileged Windows symlink skips may remain; investigate any new failure before commit.
