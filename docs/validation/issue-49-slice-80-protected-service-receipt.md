# Issue #49 — Slice 80: protected service receipt qualification

## Four additive files

- `paper_data_suite/evergreen_plan_protected_receipt.py` — service-side once-only SQLite receipt recording and integrity inspection; no teacher-local filesystem mutation.
- `tests/test_issue49_slice80_plan_protected_receipt.py` — real SQLite fixture, synthetic Ed25519 witness, authenticated-operation doubles, durable reopening, duplicate refusal, forged preclaim/reservation, missing rows, corrupt storage, lost authority, invalid signed witness, pending-capsule preservation.
- `docs/architecture/issue-49-protected-service-receipt.md` — trust, atomicity and recovery boundaries.
- This validation record.

## Qualification order

1. Verify source-only archive and file SHA-256, Python syntax, Git origin/branch, exact Slice-79 baseline `c037ee05d53ebdd35a4a1e2192716ad844fc3e6a`, remote head and clean worktree. Refuse target overwrites and symlink ancestors.
2. Write the four additive files, perform Ruff import/format normalization, then read-only Ruff lint/import/format and strict mypy on the production module.
3. Run the Slice-80 isolated suite; run all accumulated `test_issue49_slice*.py` tests and `tests/test_cli.py`, then `pip check`.
4. Confirm exact additive-only status; stage only those four paths, verify staged add-only list and whitespace, commit only on full qualification and push normally after another remote comparison. Never automatically retry failed tests, reset, stash, force push or rollback.

## Acceptance limitations

The local authoring environment does not include the full installed Suite test tree or Windows toolchain. Full Windows Ruff, strict mypy, isolated tests, accumulated pytest, dependency and Git gates are **pending** until the guarded runner succeeds. Tests cannot establish a real independently administered service, physical OS isolation, cross-file crash recovery, teacher-local active-receipt publication, capsule cleanup or launch readiness. The expected Windows symlink skips are environmental, not blanket acceptance of other failures.
