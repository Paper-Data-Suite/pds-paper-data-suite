# Issue #49 — Slice 79 validation record

## Four additive files

- `paper_data_suite/evergreen_plan_publication_preclaim.py` — protected same-connection publication preclaim and separately authorized observation.
- `tests/test_issue49_slice79_plan_publication_preclaim.py` — real synthetic receipt/request + SQLite reservation fixture; preclaim, readback, durability and negative paths.
- `docs/architecture/issue-49-publication-preclaim.md` — trust, ordering, crash and non-authority requirements.
- `docs/validation/issue-49-slice-79-publication-preclaim.md` — this record.

## Intended qualification

1. Compare exact HEAD/remote to `fe439c28c389c5be77ffff281b36b5b9d371d936` on branch `49-evergreen-launch-and-supported-composition-upgrades` in the exact Suite repository. Require a clean index and worktree; reject existing target files and non-additive changes.
2. Validate source ZIP and manifest hashes; apply exactly four files and normalize the two Python files with Ruff, then run read-only import, formatting and lint checks.
3. Run strict mypy for the production module. Run isolated Slice 79 tests, then all accumulated Issue #49 regressions and `tests/test_cli.py`, and finally `python -m pip check`.
4. If and only if all gates pass, stage exactly four new files, verify `git diff --cached --check`, commit once and push the branch after verifying the remote still matches the original baseline. No reset, stash, retry of failed tests, force push or automatic repair.

## Focused negative acceptance

Identical replay; modified request bytes; altered reservation fields and bool/int confusion; forged reservation without protected row; mismatched independent evidence; missing, failed or revoked service callback; wrong service actor; corrupt durable preclaim; SQLite reopen; active transaction; duplicate primary-key reservation; unmodified local recovery capsule and classroom documents. Production has no `publish`, `clear`, `launch` or CAS dispatch entry point.

## Limitations

Python syntax and packaging can be checked before handoff, but installed Windows Ruff/mypy, full accumulated tests and dependency consistency are **pending until user execution**. The synthetic SQLite and service evidence fixture does not prove independent deployment. No active receipt has been published or made launchable by this slice.
