# Issue #49 — Server-side durable checkpoint witness (Slice 34)

## Scope and security

Slice 33 authenticates signed, fresh external witness observations. Slice 34
provides a deliberately **server-side** durable, monotonic compare-and-swap
(CAS) implementation for those observations. This is a library for a separately
provisioned witness service, **not** a feature of `pds launch` and **not** a
standalone, independently trusted deployment. Merely invoking this library with
a SQLite file inside the teacher's profile does **not** protect rollback state.

The operator must provision, independently of the Suite managed environment:

1. An OS account/host that teacher/Suite processes cannot modify or administer;
   a service-exclusive SQLite database on reliable storage with transaction
   durability, secure backup/recovery policy, and monitored filesystem access.
2. A private Ed25519 signing key in separate custody, **never** in the Suite
   repository, classroom workspace, installed wheel, source checkout, or local
   software selection files. The signer callback is injected by the host.
3. An authenticator that establishes client identity and per-installation
   permissions. `context` is provided by the trusted server transport, **not**
   copied from a client-chosen request field. Genesis additionally requires a
   separate `enroll` authorization. The fixture's string-based `context` is not
   a viable production authentication mechanism.
4. Independently provisioned public-key pinning and server-identity binding in
   the Suite client. The witness revision lower bound must be obtained from an
   independent trusted channel if it is used to reject server-state rollbacks.
5. Authenticated transport, request rate limits, bounded disk usage, monotonic
   UTC clock practices, and operational availability/recovery procedures.

A compromised witness operator/OS account or theft of its signing key is outside
what this library can prevent. SQLite `synchronous=FULL` addresses committed
write durability, **not malicious database replacement**. The witness must be
outside the software trust and rollback domain of the client installation.

## Protocol and transaction rules

`MonotonicCheckpointStore` receives an externally created `sqlite3.Connection`,
service-injected authorizer and signing callback, and registered witness ID. It
contains no signing keys or transport/server listener. It maintains one
`witness_heads` row per authenticated installation and separately persists
recent challenge nonces. Each write uses `BEGIN IMMEDIATE` so competing SQLite
connections cannot both commit from the same prior head.

- `commit_receipt` accepts only canonical Slice 32 receipt bytes. Genesis must
  be generation 1 with no predecessor and pass both `commit` and `enroll`
  service-side authorizations. Subsequent commits require exactly previous
  generation + 1 and `previous_receipt_sha256` equal to the current durable
  head; duplicate replay, stale heads, skips, and concurrent races are refused.
- `answer_challenge` checks the exact canonical Slice 33 challenge format, a
  cryptographic 32-byte nonce, installation ID, and a time window of 120 seconds.
  It performs an authenticated read, rejects reused nonces, and signs a statement
  naming the durable current/previous heads, witness revision, the SHA-256 of the
  exact challenge, and a short response window. Nonces outside a 300-second
  retention horizon are garbage-collected; challenges that old are invalid.
- `verify_witness_statement` from Slice 33 independently verifies signatures,
  challenge binding, revision freshness, time, and the Slice 32 receipt chain.
  The witness service **does not** call this verifier on itself or ask the client
  to trust its own database or locally stored signature.

Witness `revision` is monotonic per installation. A successful CAS is durable
before acknowledgment. A signing failure does not reverse an otherwise
committed receipt; operations must detect this and query again with a fresh
challenge. The service does not claim that a caller's receipt was an
independently verified, consented, publisher-signed installation. The update
coordinator must perform those checks and obtain explicit activation approval
before calling the independently authorized witness service.

## What is still missing

No production network listener, privileged service setup, key provisioning,
authenticated remote transport, OS policy, disaster recovery runbook, actual
PDS release-wheel qualification, or production activation/rollback transaction
ships in this slice. The service and Suite client are not wired together.
Normal teacher `pds launch`, `pds modules`, and offline doctor remain independent
of network availability and continue using the historical behavior until a
separately qualified production migration is implemented.

No key, witness database, temporary stage, or update journal may be placed in
or modify the classroom OneDrive workspace.
