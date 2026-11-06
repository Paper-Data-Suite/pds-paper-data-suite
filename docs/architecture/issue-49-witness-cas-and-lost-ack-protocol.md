# Issue #49 — Slice 42: Independently authorized witness CAS and lost-ACK readback

## Decision and strict scope

Add an **opt-in witness-SERVICE-side** commit adapter and an untrusted canonical transport request format. Keep the existing teacher-facing witness endpoint **read-only** (`POST /v1/receipt/head`). There is deliberately **no HTTPS write route**, no Suite CLI command to advance a witness, no automatic activation, no local active receipt persistence, and no production `pds launch` changes. Merely importing this module never writes a checkpoint or contacts a network service.

The adapter `commit_independently_approved_successor()` must run only in a *separately administered*, authenticated witness service. Its `MonotonicCheckpointStore`, caller identity, approval policy, signing key, pinned verifier key, and approval evidence must **not** be obtained from locally writable Suite state or request fields. A Python callable supplied from teacher-local code would not satisfy that boundary. The service-owned `IndependentCommitApproval` policy must independently establish explicit operator/user consent, protected deployment activation, signed software identities, and the physical installation state. **These operational prerequisites are not provided by this slice.** The test-double policy proves only control flow.

## Request and CAS contract

`WitnessCommitRequest` contains the exact canonical predecessor and successor receipt bytes, installation ID, witness ID, and expected witness revision. The deterministic `pds_witness_successor_commit_request` version-1 JSON envelope includes canonical base64 receipts and independent SHA-256 references. Strict parsers reject duplicates, unknown fields, malformed encodings, excessive sizes, noncanonical JSON, changed hashes, reused transaction/paths, nonconsecutive receipt generation, and wrong predecessor hash.

Slice 41 may supply a `WitnessBoundSuccessorDraft`, but that draft is **never an approval token**. A receiver must independently parse and validate the request and authenticate the caller via the witness service—not from claimed client IDs or a hash alongside the payload.

At the service trust boundary, the adapter:

1. Requires the preconfigured witness checkpoint store and service-owned independent approval function.
2. Performs a fresh challenge-bound, Ed25519-signed **predecessor** head check with the independently provisioned witness public key, installation ID, witness ID and expected revision. This is a read, not a local-file attestation.
3. Requires a positive independent deployment/consent approval from service-owned identity/context. The service's own `MonotonicCheckpointStore` also reauthorizes the `commit` operation.
4. Delegates the atomic predecessor generation/digest CAS to `MonotonicCheckpointStore.commit_receipt()`: it refuses competing successors or reuse of an already advanced head. Compares the returned generation, SHA-256 and revision against the exact proposal.
5. Returns **only an unconfirmed service-local result**. A successful return does not equal authenticated client acknowledgment or launch eligibility. A failed call may still have an ambiguous outcome; never treat a local exception as proof the remote commit did not happen.

The existing store performs CAS transactionally, checking the predecessor receipt digest, generation, revision and a database-serialized update. This slice does not broaden the read-only HTTP service to remote writes. Service-side expected-revision validation is performed from a signed head immediately before the CAS; intervening competing generation advances make the store's predecessor CAS fail. External monotonic durability depends on independently protected SQLite and service credentials, not local Suite files.

## Interrupted or unacknowledged commit

`inspect_uncertain_witness_commit()` sends **one fresh challenge** to the signed head-read endpoint. It checks the same signed reply against both exact proposed receipt bytes, with pinned signer identity, challenge, installation ID, freshness, expected revision and chain-continuity validation. It does not resend a CAS, modify files, invoke application code, or acknowledge an update as complete.

| Signed result | Meaning | Action |
| --- | --- | --- |
| `SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED` | Exact successor head observed at expected revision + 1 | **Do not roll back** the local pointer; independently reconcile software bytes, durable local receipt and pending recovery before any launch |
| `PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED` | Previous head was signed at the expected revision at that instant | Do **not** infer that a prior request cannot complete later; independently fence pending service writes and confirm authorization/state before offline restoration |
| Invalid signer, alien head, forged payload, stale revision, outage | Not a validated prior/successor state | Refuse; preserve pending state and require independent operator reconciliation |

After an ambiguous commit, rerunning `commit_independently_approved_successor()` is **not** an idempotent retry: once the witness advances, the original predecessor cannot pass CAS. This is intentional to prevent duplicate advancement. A future phase must build a protected distributed activation finalization/reconciliation protocol and exercise every crash boundary on Windows.

## Explicit exclusions

- No remotely exposed write endpoint; no automatic witness enrollment or root key provisioning.
- No independently protected activation coordinator, physical software switchover, local receipt commit, successful-update state, or launch permission.
- No automatic recovery from a confirmed successor witness head: monotonic witness state must not be contradicted by restoring an old local pointer.
- No assumption that cooperative filesystem locks block hostile same-user writes or that a locally produced receipt authenticates physical software.

The old prior-head observation alone is **insufficient** to authorize offline recovery after a possibly in-flight witness CAS. Isolation/fencing is a follow-up requirement.
