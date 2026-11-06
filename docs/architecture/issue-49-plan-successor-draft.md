# Issue #49 — Slice 73: plan-bound successor review handoff

## Position in managed-update protocol

Slices 66–70 verify a complete plan, install an isolated candidate and record an independently signed native-evidence-qualified `candidate_verified` journal. Slice 71 arms `activation_intent` only after independent witness and predecessor validation. Slice 72 changes only the inert selection hint, writing its recovery capsule first. Slice 73 prepares a **non-authorizing, unsigned witness commit request** for that precise selected candidate and its independently witnessed predecessor.

The new `draft_plan_bound_successor_commit_request(...)` wraps—not substitutes for—the existing locked, doubly audited `draft_witness_bound_successor_receipt(...)` from Slice 41. It consumes the typed Slice 68, 70, 71, and 72 observations as *identifiers to cross-check*, not as trust anchors. Each operation must receive fresh authenticated catalog/witness evidence, exact signed envelopes and previous-slot bytes. An exact `activation_intent` revision 2 journal, inert candidate pointer and pending rollback capsule are required.

Before requesting a successor draft, the wrapper repeats the authenticated plan-to-installed-stage audit from Slice 67. The legacy drafter then independently audits both old and new installed compositions, checks the current witnessed predecessor while holding the cooperating selection/journal locks, and emits canonical **receipt proposal bytes in memory** only.

The adapter checks the resulting transaction, generations, receipt bytes/hashes, wheelhouse and stage identities, native and pip inventory digests, and independent witness revision. It calls `make_witness_commit_request` and `serialize_witness_commit_request` only for **an unsubmitted proposal**, and compares the journal, pointer and recovery capsule again before returning.

## Explicit non-authorities

- Never sends the proposal to an external service or calls a CAS endpoint.
- Never signs a receipt or self-authorizes a signer, issuer, witness, or writer.
- Never changes active receipt, selection, journal, recovery capsule, installed files or classroom workspace.
- Never starts a candidate, grants production launch privileges, or announces update success.
- Does not automatically retry, rollback or clear pending recovery after any mismatch.
- A caller-supplied consent phrase is an explicit operator-review interlock, **not** service-owned physical activation approval.

The independent witness writer still must enforce its own identity, authorization, independently protected installed-code evidence, durable once-only CAS fence, and fail-closed lost-ACK reconciliation. A service must not interpret this serialized proposal as a bearer token or commit approval. Same-user filesystem locks and post-audit observations are not a security boundary against malicious local writers.

## Recovery and next boundary

The previous selected stage remains intact. The recovery capsule is left in place even after this successful in-memory draft. Subsequent work must integrate separately approved witness CAS and reconciliation, with explicit service evidence before any local receipt publication or production launch. No optimistic rollback after a potentially submitted successor.
