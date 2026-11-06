# Issue #49 — Slice 96 validation and handoff

## Parent baseline

- Required branch: `49-evergreen-launch-and-supported-composition-upgrades`
- Required exact parent: `b645d8328a0a61166965abec8901af5a1904dda4` (Slice 95 qualified, pushed, clean)
- Add exactly four files: one production module, one isolated regression module, and these two documentation files.

## Evidence to collect

1. Ruff import ordering, formatting, and full lint of both Python files.
2. `mypy --strict` on the new production module.
3. `pytest -q -ra tests/test_issue49_slice96_installed_wheel_audit.py`.
4. `pytest -q -ra tests/test_issue49_slice*.py tests/test_cli.py` using the actual repository's test inventory, not shell-glob assumptions.
5. `python -m pip check`.
6. Reconfirm the exact branch, origin, HEAD, remote, additive staged scope, and a clean worktree after guarded commit/push.

## Focused negative tests

- A changed, removed, size-mismatched, or symlinked installed file cannot pass local `RECORD` verification.
- Missing, invalid, oversized, duplicate, unsupported, or outside-environment `RECORD` entries never become trust evidence.
- Wrong package name, editable installation, missing WHEEL tags, no console-script declaration, wrong interpreter environment, unapproved package, and duplicate launcher declarations must be described as review cases.
- Normalization permits the PDS distribution name spelling variants but refuses traversal and arbitrary packages.
- Even a locally matching `RECORD` never reports a signed trusted wheel, production launch eligibility, or activation permission.
- JSON output remains bounded to metadata codes and does not contain machine/user paths or raw package URLs.

## Local development checks (not Windows acceptance)

- Python syntax and AST checks: passed.
- Focused synthetic metadata tests in isolated fixtures: 28 passed locally.
- Production-style Windows inventory and clean installed-wheel acceptance: **not yet performed**.

## Slice 97 distribution-identity correction

The original Slice 96 registry used repository labels instead of the actual
`scoreform` and `quillan` Python distribution names. On the exact Slice 96
commit, replace only those two registry strings and update the duplicate-launch
test; add regressions for the exact eight distribution names, live metadata
lookup names, and refusal to treat repository labels as approved distributions.
All prior drift, RECORD, interpreter-confinement, and no-trust regressions stay
intact. No classroom workspace or installed environment may be mutated.

This is a four-file in-place correction. Qualification requires full Ruff, strict
mypy, isolated Slice 96 tests, complete Issue #49 plus CLI regressions, pip check,
and a read-only inventory before guarded commit/push.

## Operation after qualification

With the desired installed PDS environment activated, run:

```powershell
& python -m paper_data_suite.evergreen_installed_wheel_audit
```

The output is read-only JSON. It is an inventory, **not** a signed provenance certificate. Do not use this command to decide whether to run installation, activation, rollback, or an untrusted module. Subsequent work must reconcile current authentic release wheels and signed catalog evidence and run actual installed-wheel scenarios.
