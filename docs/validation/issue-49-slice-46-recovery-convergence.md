# Issue #49 — Slice 46 validation and Windows handoff

## Guarded application

Baseline: branch `49-evergreen-launch-and-supported-composition-upgrades`, exact SHA `3e80d59` (full SHA recorded in the Python runner). The source-only ZIP contains exactly four additive `.py`/`.md` files; no PowerShell, batch script, executable archive entries, hidden prerequisites or downloads. The standalone `apply_slice46.py` hashes and size-checks all entries, verifies repository origin, clean worktree and exact local/remote baseline, then copies only those four files. It runs Ruff import sorting, formatting and lint, strict mypy on the new module, the Slice 1–46 pytest suite, dependency consistency, staged scope and whitespace gates. It commits and pushes only after all gates pass. Failed gates leave an uncommitted, unpushed candidate for repair.

## Tests and coverage

`test_issue49_slice46_recovery_convergence.py` uses real canonical predecessor/successor receipt constructors and canonical witness request encoding. It covers agreement for old and new head, pending service admission/dispatch/stop states, even a new head while service writers are not sealed, changed service request binding and installation identity, wrong claimed authority, unexpected service state, bad and boolean revisions, local transaction mismatch, bad/local authority, inconsistent local generation and digest, service/local direction disagreement, missing or malformed request, and absence of launch/network/filesystem mutation. This is a pure algorithmic comparison test, not a physical deployment qualification or proof that supplied observations originated from independently protected services.

Do **not** infer production readiness from unit tests alone. Integration tests with independent service credentials, real signed wheels, hard OS-level writer fencing, power-loss durability, and actual Windows restart/reconciliation remain future work.

## Git handoff

Expected message: `feat(suite): classify service-local recovery convergence (#49 slice 46)`. Record actual Windows test totals and Git commit before advancing. The runner does not reset other local changes, bypass security software, or request elevated privileges.
