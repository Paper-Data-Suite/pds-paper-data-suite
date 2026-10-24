# Issue #49 — Slice 55: pinned HTTPS recovery-observation client

## Purpose and scope

Slice 54 offers a separately provisioned, mTLS-authenticated HTTP host for `POST /v1/recovery/service-observe`; Slice 55 adds a complementary **opt-in one-shot client** for obtaining its signed observations. `ProvisionedRecoveryObservationHttpsClient.fetch(request, now=...)` returns `SignedRecoveryServiceExchange(challenge, signed_envelope, verified)` for subsequent Slice-52 read-only inspections. No Suite teacher CLI, launch switch, CAS dispatch, rollback, installed-receipt commit, state cleanup or implicit networking is introduced.

## Source of trust

The deployer supplies a fixed canonical `https://` DNS origin, CA PEM, separately pinned SHA-256 CA file hash, mTLS client certificate/key paths, independently pinned Ed25519 **service observation signing key**, and bounded timeout. This uses the existing Slice-35 strict hostname/origin parser and ordinary-file/reparse checks. The CA PEM bytes are pinned and loaded as `SSLContext(PROTOCOL_TLS_CLIENT)` trust input with `CERT_REQUIRED`, hostname checking and TLS 1.2 minimum. Certificate and private-key paths must be ordinary files; OS permissions and key lifecycle are deployment obligations. No arbitrary proxy, redirect, remote path, package repository or `PATH` executable is accepted.

The client **generates a new cryptographically random 32-byte challenge** inside each fetch, serializes the canonical Slice-53 service-observation request, and makes one HTTPS POST. It never follows redirects or retries an ambiguous failure. Fixed content type, `no-store`, `Connection: close`, a single exact canonical `Content-Length`, and no response transfer/content encoding are required; only a bounded maximum 8-KiB signed response is read. It validates exact signed envelope using Slice-50 Ed25519 verification with the current challenge, canonical witness commit request, externally pinned service public key, and supplied aware whole-second clock. HTTP 200 and a TLS handshake alone are **not** sufficient to accept a response.

## Caller handoff

The resulting exchange exposes `challenge`, `signed_envelope`, and a verified service observation. Callers may pass the first two values to `inspect_fresh_attested_forward_recovery` (Slice 52), together with independently obtained witness transport, signed metadata/trust roots, candidate inputs, and real installed-byte evidence. **There is no automatic conversion of this object into an activation token.** The frozen dataclass is freely constructible and never an authorization credential.

## Isolation and failure conditions

Wrong origin, expired/incorrect TLS chain, wrong CA hash, missing/reparse client key, absent service pin, invalid/duplicate/cacheable HTTP headers, truncated or oversized responses, unsigned/stale/mismatched service envelope, witness identity mismatch, and signer unavailability must fail closed. A service statement is meaningful only if an *independent administrator* has deployed and protected the service signing key, gate database, process supervisor, and all CAS writers. The supplied clock is not automatically authoritative. This client neither proves global writer stop/join nor protects local software from concurrent modifications.

The distinct witness head and physical candidate-byte checks from Slice 52 remain necessary and insufficient for production activation without independently protected service-wide and OS-level transaction semantics. Windows installed-wheel and network qualification are later integration gates. No classroom data is transmitted.

## Compatibility

Exactly four additive files (source, tests, architecture and validation). Historical release artifacts, existing launch policy, Core workspace selection and prior recovery APIs are unchanged. This slice is one bounded transport interface, not an end-to-end deployment claim.
