# Issue #49 — Slice 54: separately provisioned mTLS host for signed recovery observations

## Scope

Slice 53 implemented the exact canonical `POST /v1/recovery/service-observe` handler, but did not bind real sockets or authenticate TLS clients. Slice 54 adds an **opt-in, explicitly constructed** HTTP/1.1 server factory in `paper_data_suite/evergreen_recovery_observation_server.py`. No listener is created on import or by the teacher CLI. Existing v0.1.0 launcher behavior is unchanged.

## Host contract

`create_recovery_observation_https_server(bind=..., tls_context=..., identify_client=..., observe=..., sign=..., clock=...)` requires a previously provisioned `ssl.PROTOCOL_TLS_SERVER` context with `CERT_REQUIRED` client verification and minimum TLS 1.2. The independently operated deployer supplies server certificate/private key, trusted client CA and revocation policy, authenticated client fingerprint mapping, service-owned `WitnessWriterQuiescenceGate.observe` adapter, independently controlled Ed25519 signer, and clock. The factory rejects missing dependencies and invalid bind values; it binds a socket but **does not serve** until its owner explicitly calls `serve_forever` or an equivalent supervisor loop.

The single-threaded server keeps service-owned SQLite gate access on one thread. Each accepted TCP socket receives a five-second handshake timeout and undergoes a real TLS handshake **before** any HTTP request handler runs. `SSLSocket.getpeercert(binary_form=True)` is the only source of DER passed to the Slice-53 handler, never request headers or forwarded assertions. TLS negotiation failures do not invoke the gate or signer.

The HTTP request handler exposes **only** the exact service-observation route. Other methods return 405; unknown routes return 404. It refuses missing, duplicated, noncanonical, chunked and oversized `Content-Length` framing, and the underlying Slice-53 handler checks exact JSON headers, canonical request/proposal encoding, client identity, signed service status, and bounded response size. Every HTTP response closes the connection and sets `Cache-Control: no-store` and exact response length; errors have generic bodies. It never logs request data, peer certificates, signature material, classroom records or tracebacks in normal HTTP logs.

## Trust boundary

**A real mTLS socket is not enough to establish an independently administered recovery service.** Key protection, durable gate database ownership, process isolation across every CAS writer, client CA lifecycle, signer rotation/revocation, clock accuracy, operational availability and replay-resistant client challenge creation remain deployment responsibilities. A service running under the teacher's account does not provide a separate authority boundary. The status statement is a signed observation only; it does not certify witness-head freshness or physical installed-byte integrity. Slice 52 still requires new witness and candidate-byte checks.

This server contains no CAS-write method, update installation, live launcher switch, active-receipt commit, offline rollback, cleanup, classroom workspace operation or software execution. Only a protected coordinator could eventually perform crash-safe forward recovery after independently satisfying all update trust conditions.

## Follow-on requirements

Integrate a strictly verified HTTPS client transport, real protected service deployment with gate/ledger binding, supervised CAS writer stop/join, authenticator/key lifecycle, and physical Windows installed-wheel qualification before any production recovery/activation pathway is enabled. Loopback test certificates and synthetic observers do not constitute deployment evidence.
