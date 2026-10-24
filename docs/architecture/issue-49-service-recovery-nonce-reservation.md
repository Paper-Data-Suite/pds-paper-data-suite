# Issue #49 — Slice 57: service-owned durable challenge reservation before signing

## Decision

Slices 50 and 53–55 bind a service recovery statement to a cryptographically random 32-byte client challenge, an exact witnessed successor request, an independently pinned Ed25519 key and a short lifetime. The read-only observation handler could nevertheless re-sign the **same** challenge multiple times; a restarted or competing service process had no durable application-level replay account. Slice 57 introduces an **opt-in, service-side, durable one-use signer** that can be passed directly as the `sign` callable to the existing Slice-54 `create_recovery_observation_https_server` factory. Historical Suite v0.1.0, the client, and older service handler APIs remain unchanged.

`DurableRecoveryNonceSigner(connection, sign=..., clock=...)` accepts the **exact** domain-separated Slice-50 canonical service-observation signing preimage. It rejects all other signing domains, malformed or duplicate JSON, unknown fields, unexpected service status/authority, noncanonical nonce, invalid identity/digest/revision/time fields, or a signing time inconsistent with the independently supplied service clock. It never signs arbitrary client-submitted bytes. The existing Slice-53 HTTP handler still requires a verified mTLS peer, an independently authorized gate `observe` callback returning the stopped-successor state, and a valid witness request before it invokes this signer.

## Durable replay and clock contract

1. The service administrator creates a persistent, protected SQLite database under an independently operated service account and supplies a live connection shared by its trust domain. An in-memory SQLite database is refused. The adapter does not grant or verify OS permissions; only a real protected deployment can establish independence.
2. Validate the 32-byte challenge and the exact Slice-50 domain-separated signing preimage **before** touching the ledger or signing key. Require the signed `issued_at` to be no more than five seconds behind the service-owned, aware whole-second clock; future-dated messages fail closed.
3. In one SQLite `BEGIN IMMEDIATE` transaction, refuse a backward movement from the durable service clock high-water mark, insert `(installation_id, SHA256(challenge))` under a uniqueness constraint, retain the associated request and preimage hashes for diagnostic correlation, and advance the high-water mark. An already-seen nonce is refused even when the request changes. SQLite controls cross-connection serialization when all service writers use the same protected database.
4. Remove only entries older than 24 hours according to the durable service clock. Since a signed observation expires after 60 seconds, pruning an entry after a day cannot make that old statement freshly acceptable. A later service clock rollback is refused by the retained high-water mark. Disk exhaustion or SQLite errors fail closed.
5. **Commit the nonce reservation before invoking Ed25519 `sign`.** If the signing callback crashes, returns an invalid signature or the network acknowledgment is lost, that nonce remains consumed. Do not retry with the same nonce. A client must create a genuinely new random challenge in a separate, authorized request.

A call to the Slice-54 observation handler now performs a strictly scoped, service-side **replay-ledger mutation**, even though it performs no mutation of teacher software, local installation receipts, recovery capsules, witness CAS or classroom data. The server's no-activation authority remains unchanged.

## Limitations and scope of qualification

The one-use signer is **opt-in**: deploying the prior Slice-54 server with an unrestricted signing callback does not automatically gain replay protection. Subsequent production wiring must require this signer or an independently reviewed equivalent and restrict direct access to the signing key and witness store. Replay defense is not rate limiting, revocation, a trustworthy clock, service-wide process supervision, key rotation, a global CAS fence or operator authorization. An attacker controlling the service database or signing key bypasses this trust boundary. In particular, SQLite paths under a teacher's writable software folder are *not* independent service-owned storage.

The retained hashes exclude the raw challenge, full witness request, service signature, student information and private keys. The ledger still contains pseudonymous installation/request identifiers, so it belongs to the independently protected service. Operational backups, capacity controls and retention audits are future deployment gates. No background task is started and no teacher-facing command is added.

This slice contains four **additive** files: one production module, synthetic and loopback mTLS regression tests, this architecture record, and validation notes. Existing launch/recovery/HTTPS modules are untouched.
