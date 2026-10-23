# Issue #49 — Slice 52 validation: fresh attested recovery observation

## Scope

Four **additive** files only. This slice introduces one read-only orchestrator, synthetic focused tests, and two documents; no previous source file is modified. Baseline is Slice 51 commit `97bec15fe98cbe6164f088a8bc87eaf65082d01a` on branch `49-evergreen-launch-and-supported-composition-upgrades`.

## Invariants

- Verify the signed service envelope and transaction binding before any local/witness/package audit.
- Obtain local signed-head observations using `inspect_pending_forward_recovery`, not an in-memory local argument.
- Recompute convergence and require a confirmed successor before calling the physical byte auditor.
- Use the existing `requalify_witnessed_successor_bytes` to perform two physical audits around fresh signed readback, with its own local-state checks.
- Repeat signed local head inspection and fail on changed observations.
- Reject changed candidate hashes, invalid service signer, wrong challenge, expired statement, mismatched transaction, prior/unknown local status, physical audit failure, and elapsed observation budget.
- No local receipt write, pointer switch, recovery marker cleanup, witness CAS, package execution, classroom data access, or automatic launch.

## Test coverage and limitations

`test_issue49_slice52_fresh_attested_recovery.py` uses real canonical active receipts and a real Ed25519 service signature but **constrained test doubles** for the existing local signed-head reader and physical auditor. It tests ordering, argument forwarding, refusal propagation, repeat observations, and non-authorizing outputs. It does not replace the earlier slices' independent signed-witness/pip/native acceptance or real OS protections.

On Windows: Ruff import sorting, Ruff formatting, Ruff lint, strict mypy of new production code, **all Slice 1–52 tests**, `pip check`, staged-path verification, and a guarded commit/push are required. Symlink-related skips may occur on an unprivileged Windows test environment. If any gate fails, do not commit or push; inspect the precise failure.

## Explicitly not tested or enabled

Service deployment isolation and private signing-key custody, hostile concurrent local writers, physical installed-wheel update and launch, Windows x64/ARM64 qualification, receipt finalization, rollback, and teacher-facing CLI activation remain out of scope.
