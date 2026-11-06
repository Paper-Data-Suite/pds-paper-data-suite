# Issue #49 — Slice 74: Service-side admission of a plan-bound successor

## Decision

Compose the Slice-73 **unsubmitted** `PlanSuccessorDraftReview` with two **already existing, independently operated** state machines: the Slice-44 `WitnessCasFenceLedger` and the Slice-45 `WitnessWriterQuiescenceGate`. This is strictly an admission/reservation boundary, **not** a witness commit, switch, local receipt, recovery completion, or launch authorization. No local command, launcher change, HTTP write endpoint, root-key registration, or software-installation mutation is introduced.

`admit_plan_successor_to_independent_service()` must run inside a separately administered witness/deployment service. A teacher-controlled process cannot create a legitimately independent service by supplying a callback, SQL database, or public key. The service must control the authentication context, protected state, physical deployment checks, installed software ownership, operator consent, CAS writer exclusivity, and SQLite durability. The concrete Python type of a `PlanSuccessorDraftReview` is **not** authentication.

## Exact acceptance boundary

1. Strictly validate the Slice-73 review fields and fixed no-authority status; parse its **exact bounded canonical request bytes**, both canonical active-installation receipts, predecessor receipt digest, transaction ID, consecutive generations, installation identity, witness revision, and request SHA-256. No review field is trusted merely because it appears in a dataclass.
2. Invoke a service-administered `IndependentPlanPredecessorReader`. Its `IndependentServicePredecessor` must match the **service-owned** pinned predecessor installation, witness identity and revision, prior transaction ID, generation, and exact receipt digest. A record copied from the client's own request is not service-owned evidence.
3. Require `IndependentCommitApproval` to return **exactly** `True` after the service independently verifies protected installed candidate bytes, the pending recovery capsule and inert selection, the authorized operator's explicit approval, and installation-specific custody. A local `True` callback is only a test double; it does not prove those operational conditions.
4. Require that the gate and CAS ledger share the **same** service-owned connection and ledger. `ledger.reserve()` durably writes an installation-scoped `PREPARED_NO_DISPATCH` record for this *exact* canonical request. A second reservation, including a competing successor, is refused.
5. Read the reservation back, then call `gate.admit()` to durably record `ADMITTED_NOT_DISPATCHED` behind the existing cooperating-writer barrier. Re-read both exact records and require identical identities and statuses.
6. Return only `SERVICE_APPROVED_PLAN_SUCCESSOR_ADMITTED_NO_CAS_DISPATCH` with `NO_CAS_DISPATCH_RECEIPT_PUBLICATION_RECOVERY_CLEAR_OR_LAUNCH`. The state contains **no** executable authorization, approval credential, or CAS dispatch capability.

The service is responsible for ensuring that all CAS writers use the same exclusive gate/ledger. SQLite `BEGIN IMMEDIATE` protects cooperating instances using that database; it cannot fence an external writer that has direct access to the checkpoint store. The service must protect durable DB storage and cannot use user-controlled workspace files as the service ledger.

## Failure and restart semantics

- **Before reservation**: invalid metadata, absent/different service predecessor, missing approval, wrong identity or unavailable service components cause refusal and no new service row.
- **After reservation but before writer admission**: any readback mismatch, writer gate failure, process crash or authorization failure leaves `PREPARED_NO_DISPATCH` in place. **Do not delete, release, automatically retry, or mark that request successful.** Independently reconcile the installation under the service's incident procedure.
- **After writer admission**: readback failure, crash or loss of the return value leaves the persisted gate `ADMITTED_NOT_DISPATCHED` and fence `PREPARED_NO_DISPATCH`. An attempted replay is refused. No CAS has been dispatched *through this coordinator*.
- **No forward commit implied**: Slice 74 never invokes `ledger.dispatch_once()`, `gate.dispatch_once()`, `MonotonicCheckpointStore.commit_receipt()`, or a witness HTTPS write. CAS dispatch and signed-head reconciliation require a separately reviewed follow-up boundary. A predecessor head visible later is not alone permission to roll back.

A durable reservation is deliberately sticky: the coordinator does not implement compensating deletion on a partial failure because such a deletion could falsely reopen a contested successor transition.

## Privacy and rollout

The new code stores only the preexisting installation-scoped service hashes/revisions and gate status. It does not read or change classroom data, student records, the Core workspace, program settings, local selection pointer, pending capsule, wheelhouse, or installed packages. Do not use classroom folders as SQLite storage. Approval and predecessor callbacks in tests are deterministic stand-ins only, not proof of a physically isolated witness service. No teacher-facing release or activation claims are justified by this slice.

## Next boundary

A subsequent slice may implement an *independently authorized* service dispatch path using the already admitted request, writer-quiescence shutdown, durable once-only possible-dispatch marker **before** CAS, a fresh signed readback, lost-ACK fencing, and forward/recovery state reconciliation. These must be independently qualified; Slice 74 only establishes durable non-dispatched admission.
