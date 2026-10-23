# Issue #49 — Slice 51: verify service attestation at recovery-handoff consumption

## Purpose

Slice 50 issued and verified a short-lived signed service writer-quiescence observation. Slice 48 still accepts a plain in-memory `WitnessWriterQuiescenceState` with no provenance. **Slice 51 adds an opt-in, read-only adapter** that verifies the Slice-50 envelope against a fresh caller-generated challenge and an independently pinned Ed25519 service key **before** reconstructing that value for Slice-46 convergence and Slice-48 handoff checks.

There is **no trusted-launch state**, no active-receipt commit, no pointer update, no cleanup of the pending recovery capsule, no witness write, and no teacher-facing CLI activation. The returned object can be freely fabricated by a caller and is never a credential or an operation token.

## Contract

`inspect_attested_forward_handoff(request, signed_service_envelope=..., challenge=..., pinned_service_public_key=..., now=..., local=..., requalified=...)`:

1. Type-check supplied observation objects and require raw service-envelope bytes.
2. Verify the Slice-50 domain-separated Ed25519 signature against an **externally pinned service key**, a new unpredictable 32-byte challenge, exact canonical Slice-42 witness request, installation, transaction, successor digest/generation, and bounded issued/expiry times. The 60-second statement window is checked by the existing verifier.
3. Build `WitnessWriterQuiescenceState` solely from **verified signed fields**, with the exact successor-stopped status. Ignore/reject any caller-supplied plain service state or precomputed convergence object; neither is a parameter.
4. Recompute `compare_recovery_convergence` using the supplied local Slice-43 signed-head observation. A predecessor, conflicting revision, generation, digest, or unknown status fails closed.
5. Correlate Slice-47 requalified installed bytes through `prepare_forward_recovery_handoff`. A mismatched stage, native digest, pip digest, generation, transaction, status or authority fails closed.
6. Return `AttestedForwardHandoff` containing the verified service statement, a bounded forward handoff, and the SHA-256 digest of the signed-envelope bytes for operator correlation only.

All incoming dataclass objects, including `ForwardRecoveryObservation` and `ObservedForwardSuccessorBytes`, can still be forged. Neither this adapter nor the signature guarantees that the service genuinely stopped every writer, that the signing key was administered independently, that witness/local head observations remain fresh, or that installed bytes have remained unchanged. No byte-equivalent hash supplied by an untrusted caller creates independent trust.

## Security and lifecycle boundaries

- Production deployment must generate its **own fresh challenge**, own the service trusted-key policy outside writable local receipt bytes, and obtain a real remotely signed service response. Passing a local test double is not a production trust boundary.
- A protected coordinator must independently isolate all CAS writers, check the current signed witness, requalify candidate files under suitable OS protections, authenticate authorizing operator intent, and establish crash-safe forward receipt/pointer reconciliation before any launch/receipt operation can be exposed.
- A verified successor head requires **forward-only recovery**, never restoring an old receipt/head from local metadata. The Slice-49 proposal interlock is only a local defense; it is not sufficient for global CAS serialization.
- No caller-visible object is permitted to authorize physical activation, rollback, cleanup, package execution, or release of a CAS fence.

## Scope

Four additive files only: this architecture note, validation note, a new production adapter, and synthetic regression tests. Prior modules and historical Suite v0.1.0 behavior remain unchanged.
