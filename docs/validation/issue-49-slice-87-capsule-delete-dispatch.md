# Issue #49 — Slice 87 qualification and operating limits

**Expected parent:** `132101f0d615fb023f08e568276abfda6fa30a79` on `49-evergreen-launch-and-supported-composition-upgrades`.

**Additive scope:** exactly four new files: the production coordinator, its regression suite, this validation note and the architecture note. Do not modify committed Slices 78–86, source configuration, or user workspace files.

**Checks in the guarded Windows runner:** exact source ZIP and member SHA-256, syntax, repository identity, clean branch and remote HEAD, Ruff import sorting/formatting/lint, strict mypy for the production module, isolated Slice 87 pytest, the complete Issue #49/CLI tests, `pip check`, staged-addition-only verification, conditional commit/push and remote confirmation. No reset, stash, forced push or auto-retry.

**Regression evidence targeted:** exact persisted protected chain, claim-before-deletion ordering, one service callback only, read-only inspection of persisted claim, replay refusal, callback success-without-delete, delete-then-lost-ACK, postdelete reader outage, mismatch of capsule identity/receipt/selection, independent OS fence or durability evidence loss, unauthorized caller, predelete record tampering, capsule drift, missing actual protected row, signed witness mismatch, active SQLite transaction, reopened service database and corrupted durable status/digest.

**Unverified production requirements:** callback trust/privilege separation, Windows no-follow reparse and link safety, protected file-handle identity, real same-volume deletion and directory durability, ACLs, process-wide fencing, physical custody, power-loss injection, watchdog of outstanding delete operations and launcher isolation. Synthetic callbacks cannot validate these requirements.

**Acceptance boundary:** Slice 87 may be marked code-qualified after full Windows gates, **not** deployed or launch-ready. A positive post-delete observation remains provisional. Never interpret a retained one-shot claim as authority to delete again.
