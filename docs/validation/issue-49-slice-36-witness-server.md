# Issue #49 Slice 36 — Server-side mTLS head-read acceptance

- Exact parent: `dfe6e4a` on `49-evergreen-launch-and-supported-composition-upgrades`.
- Scope: additive service module, standalone tests and two Markdown documents.
- Endpoint: exactly `POST /v1/receipt/head`; no remote commit or enrollment.
- Authentication: actual TLS peer certificate DER, never HTTP identity headers.
- Inputs: pinned HTTPS client-compatible 1–1024-byte canonical challenge.
- Output: bounded signed witness statement; no-store, connection-close response.
- Negative cases: unauthenticated peers, rejected fingerprint, denied independent
  store authorization, duplicate/malformed headers, wrong route/method/media
  type, replayed nonce, stale/invalid body, TLS context without client auth.
- Integration: real loopback mTLS certificate exchange and Slice 33 signature check.
- Security limit: no independently provisioned OS account, secret custody,
  deployed service, update authority, active installation or launch wiring.
- Windows acceptance: Ruff, strict mypy, all 37 Slice 1–36 issue #49 test
  files, pip consistency, exact staged scope, whitespace and commit/push.
