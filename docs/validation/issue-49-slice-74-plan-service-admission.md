# Issue #49 — Slice 74 validation record

## Scope

Four additive files: service-only plan admission coordinator, direct regressions, architecture decision, and validation record. Required Git baseline: `62a7b7543c069318a54be637d72933519b052cc0` on `49-evergreen-launch-and-supported-composition-upgrades`. No modifications to any earlier slice, historical bundled release manifests, classroom data, local receipt or slot recovery are permitted.

## Test matrix

- Canonical review exactness: request SHA, bounded byte length, status and no-authority field, revision, predecessor/proposed generation, transaction, installation, receipt digests, canonical request serialization and parsed receipts.
- Independent service expectation: pinned installation, witness identity/revision, prior transaction, generation and predecessor receipt SHA; missing/failed/forged readers are rejected **before** reservation.
- Explicit service approval: accepted only for literal `True` from a separately provisioned policy; missing, denied or throwing approval cannot reserve.
- CAS ledger/gate: same service connection and ledger required; authorized reservation written before one-time writer admission; statuses strictly `PREPARED_NO_DISPATCH` and `ADMITTED_NOT_DISPATCHED`; independent readback agrees with both states.
- Crash/replay: admission remains durable after SQLite connection restart; duplicate request refused; denied/failed writer admission, inconsistent service readback and lost-return situations do not delete the already stored fence.
- Exclusions: `dispatch_once()` (ledger and gate), witness checkpoint CAS, receipt publication, capsule deletion, install selection, app launch and classroom file writes are not called.

## Execution gates

The guarded Slice-74 runner verifies exact repository/remote/branch/baseline and all four ZIP members and hashes. It refuses dirty or unexpected local changes. It runs Ruff import fixing/formatting on **only** the two new Python files, then Ruff import/format/lint checks, strict mypy for the coordinator, all Slice 1–74 regressions plus legacy `tests/test_cli.py`, and `python -m pip check`. Only after all succeed may it stage precisely four added files, run staged whitespace checks, commit, and push the branch.

The local preparation here checks source integrity, syntax, manifest consistency and guarded-runner refusal; full repository tests and Windows ARM64 qualification must run in the user's existing Suite `.venv` before commit/push. Windows may skip unavailable unprivileged symlink tests; do not interpret these environment skips as production acceptance. The fixture's service callbacks do not prove independent deployment/custody.

## Acceptance limits

Slice 74 qualifies **service-side admission control flow only**. It makes no claim that an actual independent service, real publisher signing, physical switch protection, CAS dispatch/reconciliation, signed successor commit, cleared recovery capsule, integrated product release or teacher-facing production launch is complete.
