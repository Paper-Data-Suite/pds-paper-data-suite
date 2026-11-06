# Issue #49 — Pinned HTTPS witness transport (Slice 35)

Slice 35 makes Slice 33's `CheckpointWitnessTransport` callable usable through an
**explicitly provisioned** HTTPS service. It never contacts the network during
Suite import, ordinary `pds launch`, or routine offline diagnostics.

`ProvisionedHttpsWitnessTransport` accepts only a canonical HTTPS DNS **origin**,
not a caller-selected URL or path. Each call posts a single bounded challenge to
`/v1/receipt/head` using `http.client.HTTPSConnection`. Unlike general-purpose
URL openers, this API has no environment-proxy or redirect behavior. A 3xx or
non-200 status is an error. The response must be `application/json`, no larger
than 8 KiB. There is no automatic retry of a challenge nonce.

A separately provisioned SHA-256 pin authenticates the exact PEM CA bundle
bytes. An SSL context uses only that bundle, requires TLS server-certificate
verification and hostname verification, and loads an mTLS client certificate and
private key. TLS 1.2 is the minimum. The client credential authenticates the
**requester**; it never holds the witness **signing** key. All credential paths
must designate ordinary files rather than symlink/reparse-point leaves.

Supply the instance as the `transport` argument to `query_checkpoint_witness`;
the latter checks the independent Ed25519 witness signing key and binds the
response to the exact receipt, installation ID, challenge, and witness revision.
TLS certificate pinning does **not** substitute for that Ed25519 verification.

## Critical independent-deployment requirement

This code cannot establish whether the server's signing key, SQLite database,
client authentication policies, and monotonic store are protected from the
teacher operating account. The witness **must** be deployed and provisioned by
an independent administrator or host. The CA pin and Ed25519 witness key must
arrive through a trusted, independently controlled channel; values from the
teacher-writable Suite directory confer no authority. Path leaf checks do not
replace OS ACL validation of ancestor directories or private-key protection.

No first-party witness server, certificate issuer, network listener, OS service,
provisioning script, receipt enrollment workflow, or trusted activation is
provided in Slice 35. A functioning network transport alone must never be
reported as proof that the backend is independent or that software may launch.

## Fail-closed behavior

- Reject HTTP, IP literals, credentials in URLs, query/fragment/path selection,
  invalid hostnames, and noncanonical origins.
- Reject missing, replaced, symlinked or mismatching pinned CA bundles, absent
  mTLS credentials and invalid TLS parameters before sending a challenge.
- Reject redirects, non-200 responses, unexpected/duplicate Content-Type, and
  empty or oversized responses; close the connection on every outcome.
- Never accept an unsigned or arbitrary network response as a checkpoint: pass
  it to Slice 33 for Ed25519 and receipt-continuity verification.
- Never silently fall back to HTTP, system proxy settings, alternative hosts,
  previous cached replies, or a locally editable receipt digest.
