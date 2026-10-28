# Suite #49 — Slice 82 guarded validation

## Scope and immutable baseline

**Required baseline:** `1c6e0e35bc75f0524350058b80c2d3ba9ce7f595` on `49-evergreen-launch-and-supported-composition-upgrades`, exact `https://github.com/Paper-Data-Suite/pds-paper-data-suite.git` origin and matching remote head. Require a fully clean index/worktree. Exactly four additive files are permitted:

1. `paper_data_suite/evergreen_plan_local_prewrite_uncertainty.py`
2. `tests/test_issue49_slice82_local_prewrite_uncertainty.py`
3. `docs/architecture/issue-49-local-prewrite-uncertainty.md`
4. `docs/validation/issue-49-slice-82-local-prewrite-uncertainty.md`

The source ZIP is SHA-256 pinned per member; a separate apply runner is also SHA-256 pinned by the handoff. Any unexpected branch, tracked edit, symlink target, stale remote, archive hash, untracked file, or test failure refuses commit/push without an automatic reset, stash, rollback or retry.

## Windows qualification gates

The guarded runner executes, in order: exact archive and baseline verification; exclusive-create additive source write; Ruff import sorting and format; Ruff import, format and full lint checks; strict mypy on the production module; isolated Slice-82 pytest; accumulated Issue #49 tests **including every previous slice** plus `tests/test_cli.py`; `python -m pip check`; exact four-file scope and baseline/remote recheck; guarded four-file additive commit; ordinary push and verification of remote and clean worktree. Symlink-privilege skips must be reported rather than disguised as passes.

## Regression matrix

Tests use the **real** Slice 78–81 reservation → preclaim → protected receipt → local intent chain in an isolated SQLite database, with synthetic signed Ed25519 witness and simulated local file reader. Coverage includes:

- Once-only marker insertion, exact digest bindings, no direct file/capsule mutation, no authorizing methods, and read-only observation.
- Durable marker survives closing/reopening SQLite and refuses identical replay.
- Before-arm predecessor drift, changed local snapshot, forged intent, absent durable intent, lost witness, revoked consent, wrong authenticated service actor and preexisting SQLite transaction.
- Read-only post-arm classifications for exact predecessor/successor, missing target, and unexpected bytes; all retain pending capsule and explicitly deny retry/launch.
- Missing marker, changed capsule, unsafe target or active-file type, absent writer fence, wrong pinned target, oversized bytes, unauthorized inspection and corrupt protected SQLite row.

**Scope of proof:** These tests exercise Python/SQLite contracts with synthetic callbacks; they do *not* demonstrate independently administered operating-system service custody, physical filesystem exclusion, crash-durable Windows rename, or actual local publication. Any future writer requires additional Windows process/fault-injection qualification and explicit operator approval.
