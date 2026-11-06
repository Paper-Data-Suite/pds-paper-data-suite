# Issue #49 — Slice 82: protected local pre-write uncertainty barrier

## Decision and non-authority

Slice 81 persists a protected, one-shot deployment *intent* only; Slice 80 holds exact successor receipt bytes in a service-controlled SQLite database. Neither module writes an actual local active-receipt file. Slice 82 adds a separate immutable, service-side **PREWRITE uncertainty barrier** and a strictly read-only physical receipt classifier. It does not include, call, or authorize a local file writer; the `LOCAL_PREWRITE_UNCERTAINTY_ARMED_NO_WRITER_DISPATCH` marker does not assert that a write has occurred. It exists so that **a future** protected writer can never interpret the absence of an acknowledgment as permission to retry or rollback. Nothing here deletes the recovery capsule, changes a slot or journal, runs a launcher, invokes witness CAS, or permits classroom workspace mutation.

The barrier is intentionally *one per installation* and is never released in this slice. Even a still-visible predecessor after a crash cannot prove that a separate writer was not delayed or in flight. After an uncertain operation, retain the marker and use independent reconciliation rather than attempting a second write, an unsafe rollback, or a capsule clear.

## Durable marker and admission

`ProtectedLocalPrewriteUncertaintyLedger` accepts exactly a `ProtectedLocalReceiptDeploymentPlanner` from Slice 81 and shares its **same SQLite connection** with Slices 78–80. It provisions one table, `plan_local_prewrite_uncertainty_v1`, keyed by installation identity and constrained to its single status. Its record binds: installation and transaction; canonical request and successor SHA-256; successor generation and signed witness revision; canonical hash of **all** Slice-81 intent fields; Slice-80 receipt-record hash; exact predecessor-receipt digest; independently pinned target identity; retained recovery-capsule digest; and original local-snapshot digest. A forged caller dataclass cannot populate the missing service record.

`arm_once` first checks the canonical request, Slice-80 protected receipt, Slice-81 intent and all digest/status invariants. Before SQLite insertion it requires service-owned authorization for `arm_local_prewrite_once`. Under one `BEGIN IMMEDIATE` transaction it retrieves **the actual** protected reservation, publication preclaim, signed successor receipt and deployment intent. It refuses any missing, altered or existing marker. It renews independent service stopped-writer/installed-byte/consent evidence, reads protected physical predecessor and still-present capsule with independently controlled target configuration, checks the exact earlier local snapshot and refreshes the pinned signed successor witness readback. Only then does it insert the marker and `COMMIT` once. No filesystem write runs before, inside or after the transaction.

An uncertain SQLite acknowledgment triggers read-only observation, never automatic retry. The service must provision a real OS-level protection boundary, database durability, writer lease and key custody. Application code cannot establish these by `True` booleans, caller-supplied callback functions or cooperative local locks.

## Read-only post-uncertainty classification

`inspect_after_uncertainty` requires separate `inspect_local_prewrite` and `observe_local_prewrite` authorizations and rechecks the actual immutable service records. An independent physical reader must inspect **the configured protected target**, read any active receipt as bounded exact bytes (no symlinks/reparse points), and confirm the unchanged local proposal, selection, journal, and **still-present capsule**. A refreshed independent service read and signed next-head witness observation are mandatory. These are service boundary obligations; the Python callback contract does not prove OS isolation, freshness or atomicity.

The result reports one of four **non-authorizing** classifications:

- `PREDECESSOR_VISIBLE_NO_RETRY_AUTHORITY`: exact previous receipt still visible, but a future write may remain in flight; no retry, rollback, or capsule deletion.
- `SUCCESSOR_VISIBLE_RECOVERY_STILL_PENDING`: exact successor bytes visible, but durable publication and physical convergence are not established by one read; capsule retained.
- `LOCAL_RECEIPT_MISSING_MANUAL_RECOVERY_REQUIRED`: protected target absent; manual incident investigation.
- `UNKNOWN_LOCAL_RECEIPT_QUARANTINE_REQUIRED`: unexpected or corrupted bounded content; preserve evidence and quarantine launch.

No classification returns a bearer grant or writes any local file. Unknown/missing bytes do **not** qualify as either predecessor or successor. Readback with an unsafe target, changed capsule, missing independent writer fence, unknown signer or future witness revision fails closed without a classification.

## Remaining limitations and next boundary

This slice intentionally does not implement the privileged local writer or a cross-database/filesystem transaction. Atomic SQLite insertion **does not** atomically update a Windows active-receipt file. Process crashes, power loss, Windows sharing/reparse behavior, durable directory flushes, malicious same-user replacement, ACL bypass and writer-fence lease expiration remain deployment concerns. Synthetic test readers are not substitutes for independently deployed service infrastructure.

Slice 83 should design a protected, strictly gated local writer dispatch that first verifies the durable Slice-82 marker under the same independently held writer fence, uses same-filesystem staging and bounded fsync/readback where supported, refuses automatic re-dispatch, and preserves capsule and predecessor evidence until a subsequent independently signed **local convergence** transaction. Do not use the Slice-82 marker by itself as authority to write, launch or clear anything.
