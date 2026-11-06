# Issue #49 — Slice 84: protected post-dispatch convergence and crash classification

## Boundary

Slices 78–82 establish immutable independently administered finalization, publication, service receipt, local deployment, and prewrite uncertainty records. Slice 83 **durably commits a dispatch claim before** invoking its separately operated filesystem writer once. A returned call, an exception, or a missing acknowledgment is never permission to retry or roll back. A callback return is not evidence that no writer remains in flight.

Slice 84 introduces `ProtectedLocalConvergenceCoordinator`, sharing the **exact SQLite connection** of Slices 78–83. It provides two separately authorized entry points: read-only `inspect` and one-shot `certify_once`. It does **not** implement a privileged Windows receipt writer, deletion of `pending-slot-recovery.json`, local selection/journal mutation, service re-dispatch, launcher readiness, package execution, witness CAS, rollback or an untrusted HTTP/CLI mutation endpoint.

## Protected prerequisites and no-inflight proof

Both entry points require the exact canonical request, original reservation, publication preclaim, protected successor receipt record, prepared local deployment intent, armed prewrite marker and durable dispatch claim. A local dataclass cannot substitute for a service row. Under `BEGIN IMMEDIATE`, the coordinator re-reads all protected rows via their independently authorized read paths, revalidates the immutable hashes/statuses and refuses any missing or divergent identity. This database lock coordinates *service database* access only, **not** the external filesystem; the production service must hold a separate privileged OS/process-wide installation fence across the entire inspection sequence.

The independently provisioned `IndependentNoInflightReader` reports exactly bound installation, transaction, dispatch-claim hash, pinned target hash, protected writer-fence digest and SHA-256 binding the independently reported writer-fence and termination-evidence digests. It must assert literally `True` for termination of all earlier writer operations, exclusive operating-system fencing, no unaccounted writer in flight, target durability check and physical-byte re-audit. A local or caller-selected callback carrying these booleans is **not** independent evidence. The production service must determine the full writer set, revoke outstanding leases, validate the service identity and maintain the exclusive lock so that a delayed writer cannot replace the receipt after readback.

In addition, the coordinator freshly checks the independently administered service evidence, exact pending capsule/proposal/selection/journal hashes, protected ordinary-file identity, installed-byte audit and a challenge-bound, pinned-key signed successor witness head at the expected revision and digest. A signed witness proves logical head continuity; it does not itself prove physical installation or durable filesystem semantics.

## Four read-only classifications

`inspect` obtains the protected basis and no-inflight evidence, then classifies the current independently read receipt as exact predecessor (`PREDECESSOR_VISIBLE_NO_RETRY_AUTHORITY`), exact successor (`SUCCESSOR_VISIBLE_CONVERGENCE_NOT_YET_AUTHORIZED`), missing (`ACTIVE_RECEIPT_MISSING_MANUAL_RECOVERY_REQUIRED`) or unknown (`UNKNOWN_ACTIVE_RECEIPT_QUARANTINE_REQUIRED`). The result carries `NO_RETRY_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS_AUTHORITY`. It performs no write and does not update a protected terminal state.

A missing/invalid no-inflight proof, loss of privileged reader access, unknown target identity, capsule drift, witness failure or invalid protected basis **refuses** classification. None of these outcomes authorizes a second dispatch, receipt overwrite, capsule removal or rollback.

## Immutable convergence observation

`certify_once` is independently authorized as a distinct service operation. It demands exact successor bytes on its initial local readback, then a fresh signed witness challenge and **a second independently fenced local readback**, with the same full no-inflight evidence and successor digest. Both must agree before inserting a single immutable row into `plan_local_convergence_v1`, under one service SQLite transaction. The row includes transaction identity, request and receipt SHA-256, successor generation/revision, dispatch-claim hash, target identity, retained capsule SHA-256 and SHA-256 binding the independently reported writer-fence and termination-evidence digests. Its only status is `LOCAL_RECEIPT_CONVERGENCE_RECORDED_CAPSULE_RETAINED`; its authority string explicitly forbids retry, cleanup, launch, switch, rollback and CAS.

An existing record is never replaced or re-certified. A crash or unknown SQLite COMMIT outcome demands **read-only service inspection**; never issue a second certification automatically. A durable convergence row does not prove the capsule is safe to remove *later* without new separately authorized checks. It does not clear earlier one-shot barriers.

## Deployment blockers

Synthetic test readers and a local SQLite database cannot establish real Windows ACL/handle custody, anti-symlink/reparse traversal, surviving process fences, `FlushFileBuffers` and directory durability, crash/power-fail guarantees, retained operator consent, an authenticated independently administered witness, or nonrepudiable service evidence. Production completion requires a privileged writer acceptance campaign and fault injection across every crash boundary. No application should treat this slice's record as an activation or launcher grant.

## Next boundary

Design a separate protected **capsule-retention clearance preflight** and ultimately guarded readiness/launch state, with fresh independently observed installed bytes and no writers in flight. Do not combine clearance or launch with this convergence record.
