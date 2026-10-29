# Issue #49 Slice 95 — Qualification and acceptance

## Additive scope

1. `paper_data_suite/evergreen_plan_activation_readiness.py` — append-once protected activation-readiness reservation coordinator.
2. `tests/test_issue49_slice95_activation_readiness.py` — full-chain synthetic regression and fail-closed cases.
3. `docs/architecture/issue-49-activation-readiness-reservation.md` — trust, persistence, and non-activation boundaries.
4. `docs/validation/issue-49-slice-95-activation-readiness-reservation.md` — qualification requirements and evidence.

Baseline: Slice 94 `2156b70d9b3f6ac269bc10600a095823ae3e0744`, branch `49-evergreen-launch-and-supported-composition-upgrades`.

## Expected test evidence

Synthetic success must result in one durable non-activating reservation and unchanged process-start count, active receipt, classroom artifacts, and protected recovery records. Negative tests cover duplicate reservations, invalid independent activation-fence booleans and identities, two-sample drift, changed health evidence since Slice 94, missing process, forged persisted health or caller-supplied health object, corrupted successor receipt, reappearing capsule, missing signed witness, unauthorized service context, corrupt persisted reservation, external transaction contention, malformed constructor, and prohibited launch-service argument.

SQLite schema smoke checks must confirm the 16-column table and its primary key, duplicate prevention, and non-activating status constraint. Python AST/syntax and source-archive integrity checks are local preflight only; they do not substitute for Windows acceptance.

The guarded Windows runner must verify exact branch, origin, clean checkout, remote SHA, exact four-file additive ZIP, member SHA-256 hashes, and no symlink or overwrite. It may use Ruff import fixing and formatting on only the two new Python files, then must pass read-only Ruff checks, strict mypy for the production file, isolated Slice 95 pytest, all accumulated `test_issue49_slice*.py` and `test_cli.py`, and `pip check`. Only then may it stage exactly the four additive files, commit, push, verify remote SHA, and confirm clean status.

No runner may reset, stash, retry, roll back, force push, or remove files. Windows unprivileged-symlink skips should be explicitly reported.

## Non-goals / outstanding acceptance

No actual Windows activation, privileged service certification, production process-health acceptance, slot switch, or process relaunch. No automatic activation permission can be inferred from a passing synthetic test or the new protected reservation.
