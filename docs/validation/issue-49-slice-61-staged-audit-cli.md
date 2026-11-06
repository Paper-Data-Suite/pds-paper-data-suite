# Issue #49 Slice 61 — Verification Record

## Source scope

- Add `paper_data_suite/evergreen_staged_catalog_cli.py` (read-only adapter).
- Add `tests/test_issue49_slice61_staged_catalog_cli.py`.
- Add this record and the accompanying architecture note.
- Exact anchored patch to `paper_data_suite/cli.py`, adding three opt-in flags,
  guarded dispatch, and explicit refusal; no change to default behavior.

## Required gates

- Source package hashes and the exact Slice 60 development-branch baseline.
- Verify unchanged Git preimage and clean worktree before changing files.
- Ruff import sorting, Ruff formatting, Ruff lint and strict mypy for all
  modified production code; `pytest` all Issue #49 slices and existing CLI
  tests; `python -m pip check`.
- Reverify Git staged scope/whitespace and unchanged origin immediately before
  commit/push. Refuse on failure; no reset or forced push.

## Negative cases

- Partial trust/audit flags and incompatible metadata comparison.
- Missing, extra, unreadable, oversize, or symlinked evidence inputs.
- Wrong registry/module selection or absent cached signature authority.
- Physical stage audit and native signature failures do not fall back.
- No writes, network calls, package execution, or classroom workspace access.
- Report clearly distinguishes audited candidate from active software.

## Local / Windows results

Local source parse and isolated harness tests should be recorded before handoff.
The guarded Windows run is the authoritative integrated qualification. This
slice cannot claim approved active software or operational evergreen launching.
