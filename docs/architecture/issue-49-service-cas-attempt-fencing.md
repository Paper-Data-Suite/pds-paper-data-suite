# Issue #49 — Slice 44: independently operated CAS attempt fencing

## Decision and scope

Add a **service-side**, opt-in durable admission ledger for **one** external witness checkpoint CAS attempt per installation. This is necessary because the previous Slice-42 adapter may commit the successor and lose its acknowledgment, leaving both the local predecessor and the new external head in an ambiguous state. The Slice-43 durable local proposal does not fence an independently operating witness writer.

`WitnessCasFenceLedger` stores one strictly bound witness commit request identity before any service-side commit call. It uses the independently operated service's SQLite connection, `BEGIN IMMEDIATE` for each state transition, durable SQLite settings and a service-authenticated operation policy. It never stores witness signing keys, installs software, calls providers, writes classroom files, clears the pending selection recovery capsule, records a local active installation receipt, grants launch permission, or exposes an HTTP write endpoint.

## State machine

1. `PREPARED_NO_DISPATCH`: Service authorizes a canonical proposed successor request and creates an exact, installation-scoped reservation. A second reservation, even for another successor, is refused.
2. `CAS_MAY_HAVE_BEEN_DISPATCHED`: A separate, transactional update **precedes** the first and only call to the Slice-42 independently approved service-side CAS adapter. This state persists if the process crashes, signed verification fails, approval is denied, the witness refuses CAS, or an acknowledgment disappears. It is **not** inferred that a write happened; it is intentionally unsafe to infer it did not happen.
3. `PRIOR_SIGNED_STILL_UNRESOLVED`: A fresh pinned-key challenge confirms the exact previous witness head at the expected revision, but an external request may still complete later. **Not permission to roll back, release the installation fence, dispatch again, or certify the previous slot.**
4. `SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED`: A fresh signed head confirms exactly the proposed successor at the next witness revision. Monotonicity requires a protected forward reconciliation of physical software, pending capsule and local active receipt; no automatic old-pointer rollback is permitted.

The service DB row binds the exact SHA-256 of the canonical request bytes, both exact receipt digests, expected witness revision and last signed observation. Different-request admission, corrupt row contents, replayed dispatches and unexpected service identity all fail closed. A returned state always includes `NO_LAUNCH_OR_ROLLBACK_AUTHORITY`.

## Lost-ACK, outage and crash boundaries

- Crash before successful reservation: no CAS may be dispatched through the coordinator without a valid recorded reservation.
- Crash after reservation, before dispatch marker: no CAS has been invoked through this adapter. Manual service recovery is needed before any new attempt, not automatic reuse.
- Crash after dispatch marker, before/during/after external CAS: durable marker remains and **dispatch is never repeated**. Signed readback can record prior/successor without clearing the fence.
- Transport unavailable, forged signer, conflicting witness revision or divergent head: status stays unresolved. Never automatically retry a possibly sent CAS or assume an old head licenses rollback.
- Service process restart: reopening the independently administered SQLite ledger preserves the exact reservation/possible-dispatch state.
- Concurrent signed readback and service DB changes: reject the observation rather than overwriting state. A signed successor observation must never be downgraded to predecessor status.

## Trust boundary and limitations

This module cannot provision independent administration, private-key custody, OS-protected installation directories, a service-wide exclusive writer, or physical switchover. **All** paths that can advance `MonotonicCheckpointStore` must be routed through the same protected exclusive coordinator. Direct use of `commit_receipt()`, another service instance with uncoordinated writer privileges, malicious replacement of the SQLite file, or teacher-local invocation bypasses this fence. An `authorize` callback passed by the local Suite application does **not** satisfy the independent authority requirement.

The ledger deliberately provides **no `clear`, `unfence`, `retry`, `rollback`, or `launch` method**. A subsequent slice must implement a separately authorized service-wide writer shutdown/quiescence protocol and physical installation receipt finalization. A signed predecessor read **alone** is insufficient to fence an in-flight CAS; protected quiescence and signed state must both be established in that later protocol.

## Validation intent

Slice-44 regression tests use a real Ed25519-signed `MonotonicCheckpointStore`, a separate file-backed SQLite coordinator and deliberately constrained authorization doubles. They demonstrate the state machine, transaction order, replay refusal, process-restart persistence, simulated crash after preclaim, actual commit followed by lost acknowledgment, bad signer/outage refusal, and database corruption/drift handling. They do **not** certify independent service deployment, physical switch protection, general service-wide exclusion or teacher launch eligibility.
