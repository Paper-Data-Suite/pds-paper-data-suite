# Issue #49 — Slice 76: plan-bound pinned successor forward-recovery inspection

## Decision and threat boundary

Slice 75 can independently fence/dispatch one service CAS and later observe a signed successor after service-asserted stopped writers. That observation is not proof that the inert local selection, pending recovery capsule, installed package bytes, and active installation receipt have converged. Slice 76 creates a **read-only plan-to-recovery inspection** that joins the exact Slice 73–75 plan request with the already implemented independently pinned Slice 56 remote recovery inspection. This is an additive opt-in adapter; it does **not** change the production launcher or update `pds doctor`, clear a pending capsule, write an active receipt, change a selection, mutate a classroom workspace, dispatch CAS, or authorize a rollback.

All locally held dataclasses, including `PlanSuccessorServiceSignedRecovery`, are **untrusted values**. The Slice 76 entry point reparses the canonical bounded witness request through the existing Slice 74/75 parser and requires exact agreement with its admission, terminal signed successor state, selected generation/stage, and the original predecessor digest. Only the signed-successor path qualifies for forward review. The predecessor-only state remains unresolved, with no automatic rollback authority.

## Reuse existing independent verification

After early rejection of forged and mismatched plan claims, Slice 76 delegates to `inspect_pinned_remote_forward_recovery()` (Slice 56), not a new cryptographic or byte-trust subsystem. Slice 56 fetches through the provisioned one-shot pinned-mTLS service client, checks the independent Ed25519 service signature and fresh random challenge, then invokes the Slice 52 read-only sequence: fresh signed local witness observation, convergence comparison, a physical publisher/pip/native stage audit before and after an independently signed successor observation, and repeated local signed-head readback. The established implementation verifies durable local proposal/recovery-pending state under cooperative locks. Slice 76 checks the resulting handoff against the canonical request and selected plan again.

A genuine service signature is still **not** proof that the service supervisor truly stopped all operating-system writers, nor that the local active installation is safe for launch. The deployment must independently provision service trust, secure key storage, authenticated operator consent, global writer isolation, protected software bytes, a stable clock, and bounded recovery windows. Python dataclasses and cooperating local locks alone do not provide these guarantees. No signed envelope or challenge may be constructed from teacher-writable metadata or caller-chosen request fields.

## Result and limitations

`PlanForwardRecoveryReview` contains exact, nonsecret identity and audit summaries only, with status `PLAN_SUCCESSOR_BYTES_REVIEWED_FORWARD_FINALIZATION_STILL_REQUIRED` and `NO_LAUNCH_ROLLBACK_SWITCH_RECEIPT_CLEANUP_OR_CAS_AUTHORITY`. The caller cannot interpret the review as an activation, receipt, or cleanup capability. A fresh review must be obtained at any eventual protected finalization boundary; this value is never a durable entitlement.

Next implementation must address independently protected physical selected-installation convergence and an atomic, crash-recoverable local active-receipt transition tied to a currently authenticated witness successor. Only after further verification and recovery-capsule reconciliation may a separate launch-eligibility decision be considered. Do not treat an already authenticated successor as permission to restore the predecessor pointer.
