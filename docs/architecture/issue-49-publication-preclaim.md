# Issue #49 — Slice 79: protected, one-shot publication preclaim

## Decision: stop at the publication uncertainty boundary

Slice 78 introduced an immutable, per-installation `PREPARED_NO_ACTIVE_RECEIPT_WRITE` finalization reservation. It does **not** allow active-receipt writes. The next necessary boundary is to record that a publication attempt *may subsequently be dispatched* **before** any future service implementation touches independently protected local active-receipt state. Slice 79 adds that preclaim and deliberately does **not** dispatch a filesystem writer. It makes the durable uncertainty barrier available to future protected publication work.

This is not an update completion feature. No new local receipt, slot, journal phase, recovery-capsule deletion, witness CAS operation, launch, rollback or user-facing CLI is added. The teacher workspace remains untouched. No preclaim object is a bearer authorization for the next step.

## Same-service storage and actor boundary

`ProtectedPlanPublicationPreclaimLedger` takes a genuine `ProtectedPlanFinalizationFence` instance and uses **its exact SQLite connection**, not a caller-supplied alternate database. Its separate `plan_publication_preclaim_v1` table has one row per installation and a `CHECK`-constrained status, `PUBLICATION_PRECLAIMED_NO_RECEIPT_WRITE_DISPATCHED`. The row binds the installation, successor transaction, canonical witness-request SHA-256, successor receipt SHA-256, generation, signed revision, a SHA-256 of **every** original Slice 78 reservation field, and the reserved independent-evidence SHA-256.

The `preclaim_once()` path requires all of the following:

1. Strict canonical witness-request parsing; reject malformed bytes, changed successor identity, noncanonical serialization and any altered reservation field/status/authority.
2. Fresh independently authenticated service permission for `preclaim_publication_once`. No locally created Python dataclass can establish that the actor is protected.
3. A renewed independent service callback producing `IndependentFinalizationEvidence` with exactly matching original preimages and a literal `True` for stopped-writers, physical re-audit and operator consent. In production the callback must **actively** reverify its physical source and all protected preimages, rather than copying the old reservation or trusting a classroom-supplied report.
4. Inside `BEGIN IMMEDIATE`, read back the actual service-owned Slice 78 reservation through its own authorized `observe_finalization` operation. Its value must equal the supplied untrusted reference; a fabricated reference does not create a row.
5. Refuse any existing preclaim row for the installation, even when byte-identical. Insert the immutable row and `COMMIT` once. No reset, UPDATE, DELETE, compensating transaction or automatic retry method is exposed.

`observe()` requires separate `observe_publication_preclaim` authorization, validates persisted data and returns only diagnostic metadata. A post-COMMIT lost acknowledgment can leave a valid preclaim despite a caller exception. The subsequent step must **inspect independently, reconcile the physical receipt and retained capsule, and decide whether an external publication could have occurred**. Absence of a preclaim after a crash must never be interpreted as proof that no independently initiated side effect occurred unless deployment can establish strict writer ordering.

## Important production limitations

Python callbacks and data structures do not provide OS-level account isolation, durable coordinator lease, privileged filesystem control, independent service keys, stopped-process certification, package integrity, operator identity, or consent. SQLite autocommit/transactional operations do not make the *separate* active-receipt filesystem and database one atomic transaction; Windows rename does not alone provide a multi-file crash-safe commit. A malicious same-user writer can evade cooperating locks. These controls require real independently administered deployment and testing.

The static `IndependentFinalizationEvidence` currently has no built-in proof of when an observation was made; production must enforce per-operation freshness, anti-replay, and secure reader ownership outside this library. Slice 79 never treats its hash agreement as a cryptographic signature or launch grant. A future publisher must address robust write-ahead receipt staging, pinned signed-head rechecks, durability, retained predecessor evidence, capsule retention across crash windows, idempotent reconciliation, and explicit terminal readiness. The preclaim itself is not a reason to delete the capsule.

## Follow-on boundary

Next implement a separately authorized, protected **receipt-writer protocol** that consumes the durable preclaim with independent OS custody and preserves an unambiguous recovery strategy. Do not implement direct classroom-local active-receipt writes, unguarded rollback, capsule deletion, or launch activation as a shortcut. The preclaim must remain one-shot even when the writer has never run.
