# Issue #49 — Slice 77 guarded qualification record

## Exact additive scope

1. `paper_data_suite/evergreen_plan_finalization_preflight.py` — ephemeral plan-bound, remote-refreshed and local-locked forward-finalization preflight, **no writes to durable recovery state**.
2. `tests/test_issue49_slice77_plan_finalization_preflight.py` — isolated real local proposal/capsule/journal/selection and signed witness fixture; remote/physical Slice 76 wrapper is a synthetic test stand-in only.
3. `docs/architecture/issue-49-plan-finalization-preflight.md` — trust, ordering, and limitations.
4. This validation record.

## Negative cases and acceptance

The suite verifies a matching witnessed successor while preserving the recovery capsule, proposal, pointer, journal and classroom data. It refuses modified canonical plan metadata, changed or forged refreshed observations, missing/altered proposal/pointer/capsule/journal, wrong Ed25519 witness pin, active selection-lock contention, invalid recovery inputs and independent verifier outage. It asserts that successful results have no commit or launch method, and that the result's hash summaries match the retained local files. Readback occurs after the independent review, under existing cooperative locks, and must find a fresh signed successor; predecessor-only and uncertain results cannot proceed.

## Guarded Windows workflow

1. Verify exact parent commit `a5878eee157578715eacc5852de6ca963944c862`, branch `49-evergreen-launch-and-supported-composition-upgrades`, origin and matching remote HEAD; require clean worktree and clean index.
2. Verify the embedded four-file archive SHA-256 manifest, no archive path aliases or symlinks, bounded UTF-8 content and Python syntax. Add only four previously absent files.
3. Ruff import-sort and format only the two new Python files; read-only lint/import/format checks; `mypy --strict` for the production file.
4. Run the isolated Slice 77 tests and then *all* `test_issue49_slice*.py` regressions and `tests/test_cli.py`. Check `pip check`.
5. Reconfirm exact additive path inventory, original Git SHA and remote; stage only four new files; check staged add-only scope and whitespace; commit and push without force. Verify remote commit and clean checkout. A failed test leaves exact partial files in place for explicit guarded repair, **never automatic reset or retry**.

## Claims not made

Source syntax and ZIP hashes do **not** establish full Windows qualification. A Windows runner must report the real test counts, Ruff/mypy results and commit. Synthetic test doubles are not proof of an independently administered service, physical installation safety, receipt publication, crash-safe cleanup, or launch eligibility. The 21 preexisting symlink-related Windows skips may remain. The update-recovery capsule must remain intact throughout this slice.
