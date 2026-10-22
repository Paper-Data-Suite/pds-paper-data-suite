# Issue #49 — Slice 45: service-owned CAS-writer quiescence handoff

## Decision and authority

Introduce `WitnessWriterQuiescenceGate` as an **opt-in, independently administered witness-service building block** that closes CAS admission before a supervisor stops/joins outstanding writers. It sits *in front of* the Slice-44 `WitnessCasFenceLedger.dispatch_once()` and shares the ledger's exact SQLite connection. Its state machine is durable and transactionally serialized for cooperating service writers; it cannot stop processes or establish independent administration by itself.

There is **no Suite CLI integration, no teacher-local witness write endpoint, no active-receipt write, no production launcher change, and no removal of the pending recovery capsule**. Nothing grants automatic old-pointer rollback, release of a witness fence, successful activation, or teacher-launch eligibility. The persisted and returned authority label is `NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY`.

## Preconditions

- Service-owned, durable SQLite database and authentication policy. The gate and Slice-44 ledger **must share the same connection**; per-installation transitions use `BEGIN IMMEDIATE` and compare-and-set. Durable SQLite depends on service provisioning, protected directory, non-adversarial disk and WAL/synchronous policy.
- Exact canonical Slice-42 `WitnessCommitRequest`, a Slice-44 `PREPARED_NO_DISPATCH` ledger reservation, and a service-authenticated operation context. An untrusted local receipt proposal is not a service credential.
- **All** potential `MonotonicCheckpointStore.commit_receipt()` writers for an installation must be under the same independently administered admission/stop authority. If even one direct store writer or another service instance can bypass the gate, its observation cannot establish quiescence. The code does not enforce this deployment topology.

## Service state machine

1. `ADMITTED_NOT_DISPATCHED`: Admit one request already reserved with the matching Slice-44 ledger. A competing request, duplicate admission or stale context is refused.
2. `CAS_MAY_BE_IN_FLIGHT`: Atomically and durably mark dispatch possible **before** invoking `WitnessCasFenceLedger.dispatch_once()` once. Crashes and errors preserve the possible-in-flight marker. No automatic retry or re-admission exists.
3. `STOP_REQUESTED_NO_DISPATCH` / `STOP_REQUESTED_MAY_BE_IN_FLIGHT`: Atomically close admission before asking a protected supervisor to stop/join all outstanding CAS workers. Further gate dispatches fail. The distinction records whether a dispatch could have begun; no timeout converts either status into proof of shutdown.
4. `SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED`: A separately provisioned supervisor asserted that **all** writers had ceased, and a *fresh challenge-bound* signed witness head matched the exact prior receipt at the original revision. Still **no rollback authorization**: supervisors or service topology may be misconfigured, or other write paths may exist.
5. `SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED`: The same service-side stop assertion plus signed observation identifies exactly the successor at expected revision +1. Protected **forward** software/receipt reconciliation is still mandatory. Do not reset the witness or silently restore an old pointer.

The final statuses are **terminal** in this slice: no reopen, retry, delete, or fence-clear operation. `request_stop()` is idempotent once stopping begins. `certify_stopped_and_observe()` requires the stop request, an externally implemented `IndependentWriterSupervisor` returning literal `True`, and a fresh signed head via the Slice-42 verifier; it rechecks the database snapshot after those callbacks and refuses a concurrent modification. A client-provided callback returning `True` is not *evidence* of a stopped process; it is a test double unless an independently administered service provisions and enforces it.

## Failure boundaries

- Crash before admission → no gate dispatch. Crash after admission → single request recorded; no safe automatic restart/dispatch.
- Crash after possible-dispatch marker → durable `CAS_MAY_BE_IN_FLIGHT`; the Slice-44 ledger may or may not have committed. Stop is required before signed readback, and never automates rollback.
- Stop request races a previously admitted worker → the service supervisor must stop/join it; local transaction locks serialize only the gate's states, **not** physical process lifetime.
- Supervisor unavailable/denied, wrong signer, unknown signed head, outage, competing database writer → refuse final observation and retain stop state. The caller must not infer no pending CAS from a visible prior head.
- Process restart → service SQLite row preserves admission/stop/observed state. No lease expiry, clock-based abandonment, blanket reset or success assertion.

## Remaining prerequisites

Before treating any signed predecessor plus stop status as *safe offline rollback*, build and qualify real protected service-wide admission authority (including direct-store writer exclusion and worker termination), prove no external writes remain, verify predecessor installed bytes/active receipt, and obtain authorized recovery. After a signed successor, independently verify protected candidate bytes and active receipt and reconcile the local journal/capsule **forward**. Further slices must physically test these distributed crash boundaries on Windows. Unit tests for this protocol **do not** establish those operational guarantees.
