# Issue #49 — Slice 47: post-CAS forward candidate-byte requalification

## Decision and scope

Introduce `requalify_witnessed_successor_bytes()` as an **opt-in, read-only recovery preflight** for a successor whose exact receipt is independently visible as a signed witness head. This addresses the previously unfilled boundary between Slice 46's service/local *metadata convergence* and the physical installed files that a future recovery coordinator would need to reconcile.

The function does **not** commit an active receipt, change the selected pointer, clear the recovery capsule, advance the witness, issue a launch token, invoke installed application code, or change production CLI/launcher behavior. It obtains and removes cooperating local lock files, but leaves the durable installation and classroom workspace unchanged.

## Preconditions and checks

1. Validate a `MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED` convergence observation, exactly typed bounded candidate envelope inputs, trusted signer set and whole-second aware clock. A convergence object is **caller-controlled data**, not an authenticated approval; the function must independently query the witness again.
2. Acquire cooperating **selection then transaction** locks and require the canonical durable Slice-43 successor-proposal file and unchanged Slice-40 recovery capsule, selected pointer, and revision-2 activation-intent journal. Reconstruct and compare the exact request and bound identities using the existing `_snapshot` and `_parse` checks.
3. Cross-check the convergence identity, transaction, request SHA-256, predecessor/successor receipt digests, witness generation/revision and all four candidate signed input digests against the exact proposed successor receipt. Require an ordinary child stage and wheelhouse, with no overlap.
4. Perform fresh candidate-stage audit using `audit_publisher_bound_pip_candidate()` (delegated publisher signatures, exact pip-installed bytes, root launchers) and `verify_signed_staged_native_evidence()` (root-signed native executable bytes). Require exact transaction, stage, wheelhouse, native payload digest, pip inventory digest, module publisher identities, root console targets and external distribution identities matching the successor receipt. Do not trust caller-provided audit summaries.
5. Under both locks, issue a **fresh signed witness challenge**. Require the successor digest at the expected witness revision (+1). A predecessor head, signer mismatch, transport error, stale revision or unknown head is a refusal.
6. Repeat the complete publisher/pip/native audits. Reject unequal observations, a conservative post-witness elapsed budget longer than 45 seconds, changed caller envelope dictionary, or any change in the durable proposal, pointer, capsule or journal during the audit.
7. Return only a typed ephemeral `POST_CAS_SIGNED_BYTES_OBSERVED_FORWARD_RECOVERY_STILL_REQUIRED` finding, with exact observed digests. This finding never grants permission to commit a receipt or execute code.

## Operational guarantees and missing authority

- The witness statement is separately signed, but its **independent custody, current revocation state, and service-wide writer exclusion** depend on operational provisioning. Slice 45's callback and Slice 46's convergence claims are not authenticated transport proofs by themselves.
- Signed-byte rechecks provide a bounded observation, not ongoing filesystem integrity. Cooperating lock files cannot stop malicious same-user writers, process injection, or privileged modification after audit. Protecting the actual physical deployment and receipt storage is still a separate engineering task.
- Signed metadata and exact pip/native file checks do not imply package code is harmless. This preflight never imports or executes the candidate.
- The 45-second monotonic budget is conservative relative to the 60-second signed witness statement lifetime, but depends on a trustworthy caller-supplied wall clock. It is not a replacement for trusted hardware time or protected execution.
- Crash or failure at any point leaves `ACTIVATION_INTENT` revision 2, the pending recovery capsule, and the proposed successor receipt unmodified. The previous software slot is not deleted or overwritten.

## Next boundary

A **protected deployment/active-receipt coordinator** must validate externally authenticated actor consent, service-wide CAS quiescence, protected physical installed state and immutable receipt custody across every crash point; then it can plan forward finalization. Neither the old nor successor head alone is sufficient. Physical Windows x64 and ARM64 qualification should precede production activation.
