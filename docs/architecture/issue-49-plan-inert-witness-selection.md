# Issue #49 — Slice 72: Plan-bound witness-gated inert selection

## Intent and authority boundary

Continue the Slice-64→71 independently authenticated composition flow into the **existing** Slice-40 reversible selection transaction. This stage deliberately does **not** activate, launch, commit a witness successor, publish an active receipt, or clear recovery. Its sole possible mutation (performed by the previously established selector) is to save a pending recovery capsule **before** atomically replacing a local, untrusted candidate-selection hint.

A selected candidate with an unresolved capsule must remain unlaunchable. The local selected pointer, returned Python dataclass, journal and after-the-fact inspection are not protected installation history and must never authorize production launch or rollback.

## Entry contract

`select_plan_bound_witness_inert_slot` requires an explicit, precise consent string: `SELECT_WITNESSED_PLAN_INERT_SLOT_PENDING_RECOVERY`, together with:

- The same authenticated registry/catalog snapshot and witnessed baseline used by the preceding plan.
- Slice-68 isolated installation, Slice-70 recorded journal and Slice-71 armed intent, with a strictly monotonically related predecessor and selected generation.
- Exact prepared record, registry/lock/module envelopes and independently signed native envelope.
- Independently pinned witness transport/key, old receipt, previous observation evidence and separate prior publisher envelopes.
- Explicit software/classroom roots, target component/version map, interpreter and platform, whole-second aware clock.

The prior observation-record digest in the journal is deliberately **not** the predecessor active receipt digest in the witness head; those are separate values and separately verified.

## Operational sequence

1. Reject absent consent, malformed inputs, changed plan/armed identities and previous receipt mismatch before any mutation.
2. Enforce ordinary, separate software and classroom roots. Require the exact `candidate-builds/<transaction-id>` path and an independent wheelhouse.
3. Refuse any existing pending recovery capsule. Require exactly the revision-2 `ACTIVATION_INTENT` journal with immutable input digests and previous-slot observation-record binding.
4. Reverify the complete signed plan, independently authorized candidate PDS wheels, transitive lock, staged pip inventory and root-signed native inventory through Slice-67.
5. **Delegate** all mutation to `select_witness_bound_candidate_slot`. It holds cooperating selection and journal locks, reauthenticates the prior and candidate installations, queries the fresh independent witness, checks replay/freshness and writes the recovery capsule **before** changing the inert pointer.
6. Afterward, inspect the selector result, pending capsule, current pointer and unchanged journal. Report an inert pending selection only if they agree exactly. A post-write discrepancy reports that explicit recovery is needed; it neither retries nor silently restores a pointer.

## Security and reliability limitations

The boundary is designed to fail closed and make interruptions visible. It is not an OS-protected atomic transaction against malicious same-user writers, nor does it create root signatures, durable witness CAS authority, a production launcher integration or a verified current installation receipt. A power failure between capsule persistence and pointer replacement, a lost remote acknowledgment, or a changed candidate requires explicit reconciliation using service-backed evidence. Offline rollback is disallowed when there is an outstanding successor proposal or uncertain witness commit.

**Follow-on work:** independently approved successor receipt draft/CAS, durable lost-ACK reconciliation, exact forward installed-byte requalification, protected active receipt/selection convergence, truthful rollback constraints, and installed teacher-facing launch/update acceptance.
