# Issue #49 — Slice 70 validation ledger

Baseline: Slice 69 commit `6b50efc` on `49-evergreen-launch-and-supported-composition-upgrades`.

Source scope (four additive files):

- `paper_data_suite/evergreen_plan_candidate_intent.py`
- `tests/test_issue49_slice70_candidate_intent.py`
- `docs/architecture/issue-49-plan-signed-candidate-journal.md`
- `docs/validation/issue-49-slice-70-signed-candidate-intent.md`

## Isolated acceptance

33 isolated tests passed against stand-in implementations of earlier repository APIs. Covered explicit consent, stage/workspace isolation, signed-native-before-request ordering, exact request payload binding, fresh physical remeasurement, full staged-plan identities, refusal of bad envelopes/signatures, refusing stale or existing journals, no activation/selection, journal write failures, and retained recoverability after a bad post-write readback. **These tests do not prove actual release signing or native verification.**

## Required Windows qualification

The guarded runner must verify exact Git origin, branch, HEAD, clean state, and source ZIP manifest before writing. Ruff import/formatting passes are allowed to reorder imports only, checked by import-independent AST equivalence. Then require Ruff check, strict mypy on new production code, complete Issue #49 Slice 1–70 pytest regression files plus both legacy CLI test files, and `pip check` before narrow four-file commit/push. Windows symlink-permission skips are expected but must not be reported as passes. No commit on any failed gate.

## Boundaries not claimed

- No production signer keys, external root-authority deployment, or proof that arbitrary candidate interpreter binaries originate from an official release.
- No active-selection switch, launch, protected receipt, rollback/recovery execution, auto-update or classroom workspace change.
- No read-only journal can independently prove a fresh witness head; an eventual activator must perform protected independent CAS re-verification.
- No installed-wheel/physical Windows acceptance of a production signed release has occurred in this slice.
