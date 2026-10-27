# Issue #49 — Slice 80: service-owned protected receipt record

## Boundary and decision

Slices 78–79 reserve finalization and durably preclaim possible publication, without writing any active receipt. Slice 80 adds the **first protected successor-receipt write**, confined to the **same independently administered SQLite database connection** as those two existing records. This is an atomic, one-shot **service-side receipt record**. It is *not* a write to a classroom-local active-receipt path and **cannot establish local active installation or launch readiness**. The existing pending recovery capsule, local selection and update journal remain unchanged. No new witness CAS call, rollback, slot switch, local receipt publication, package execution or teacher CLI/HTTP writer is provided.

The new SQLite table, `plan_protected_receipt_v1`, has a primary-key row per installation and the sole terminal status `PROTECTED_RECEIPT_RECORDED_LOCAL_RECOVERY_PENDING`. It stores **exact canonical successor receipt bytes** (bounded by existing active-receipt parsing), their SHA-256, canonical request hash, transaction, generation, witness revision, original Slice-78 reservation hash, Slice-79 preclaim hash and originally retained independent-evidence digest. A read-only inspector checks the receipt's canonical encoding, hash, transaction, generation and constrained status. The return dataclass omits receipt bytes and confers no authority.

## One-shot write order

1. Reparse the canonical request against a supplied Slice-78 reservation; reject unrecognized types, booleans as integers, altered non-authorizing status/authority or any wrong successor fields. Validate the exact supplied Slice-79 preclaim, including the hash of **all** reservation fields. Neither caller-provided dataclass is an authorization token.
2. Require a separately authenticated `record_protected_receipt_once` service operation and provisioned live witness transport/pinned key/whole-second clock. These must not be derived from teacher-writable inputs.
3. Enter SQLite `BEGIN IMMEDIATE` on **the exact existing service connection**. Re-fetch the actual durable reservation and preclaim with their own independent read authorizations; both must match byte-for-byte equivalent typed values. Reject an existing recorded row regardless of whether its content matches.
4. Reacquire fresh independently administered evidence inside the transaction, requiring stopped writers, physical byte re-audit and operator consent to remain literally true with identical preimage hashes. These callbacks are **not** independent merely because Python accepts them: service isolation is a deployment obligation.
5. Obtain a new signed witness challenge-bound readback using the separately pinned witness key. Accept only the exact successor digest, generation and expected next revision. Reject a predecessor, unknown revision, stale or untrusted signed statement, outage and future states.
6. Insert the exact successor receipt bytes into the protected database and commit **once**. The same transaction makes the protected receipt row atomic in SQLite. Exceptions and uncertain COMMIT outcomes must lead to *read-only* observation and explicit incident reconciliation, not a second write.

The prior reservation/preclaim remain immutable and present. No method clears or disarms them. A missing protected receipt row after a crash does **not** make an automatic retry safe; independent operators must reconcile the retained preclaim and verify no external side-effect occurred.

## Limits and follow-on

There is deliberately **no cross-filesystem atomicity claim**. SQLite does not atomically publish a different local active-receipt file, remove `pending-slot-recovery.json`, switch code execution, establish verified local installation, or harden the OS. The witness confirms a signed logical successor, not necessarily unchanged physical bytes after its sample. Production must independently provision service account privileges, SQLite durability/ACLs, physical-byte custody, anti-replay and fresh consent, key and TLS pinning, process-wide writer quiescence, and trustworthy clocks. The synthetic tests cover code ordering and SQLite semantics, not those operational prerequisites.

Next: independently protected local active-receipt deployment protocol, with an explicit crash journal linking the protected receipt to actual installed bytes, a retained recovery capsule until completed local reconciliation, and clear separation from any subsequent *launcher readiness* authorization.
