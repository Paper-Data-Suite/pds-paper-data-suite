# Issue #49 — Slice 11: Signed-candidate update intents and crash-recovery journal

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base commit:** `808accbcb0e72269280e9bc5b87ded368af9b224`
**Status:** Isolated, additive transaction-state infrastructure. No runtime, updater, or launcher wiring.

## Purpose and explicit limitations

A verified staged environment alone is insufficient to perform a safe update. Before changing the one managed installation, Suite needs to record **what it intends to change**, retain enough identity information to recognize an interrupted change, and refuse to self-certify an incomplete transaction after restart.

`evergreen_update_journal` introduces a strict, bounded, canonical JSON intent, written through a same-directory temporary file and atomic replacement. The candidate cannot enter this journal until **raw signed** release-registry, dependency-lock, and native-executable evidence have been independently reverified against the staged virtualenv, exact wheelhouse and prepared composition (via Slice 10). Later movement from `candidate_verified` to `activation_intent` repeats that entire signed stage verification and rechecks that all envelope bytes match the recorded hashes.

This slice **never runs pip**, changes an executable, activates a stage, flips an active pointer, restores packages, imports stage code, invokes a subprocess, writes an active-installation receipt or changes `pds launch`. It is **not a complete updater** and it does **not** demonstrate rollback of package bytes. That work remains mandatory before production wiring.

## Journal contract

Each transaction is bound to one lowercase 32-hex transaction ID from the prepared composition. The journal file is `<approved-software-root>/transactions/<transaction-id>.json`, never a caller-chosen free-form path. The `transactions` directory and root must already exist. The caller explicitly supplies a **distinct classroom workspace root**: software root and workspace cannot be the same directory or ancestors of each other. Both directory chains and the staged inputs must be ordinary directories, not evident symlinks or Windows reparse points.

The journal records:

- Schema identity/version, transaction ID and monotonically increasing local revision.
- One of `candidate_verified`, `activation_intent`, `recovery_required`, or `aborted`.
- Aware UTC state timestamp; confined relative paths for stage and wheelhouse.
- SHA-256 of the exact prepared record, signed registry envelope, signed lock envelope, and native-evidence envelope.
- An **optional expected** previous-install receipt digest. This expectation is **not itself an authenticated active-installation record**.

All keys and types are exact. Unknown fields, duplicate JSON keys, nonsensical phases, noncanonical bytes, malformed digests, traversal, stale revisions, locked transactions, prior clock regressions and attempts to reset an existing transaction are rejected. The record is **locally editable**: its checksum-like hashes detect ordinary discrepancies on re-verification, but a same-user attacker can forge the record. Do not use it as a signing root, anti-rollback anchor, installed receipt, or launch permission.

## State transitions and interruptions

`begin_verified_update_intent` verifies signed stage evidence and atomically writes `candidate_verified` (revision 1). This records readiness for a *future* updater only.

`request_activation_intent` requires revision 1, exact immutable envelope bytes and another signed stage verification. It writes `activation_intent` (revision 2), **without switching anything**. On restart, an intent is classified as `manual_active_install_reconciliation_required`: no automatic promotion, retry or assumption that a swap succeeded. Later activator code must compare independently verified previous/current **actual files** before deciding how to recover.

`record_safe_disposition` allows only `candidate_verified` → `aborted`, or `activation_intent` → `recovery_required`, advancing the journal revision. Neither status changes package files. `classify_recovery` reports deterministic nonmutating guidance; it never asserts a state of the active environment.

Concurrent cooperating writers are serialized by an exclusive per-transaction lock file. Stale locks block writes pending deliberate recovery; no unsafe automatic lock break. Atomic replacement preserves the prior journal on injected write/replace failure and cleans temporary files. Local disk metadata does not provide durable trust against rollback by a same-user actor; power-failure durability depends on filesystem/platform support and operating-system protection. Windows junction, hardlink and concurrent attack races require further scrutiny at the active-installation boundary.

## Remaining activation gates

1. Independently owned root/key provisioning and reproducible executable signatures; a teacher machine must not self-sign arbitrary generated launchers.
2. Actual staged package installation from signed, fully locked offline wheels; complete real-pip behavior, native provenance, and module/Core smoke tests.
3. Protected active-install receipt and continuity independent of replaceable update journal state; explicit migration from historical Suite environment markers.
4. Crash-recoverable **actual installation slot switch** with previous verified executable bytes retained, restoring the original software on failure, and tested Windows ARM64/x64 paths and reparse-point security.
5. Teacher-visible `update --plan`, explicit approval, targeted updates, offline status/doctor, and independent per-module launch/per-feature integration qualification.

No teacher workspace files, school roster/grades/student data or old release manifests are written or modified by Slice 11.
