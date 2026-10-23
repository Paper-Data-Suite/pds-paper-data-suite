# Issue #49 — Slice 52: fresh, non-mutating attested recovery orchestration

## Decision

Slices 48 and 51 correlated supplied in-memory observations. An ordinary caller could fabricate `ForwardRecoveryObservation` and `ObservedForwardSuccessorBytes` values, even if the signed service statement was correctly verified. Slice 52 introduces **one optional read-only orchestrator** that calls the already qualified source inspectors itself rather than accepting caller-created local/byte observations:

`inspect_fresh_attested_forward_recovery(software_root, classroom_workspace=..., transaction_id=..., request=..., signed_service_envelope=..., challenge=..., pinned_service_public_key=..., witness_transport=..., pinned_witness_public_key=..., candidate=..., candidate_module_envelopes=..., trust=..., now=...)`.

No launcher, activation, CAS writer, receipt committer, rollback, capsule cleanup, or teacher-facing command is added. Historical Suite v0.1.0 behavior and the opt-in earlier functions remain unchanged.

## Ordered read-only boundary

1. Authenticate the Slice-50 Ed25519 service envelope with the exact canonical witness request, independently pinned service public key, fresh 32-byte challenge, and finite service signing window **before** local inspection or witness transport. Refuse a mismatched transaction.
2. Reconstruct a value-only service observation from authenticated fields. This is **not** a service-wide stopped-writer proof.
3. Call `inspect_pending_forward_recovery` to read the durable local proposal, pointer, journal, and recovery capsule under the existing cooperative locks, with a fresh signed witness-head challenge.
4. Recompute Slice-46 convergence from service and actual local results. Require an exact confirmed successor, never a possibly in-flight or predecessor head.
5. Call `requalify_witnessed_successor_bytes`, which repeats physical publisher/pip/native audits around another signed successor-head query and checks the durable proposal and local state again. Never execute installed candidate code.
6. Call `inspect_pending_forward_recovery` again after the physical audit. Refuse if the signed local observation differs from the first read.
7. Revalidate and correlate the signed envelope, local observation, and requalified installed bytes using the Slice-51 adapter. Refuse if the elapsed time budget exceeds 30 seconds. Return only `FreshAttestedRecoveryObservation` for review.

The expected observation contains **two direct local signed-head reads** and **one signed-head read inside the physical requalification** (which itself audits the physical stage twice). It does not count any underlying metadata/key refreshes.

## Hard security limitations

- The orchestrator does not own or protect the service signing key, service-wide writer gate, process supervisor, local installed files, OS ACLs, witness transport, or trusted publisher keys. Deployment must do that independently.
- Local selection and journal locks are cooperative and do not exclude hostile same-user or external writers. Three matching readbacks are a **sampled observation**, not a distributed transaction or physical quiescence guarantee.
- The caller-provided `now` and externally supplied challenge cannot by themselves prove true wall-clock monotonicity or nonce uniqueness. The elapsed budget only limits one execution; the deployment must supply an authenticated clock and unpredictable challenge.
- A returned dataclass is freely constructible. No consumer may interpret its contents as authorization to finalize an active receipt, clear the pending recovery capsule, switch launchers, or revert to a prior witness head.
- The original `restore_previous_selection` and `reconcile_witness_bound_selection_offline` remain guarded only by the Slice-49 **proposal-presence** interlock, not a global proof of no externally dispatched CAS.
- Nothing here certifies a real installed-wheel acceptance matrix, stable release provenance, Windows ARM64 path behavior, or safe teacher deployment.

## Remaining work

A genuinely protected updater requires independently deployed service-wide CAS writer isolation, authenticated operator intent, OS-protected physical installation and active receipt state, crash-safe forward-only reconciliation after a witnessed successor, real Windows installed-wheel tests, and final guarded CLI/doctor/launcher integration. **Do not activate a live launcher on the strength of this observation.**
