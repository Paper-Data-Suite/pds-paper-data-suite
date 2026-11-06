# Issue #49 — Slice 89: Launcher readiness preflight validation

## Scope

One new production module, one regression file and two docs, with no changes to Slices 1–88. Validated exact baseline requirement: Suite Issue #49 branch at `fc22af4c836ea4689a2e3a1e220f9bedfc83be28`. Service-owned protected SQLite persists the one-shot non-activating preflight. Neither production nor tests are authorization to operate a privileged Windows service or start a launcher.

## Windows acceptance gates (pending)

1. Verify exact four-file source archive SHA-256 and exact file manifest; refuse pre-existing paths, dirty repository, incorrect remote, branch or HEAD.
2. Ruff import sorting, Ruff formatter, complete Ruff lint; strict mypy on production module.
3. Isolated `tests/test_issue49_slice89_launcher_readiness_preflight.py` tests using real Slice 78–88 integration/witness fixtures.
4. All accumulated Issue #49 and CLI regressions with no unexpected failures; dependency consistency (`pip check`).
5. Reverify full additive scope, baseline and remote; stage exactly four new files, validate staged diff, commit, push and confirm remote matching new commit and clean worktree.

## Focused refusal coverage

* No launcher process, deletion retry, rollback or slot switch; only the non-authorizing status may be recorded.
* Strict once-only insertion and durable reopen readback; malformed persisted record is refused.
* Full pinned service chain, actual postdelete certificate, witness revision and signed successor; missing/mutated/forged entries are refused.
* Exactly absent recovery capsule, exact installed successor receipt, independent delete termination, unchanged local identities, stable launcher runtime and dependency audit.
* Missing/false readiness booleans, invalid digests/identities, user data drift, wrong actor, malformed callback, changed runtime between two reads, and altered witness all refuse.

## Interpretation

Container-only source checks and synthetic test fixture checks are not Windows qualification. Even a fully green Windows pytest + Ruff + mypy run validates the **protocol interface**, not the privileged Windows launcher/runtime inspection provider, actual service ACL enforcement, filesystem durability or crash-safety. Those require additional native acceptance before production authorization may ever be considered.
