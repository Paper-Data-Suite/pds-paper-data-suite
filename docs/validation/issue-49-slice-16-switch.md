# Issue #49 — Slice 16 validation

**Base:** `483c863` (exact 40-character Git commit required by runner).

**New files:** `evergreen_prior_switch.py`,
`test_issue49_slice16_prior_switch.py`, and two documentation files.
No existing tracked source, production launcher, bootstrap, doctor, CLI, or
classroom-workspace contents are modified by this slice.

## Acceptance cases

- Armed two-sided switch preserves original pointer bytes in a recovery capsule
  and increments only the untrusted selection generation.
- `restore_previous_selection` returns exactly the old selection, keeping
  physical previous/candidate software intact.
- Unarmed/stale/wrong-transaction journals and absent prior receipts fail.
- Candidate/prior executable tampering, altered envelope bytes, a changed
  previous selection generation, missing selection, and expired signed evidence
  fail without creating a replacement selection.
- Pending recovery, selection/journal lock contention, and workspace overlap
  fail closed.
- A simulated failure during pointer replacement leaves the recovery capsule
  and exact previous pointer available for safe restoration.
- A third-party pointer substitution is not overwritten by recovery.
- Normal operation reads no classroom files and never grants activation rights.

Local synthetic fixture run: 440 tests passed across issue #49 Slices 1–16.
The final Windows runner performs Ruff import sorting/lint/format, strict mypy,
focused pytest, dependency validation, staged whitespace/scope validation,
then commits and pushes only if all gates pass.

**Known limitations:** Tests use synthetic signed runtime inputs. A valid local
observation is not historical active-installation authority; same-user state
is replaceable and the production launcher remains unchanged.
