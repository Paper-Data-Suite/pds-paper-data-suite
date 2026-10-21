# Issue #49 — Slice 41 validation: successor receipt proposal only

## Windows package acceptance

Run `run_slice41.ps1 -Repo .` on `49-evergreen-launch-and-supported-composition-upgrades` at exact SHA `cbc016b08a653e601b29b9a881ac99147aae841f` with the existing `.venv`. The guarded runner checks the official repository origin, remote branch SHA, clean local tree, exact additive targets and manifest SHA-256 digests before installing four files. It then performs Ruff import sorting/formatting/lint, strict mypy for the new production module, the complete issue #49 slice test inventory, `pip check`, an exact staged-file-set check, and automatic commit/push only if every gate succeeds.

The test module uses controlled publisher/pip/native audit doubles to challenge transition orchestration; earlier slices test the underlying verification layers separately. It verifies a correctly generated canonical, predecessor-bound generation-2 receipt draft; the unmodified selection, journal, recovery capsule and classroom workspace; absent capsule, pointer mismatch, stale journal, forged or changed receipt, invalid or replayed witness, remote outage, both physical stages tampered during the witness call, concurrent local state modifications, expiry, lock contention, and no subprocess or launch execution. It also verifies the proposal never marks success and does not block Slice 40's offline rollback.

No unit-test count or skipped count is predicted. Report the real Windows output. A successful test suite does **not** prove independent witness operation, OS filesystem protection, physical activation, remote commit support or production release readiness.

## Expected git handoff

Commit subject: `feat(suite): draft witness-bound successor receipts (#49 slice 41)`. Failure leaves changes uncommitted and unpushed for review. No source files from earlier slices or mainline launch interfaces should be modified.
