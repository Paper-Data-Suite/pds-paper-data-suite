# Issue #49 — Slice 47 validation plan

## Windows source-only acceptance

Run `apply_slice47.py --archive pds_suite49_slice47_source_only.zip --repo . --apply` from the exact clean Suite `49-evergreen-launch-and-supported-composition-upgrades` branch at commit `3ca6ecf5758fcf4cea29ae32d91c073b1b4084f8`. The independent Python runner checks the Git origin, branch, local and remote commit, absent four targets, exact four ZIP member SHA-256 values, and exact staged scope.

Before committing, require Ruff import sorting/formatting/lint, strict mypy on new production module, all issue #49 test files through Slice 47, `pip check`, and Git whitespace/diff checks. The runner creates only four additive repository files and will not commit or push on a failed check. Use the actual Windows counts rather than predicting a pass count.

## Test design

The regression test module exercises a real in-memory `MonotonicCheckpointStore`, signed Ed25519 predecessor/successor receipts and fresh challenge-bound head readback. The local selected pointer, pending recovery capsule, revision-2 journal and durable successor proposal are genuine canonical protocol records. Convergence is constructed through the Slice-46 comparison helper.

Publisher/pip/native stage auditors are **test doubles**, returning deliberately bounded mock observations and detecting simulated candidate-file modifications. This tests the new double-audit coordination and fail-closed handling but is **not** an integration acceptance with real signed PDS wheels or true Windows software deployment.

Negative cases include invalid context, missing proposal, journal/capsule/proposal drift, mismatched signed envelopes, edited installed candidate bytes before/after the witness query, mismatched pip/native payload identities, second audit failure, offline and wrong signer, stale observation duration, changing caller envelope maps, already held selection lock, untouched classroom work and absence of application execution.

## Follow-up and status

Expected commit title: `feat(suite): requalify witnessed successor bytes without activation (#49 slice 47)`.

A green test run qualifies only this additive preflight. It **does not** establish protected physical switchover, authenticated actor consent, active receipt commitment, rollback permission, or production launch eligibility.
