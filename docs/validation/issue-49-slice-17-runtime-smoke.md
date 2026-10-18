# Issue #49 — Slice 17 validation

Additive files: `evergreen_candidate_acceptance.py`, `test_issue49_slice17_candidate_acceptance.py`, architecture and validation documents.

## Local checks

- Python syntax compilation passes.
- Synthetic, signed stage and journal fixtures: pass and fail-closed cases for interpreter identity, offline pip check, exact journal binding, changed executable bytes, injected mid-run mutation, stale phase, missing journal, pending recovery, exclusive locks, host layout, invalid timeouts, child error/timeout and no persisted child output.
- Focused test suite covers issue #49 Slices 1–17. Runner invokes it once, not a dirty run followed by an immediate clean rerun.

The repository runner applies import sorting and formatting, then Ruff check, strict mypy, focused pytest, `pip check`, staged whitespace, and exact file scope. Only a successful run commits and pushes.

## Exclusions

Synthetic tests intercept `subprocess.run`; they do not execute test fixture executable bytes. No real Windows staged venv was accepted in this slice and no production `pds launch`, `pds doctor`, state receipt or install mutation is enabled. Genuine Python runtime acceptance is pending controlled end-to-end qualification. No raw user/classroom payloads are included in fixtures, metadata, or error summaries.
