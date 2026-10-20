# Issue #49 — Independent witness HTTPS head-read endpoint (Slice 36)

Slice 35 supplied a strictly pinned mTLS **client**. Slice 36 adds a narrowly
scoped **server-side read endpoint** for the exact `POST /v1/receipt/head` request.
There is **no commit, enrollment, update, or administrative HTTP endpoint**.
The only business operation reachable through HTTP is the existing Slice 34
`MonotonicCheckpointStore.answer_challenge` read operation, which already
checks the canonical challenge, expiration, replay nonce and installation ID,
requires an independent authorizer and signs the statement.

## Transport and trust boundary

`create_witness_https_server` requires an explicitly provisioned server TLS
context, mutual TLS (`CERT_REQUIRED`), TLS 1.2 or newer, existing checkpoint
store, service-owned peer-fingerprint policy and clock. It binds a socket but
**does not start serving**; its host must explicitly call `serve_forever`.
The listener completes and authenticates TLS on each accepted socket **before**
handing the request to the HTTP parser. Client identity is derived solely from
`SSLSocket.getpeercert(binary_form=True)` and the SHA-256 digest of the verified
DER certificate. It never comes from a request header, URI, or request JSON.

The service operator must provision the TLS certificates, client CA, fingerprint
allowlist, SQLite connection and the *separate* Ed25519 signing key. The
certificate-policy callback maps a verified fingerprint to a service-owned
context and the store's independent authorizer decides whether that context
may read the named installation. A matching certificate alone cannot enroll or
mutate a checkpoint. Unauthenticated or unknown peers fail closed.

The handler rejects non-POST methods, unknown paths, transfer encoding,
ambiguous/missing Content-Length, unsupported JSON media types, identity-spoofing
headers, and bodies outside 1–1024 bytes. The response is bounded by 8192
bytes, has `Cache-Control: no-store`, and closes the connection. The service
is single-threaded to respect one dedicated SQLite connection. A five-second
socket timeout bounds an incomplete TLS handshake or HTTP body read; public
exposure still requires independent network access controls and operations.

## Protection remains external

Running the server in the teacher's login, storing its signing key/DB beside
Suite, or treating its Python service as a protected authority **does not**
provide anti-rollback security. Protect storage and signing keys using an
independently controlled OS principal or host and restrict who may update the
allowlist. Independently pin its public witness key and HTTPS CA for clients.

The SQLite service's *administrative* commit/enrollment methods are **not**
network endpoints. An externally authorized administrative activation protocol,
protection against compromised service credentials, activation rollback and
actual released-wheel qualification remain separate work. Neither this module
nor its tests modify installed packages, change the active candidate, create
classroom data, or enable production `pds launch` behavior.

## Integration

The existing Slice 35 client issues a single JSON POST to
`/v1/receipt/head`. A real loopback test generates temporary CA/server/client
certificates, exercises TLS client verification, invokes the database-backed
head read, and verifies the returned Ed25519 statement through Slice 33's
`verify_witness_statement`. Tests keep synthetic keys in temporary fixtures
only. Runtime code does not generate, save, or ship private signing keys.
