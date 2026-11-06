# Issue #49 — Slice 75: one-shot service dispatch and signed recovery

## Decision and trust boundary

Slice 74 deliberately stopped at an independently provisioned service-owned `PREPARED_NO_DISPATCH` fence plus `ADMITTED_NOT_DISPATCHED` writer gate. Slice 75 connects that exact admission to the existing Slice 45 → Slice 44 → Slice 42 one-shot CAS path. The service calls `dispatch_admitted_plan_successor_once()` only with **its own** witness checkpoint store, pinned verifier key, independently authenticated service context, predecessor expectation, deployment approval, and exclusive writer supervisor. The caller's `PlanSuccessorDraftReview` and `PlanSuccessorServiceAdmission` are both untrusted reference metadata, **not approval or dispatch credentials**.

This remains an opt-in service-side Python adapter; there is **no teacher-facing CAS command, HTTP write route, software installation, locally published active receipt, recovery-capsule deletion, automatic retry, or production launch permission**. A Python callback constructed by a classroom process does not satisfy service independence. Production must provide independently isolated key custody, protected physical installation checks, operator consent, durable SQLite and checkpoint store, and assurance that **all** witness writers use the one gate.

## Dispatch order

1. Reparse the canonical bounded Slice 73 witness request and both receipts, reconstruct the exact expected Slice 74 admission record, and reject altered fields, booleans masquerading as revisions, missing service components and a different ledger/gate connection.
2. Independently inspect the service ledger and gate for matching request hashes, generations, `PREPARED_NO_DISPATCH` and `ADMITTED_NOT_DISPATCHED`. A later or divergent status is a replay/uncertain operation, not permission to dispatch again.
3. Recheck the **service-owned** pinned predecessor identity and independently administered physical deployment + operator approval. These checks occur again even though Slice 74 performed them at admission; the Slice 42 adapter also validates approval under a fresh signed predecessor.
4. Delegate exclusively to `WitnessWriterQuiescenceGate.dispatch_once`: it commits `CAS_MAY_BE_IN_FLIGHT` in SQLite **before** invoking the `WitnessCasFenceLedger.dispatch_once` adapter, which commits `CAS_MAY_HAVE_BEEN_DISPATCHED` **before** calling the Slice 42 witness checkpoint CAS. Every exception after the writer preclaim leaves uncertainty and blocks dispatch replays. Only the protected checkpoint store may advance the witness head.
5. If and only if dispatch returns normally, check both durable records and return an **unconfirmed** `SERVICE_CAS_RETURNED_SIGNED_READBACK_AND_RECOVERY_REQUIRED` observation. A return is not a signed acknowledgment, nor proof that software and local receipts have converged.

No compensation, deletion, rearming, or automatic second attempt follows any error. A crash between writer preclaim and CAS-fence preclaim leaves `CAS_MAY_BE_IN_FLIGHT` with a `PREPARED_NO_DISPATCH` fence, rather than falsely claiming a completed CAS.

## Independently fenced signed recovery

`reconcile_admitted_plan_successor_signed_head()` requires a previous possible-dispatch gate marker. It closes writer admission durably via `request_stop` and calls the **independently administered** supervisor that must stop and join all checkpoint writers across service processes. The preexisting gate then issues a **fresh challenge-bound, pinned-key signed witness observation** and stores one of:

- `SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED`: predecessor observed after service-asserted shutdown; **no automatic rollback**, no re-dispatch, no unfencing.
- `SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED`: successor observed; protected forward-only physical and receipt recovery remains mandatory before launch.

If the independent CAS fence progressed to a possible-dispatch state, the coordinator also asks it to record **its own** signed readback and refuses inconsistent hashes/revisions. If the fence is still `PREPARED_NO_DISPATCH` in the writer-preclaim crash window, it stays prepared; no witness write is invented. Service denial, missing supervisor, signer mismatch, divergent head, outage, or inconsistent durable readback leave the barrier closed and require incident reconciliation.

The recovery observation may be resumed **read-only** after the gate has already persisted one of the two terminal stopped states (for example, after a crash between its signed observation and the CAS fence observation). Such resumption independently verifies writer shutdown and obtains a *new* pinned signed head before inspecting the fence; it never reopens gate admission or dispatches CAS. A contradictory later witness head fails closed.

The returned object always contains `NO_RETRY_ROLLBACK_ACTIVATION_RECEIPT_PUBLICATION_OR_LAUNCH`. Neither a prior nor a successor signed head proves the selected installation's package bytes remain valid. Physical verification, local receipt finalization, pending-capsule reconciliation, and teacher launch readiness remain subsequent bounded work.

## Limitations and negative acceptance

These coordinators cannot prevent an external privileged writer from bypassing their SQLite fences. They do not create a durable user-consent record, certificate/policy infrastructure, actual shutdown/OS-level process joining, or a production service deployment. Tests use synthetic, bounded receipts and in-memory independently signed checkpoints with deterministic stand-in policies; they prove code-level ordering and refusal paths, **not independently administered physical acceptance**. An offline classroom path continues unchanged, and no classroom workspace is touched.

Next: resolve signed observed successor and predecessor branches with the established forward-byte-requalification, verified-physical-recovery, active-receipt/slot-convergence, and teacher-visible completed-update contracts. Do not conflate witness CAS with those steps.
