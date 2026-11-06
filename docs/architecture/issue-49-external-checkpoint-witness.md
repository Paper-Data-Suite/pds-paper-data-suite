# Issue #49 — Challenge-bound external checkpoint witness (Slice 33)

Slice 32 defines canonical active-installation *receipt claims*, but a locally
editable receipt and a colocated checksum do not prove which installation was
previously selected. This slice adds a bounded Ed25519 **verification protocol**
for a separately provisioned, independently controlled checkpoint witness.

## Request and response

`issue_witness_challenge` produces a fresh 32-byte CSPRNG nonce in a canonical,
installation-scoped challenge. `query_checkpoint_witness` sends exactly those
bytes to a caller-provisioned transport, receives a signed reply, and verifies
it in the same call. It cannot use a cached reply from an older challenge.

The witness's canonical statement binds:

- the registered witness ID and stable installation ID;
- SHA-256 of the *exact* challenge bytes;
- a positive witness state revision;
- the current receipt generation and SHA-256;
- either an absent predecessor (genesis) or the exact prior generation and hash;
- bounded `issued_at` and `expires_at` timestamps.

The envelope contains `payload_b64` and `signature_b64`. The exact canonical
payload is signed using Ed25519. The local verifier requires a separately
**pinned 32-byte public key**; a public key supplied by the same untrusted
response is never accepted. Every message is size-bounded, canonical JSON;
duplicate fields, malformed base64, invalid signatures, changed installation,
expired responses, excessive validity windows, and mismatched predecessor
continuity are rejected. The witness statement is compared with the exact
local receipt using Slice 32's `verify_externally_pinned_receipt`.

The caller can supply an independently obtained witness-revision minimum.
A minimum supplied by locally editable candidate data adds **no anti-rollback
protection**. A fresh challenge plus a signed response prevents local response
replay, but requires an *honest witness with durable monotonic state* to prevent
the witness itself from serving an old head under a new challenge.

## Non-authority boundaries

This code **does not provision** the signing key, the witness, network service,
key pin, anti-rollback store, durable compare-and-swap, OS-protected state,
activation transaction, rollback, production launcher, or update CLI. It
performs no filesystem writes or candidate code execution. The test-only private
keys are generated in isolated pytest fixtures; production code includes no
private keys or signature-generation action.

The witness implementation must independently enforce append-only generation,
atomic compare-and-swap, and installation-ID ownership; a dishonest witness can
sign arbitrary heads. Caller-supplied objects or signatures from an unpinned key
do not establish trust. A missing, offline, or unprovisioned witness fails the
*live witness probe*. That is NOT a policy to disable normal offline teacher
launches; a future OS-protected local checkpoint and replay-safe refresh policy
must be designed for launch-time use without mandatory network access.

`WitnessReceiptObservation` is a **read-only observation**, not a credential
for installing, activating, rolling back, launching, or declaring a cross-module
integration qualified. Classroom workspace paths and student records are not
involved in this protocol and must not be used as checkpoint/key storage.

## Next implementation gate

Provide a reviewed witness service or OS-protected monotonic checkpoint
backend, implement independently authorized and durable CAS, transactionally
bind the receipt to the selected staged environment, reverify signed wheel and
native bytes, and qualify offline continuity and recovery before production
launch uses any of these observations. Signing code must remain outside the
ordinary teacher installation and any public module wheel.
