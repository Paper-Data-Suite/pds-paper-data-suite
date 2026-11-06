# Issue #49 · Slice 62 validation record

Scope: `paper_data_suite/evergreen_witness_selected_stage.py`, `tests/test_issue49_slice62_witness_selected_stage.py`, architecture and validation documentation. Four new files; no existing production or CLI edits.

Baseline: `edc8d17851e552cad8a4399ef3e22b53c5bad218`, branch `49-evergreen-launch-and-supported-composition-upgrades`.

## Required Windows qualification gates

- Verify source ZIP membership and SHA-256 before writing; exact expected remote origin, branch and HEAD, and clean index/worktree.
- Ruff import order and formatting, followed by check-only Ruff lint.
- Strict mypy on new production module.
- Complete `tests/test_issue49_slice*.py` regression tests, plus application and base CLI tests.
- `pip check`, exact staged file scope, `git diff --cached --check`, no unstaged changes, recheck remote before commit.
- Commit and push only after every gate passes; never reset/stash, stage unrelated files, or force-push.

## Coverage

A real Ed25519/SQLite witness fixture verifies distinct challenge observations. Additional tests cover invalid inputs, missing or altered selection, incomplete recovery marker, changed signed bytes, incorrect witness identity/key, physical audit failure, mismatched console/externals, pointer drift during audits, signed head revision drift, software/classroom overlap, and unchanged classroom/stage data. The staged-byte subaudit is monkeypatched in focused tests; prior Slice 60 tests separately exercise its logic, and the full regression suite must qualify their combination.

Expected observation: `WITNESS_PINNED_SELECTED_STAGED_BYTES_OBSERVED_ONLY`, explicitly without launch/activation/receipt authority. **No assertion of protected active-state custody or production launch readiness.**

The authoritative machine-specific test totals and any skips should be recorded from the Windows runner output. Do not claim qualification from isolated tests alone.
