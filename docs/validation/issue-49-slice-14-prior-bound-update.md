# Issue #49 — Slice 14 validation

Branch: `49-evergreen-launch-and-supported-composition-upgrades`
Base commit: `6ec9065` (exact SHA enforced by runner)

## Additive scope

- `paper_data_suite/evergreen_prior_update.py`
- `tests/test_issue49_slice14_prior_update.py`
- `docs/architecture/issue-49-prior-bound-update-preflight.md`
- `docs/validation/issue-49-slice-14-prior-bound-update.md`

No modification of existing production files, entry points, package dependencies, or historical release data.

## Local functional gate

All Slice 1–14 tests passed locally using deterministic synthetic signing keys and fixtures: 404 tests, including 19 Slice 14 tests. Local Linux symlink tests can execute; Windows may report pre-existing permission-related skips. Final Ruff and strict mypy must run through the bundled Windows runner before a commit.

Slice 14 tests cover real signed candidate + previous bytes; prior transaction and generation binding; read-only/no-classroom-data behavior; journal hash substitution, missing prior binding, stale revision, wrong transaction, wrong stage/wheelhouse, changed prior or candidate native executable, changed signed envelopes, interrupted selection recovery, expired metadata, forged caller evidence, unsafe overlapping directories, unarmed-only phase, malformed clock/trust, and boolean/invalid revisions.

## Windows runner gates

1. Verify exact source branch and committed Slice 13 base; require a clean tree.
2. Check exact SHA-256 of each bundled additive file; prohibit replacing existing files.
3. Ruff import auto-sort, format, lint and formatting check on only the new Python files.
4. Strict mypy on the new module.
5. One focused pytest run across Slices 1–14; do not run duplicate dirty and clean full suites.
6. `python -m pip check`, staged `git diff --cached --check`, exact staged path list, no unstaged tracked changes.
7. Only after success, commit and push the exact Slice 14 scope. A failure leaves applied files uncommitted.

## Acceptance limitation

This is a read-only two-sided software-byte preflight. It does not certify historical activation, persist protected receipts, or authorize normal launch. Final Windows test count and skips are determined by the actual runner output, not inferred from the local environment.
