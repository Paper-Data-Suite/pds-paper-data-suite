# Issue #49 — Slice 50: challenge-bound service recovery observation

## Purpose and authority boundary

Slice 46 compared local observations against `WitnessWriterQuiescenceState`, a **plain Python dataclass** that a caller could fabricate. Slice 48 then correlated these observations into a **non-authorizing** handoff. This slice defines a *short-lived, independently signed, challenge-bound* service statement to distinguish a cryptographically verifiable service observation from a client-supplied object.

It does **not** authorize rollback, switching a launch pointer, changing installed software, clearing a pending capsule, committing an active receipt, or launching. The returned `VerifiedRecoveryServiceAttestation` has explicit `NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY`. Signed observation is *not* a capability token. No teacher CLI integration, witness mutation, local file writes, signing key material, production service provisioning, or change to launch eligibility is included.

## Independent trust prerequisites

1. The **service** provisions an Ed25519 signing key that never ships with Suite, its packages, local teacher workspace, or downloaded records. The verifier obtains the corresponding public key from an independently authenticated and protected policy, **not** the presented record.
2. The service obtains `WitnessWriterQuiescenceState` directly from its protected durable ledger, on the same exclusively managed CAS-writer admission path. That service deploys real worker termination/join and excludes direct-store bypasses. A callback and a signed assertion cannot establish this topology by themselves.
3. The consumer issues a new, unpredictable, single-use 32-byte challenge for **each** observation. A fixed test challenge is not acceptable in production. Client wall time is trustworthy enough to enforce the narrow issuance/expiry window; a hostile local clock may defeat freshness.
4. The service must obtain fresh, independently verified signed checkpoint state before signing. Signing the service's stored terminal row without revalidating the current witness head may be stale. This Python issuer cannot prove whether that happened.
5. Verifiers must redo independent physical installed-byte and active-receipt checks and never treat the attestation as an activation grant.

## Wire contract

A strict canonical JSON envelope (maximum 8192 bytes) contains only `record_type`, `schema_version=1`, `payload_b64`, and `signature_b64`. The canonical JSON payload (maximum 4096 bytes) binds the exact serialized Slice-42 request SHA-256, installation ID, transaction ID, predecessor/successor receipt digests, expected witness ID, signed successor revision, successor generation, a literal service status, a *non-authorizing* authority label, UTC issue and expiration times, and the caller's challenge.

Ed25519 signs the exact bytes `b"pds-evergreen-service-recovery-observation-v1\0" + canonical_payload` (domain separation). The current fixed lifetime is **60 seconds**, including no permitted future issuance and rejection at expiration. Unknown fields/schemas, noncanonical JSON/base64, replay with a different nonce, wrong trusted key, wrong request, altered signature, expired issuance, and inconsistent service status fail closed.

`issue_service_recovery_attestation` requires a supplied `sign(message)` callback; it never generates, persists or accepts a public key as proof of trust. This is an **adapter for an independently provisioned service**. `verify_service_recovery_attestation` requires an independently pinned 32-byte Ed25519 key. Neither operation reaches the network or filesystem, or changes checkpoint/receipt state.

## Accepted classification

Only `SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED` for the exact candidate successor is signable. The signed result is `SERVICE_SIGNED_SUCCESSOR_OBSERVATION_ONLY`; it is not final authority. Pending, predecessor-signed, unknown, or competing writer states are not signable in Slice 50. A signed successor observation does not mean recovery is complete.

## Remaining work

- Deploy independently isolated service writer authority, key lifecycle/rotation/revocation and a protected challenge/response endpoint; no service endpoint is added here.
- Bind a freshly verified attestation into a **new** post-CAS coordinator that independently checks the signed witness head, physical bytes, journal/capsule identity, and operator approval at the time of action.
- Design a protected receipt commit and forward-only crash recovery protocol before any production activation.
- Cover real Windows x64/ARM64 installed-wheel acceptance and failure injection. Unit tests with synthetic signer/witness evidence **do not** prove independent deployment.
