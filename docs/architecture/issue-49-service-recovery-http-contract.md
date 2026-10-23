# Issue #49 — Slice 53: authenticated service-recovery HTTP request contract

## Scope and design decision

Slices 50–52 can verify a signed service writer-quiescence statement and reconstruct local/witness/installed-byte evidence, but did not define a bounded request path for a separately operated service to **return** that statement. Slice 53 introduces **only** a strict, opt-in, read-only HTTP handler contract in `evergreen_recovery_observation_http.py`. It does not start a network listener, provision private keys, certify a real mTLS peer, dispatch witness CAS, start a package or expose teacher launcher/activation. Historical Suite v0.1.0 remains unchanged.

The handler models the existing independent witness mTLS head-read convention but has its own exact route `POST /v1/recovery/service-observe`. Hosts integrating the handler MUST terminate a *verified* mTLS socket and pass only `SSLSocket.getpeercert(True)` DER, never a header or request claim. Hosts MUST authenticate/authorize the client certificate fingerprint, maintain a protected independent service-owned `WitnessWriterQuiescenceGate` SQLite and writer supervisor, protect the Ed25519 signing key and provide an independently controlled whole-second clock. The handler cannot prove any of these deployment properties.

## Wire contract

- Accept exact `Content-Type: application/json`, `Accept: application/json`, and canonical decimal `Content-Length` equal to the body length; reject duplicate headers, proxy/client identity headers, forwarded assertions, chunked transfer, oversized content, unknown routes and methods.
- Canonical, duplicate-free ASCII JSON with exactly `record_type`, `schema_version`, `challenge_b64`, and `witness_request_b64` fields. The request is at most 48 KiB; the canonical nested Slice-42 witness commit request at most 32 KiB. Both base64 strings must be canonical. The challenge is **exactly 32 bytes**; caller must generate a new unpredictable nonce on each query.
- Parse the nested witness proposal through the already strict `parse_witness_commit_request` validator, not by trusting a claimed receipt digest or installed file.
- The server maps a verified mTLS peer fingerprint to a **service-owned authorization context**, then observes the exact request using the injected service `observe` function (in deployment, `WitnessWriterQuiescenceGate.observe(request, service_context=context)`). It never accepts a `WitnessWriterQuiescenceState` serialized by the client.
- Only a `SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED` observation bound to this request is eligible for the existing Slice-50 `issue_service_recovery_attestation`. The service signs the domain-separated Slice-50 statement, not arbitrary client bytes. The statement has an exact 60-second signing window and no activation authority.
- Return JSON body and HTTP 200 for a signed observation, otherwise fixed generic `400/401/403/404/405/413/415/503` error JSON, without traces or local receipt contents. The embedding HTTPS host MUST add `Cache-Control: no-store`, `Content-Length` and `Connection: close`, and bound response time and connection count.

## Security boundary

A supplied `peer_der` parameter does not itself prove the TLS handshake authenticated the peer. A callback posing as the service gate or signer is also not independent authority. The HTTP handler is explicitly **a pure request/response adapter**, not an HTTPS host or a deployed independent service. It never writes SQLite, reconciles physical slots, dispatches witness CAS, clears a capsule, grants rollback, switches a pointer, or runs teacher-installed code. Even a real signed service statement remains an observation of the durable gate and does not itself re-read the witness head. The client must still run fresh Slice-52 signed witness and physical candidate-byte checks; an OS-protected activation transaction is future work.

Malformed requests, stale/mismatched gate state, unknown peers, missing gate rows, signer failures, and malformed certificate evidence fail closed. Avoid logging certificates, challenge bytes, installed artifact metadata, class records or full request bodies. All data belongs to software-recovery protocol; no classroom contents are fetched or transmitted.

## Follow-on work

A later integration slice must provide a real configured mTLS host with protected signer/gate dependencies, actual inter-process/service-wide writer fencing tests, nonce/freshness continuity checks, and a remote service transport that plugs into Slice 52. This slice deliberately does not represent that deployed host as complete or ready to enable production activation.
