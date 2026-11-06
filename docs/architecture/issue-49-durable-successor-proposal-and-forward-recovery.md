# Issue #49 — Slice 43: durable successor proposal and guarded forward-recovery observation

## Decision

Add a deliberately **untrusted**, bounded local successor-proposal record under the managed software root, written **before any external witness CAS may be attempted**. After a possible witness advance or lost acknowledgment, a separate read-only observer compares a fresh challenge-bound signed witness head with the exact persisted predecessor/successor receipt bytes. Both paths preserve the inert selection pointer, the pending recovery capsule and the revision-2 `ACTIVATION_INTENT` journal.

This is a recovery **precondition and observation**, not a finished update transaction, active-installation receipt, executable trust credential, launcher switch, remote CAS, or permission to roll back. There is no new CLI, startup action, witness HTTP write route, or change to `pds launch`.

## Persist proposal before external commit

`persist_untrusted_successor_proposal()` takes a Slice-41 in-memory draft and its exact predecessor bytes and turns them into the strict Slice-42 `WitnessCommitRequest`. It requires explicit software/classroom boundaries, selection-then-journal cooperating locks, and an exact pending state:

1. `ACTIVATION_INTENT`, journal revision 2, exact selected successor generation, four separate ordinary staged/wheelhouse directories, and a matching preserved predecessor selection from the pending recovery capsule.
2. Exact predecessor and successor canonical receipts; receipt generations consecutive; successor prepared/registry/lock/native hashes tied to the armed journal; selected pointer and recovery-capsule hashes checked against exact local bytes.
3. A fresh signed, challenge-bound witness **predecessor** head at the expected revision, checked through Slice 42. If the signed successor is *already* visible, refuse creation of an after-the-fact record. A prior-head observation does not prove the absence of an in-flight commit.
4. Identical journal/selection/recovery state after the witness read while locks remain held.
5. A single canonical, bounded `transactions/<tx>.successor-proposal.json` write via same-directory temporary file, fsync and atomic replacement. Reject an existing/unsafe file; no silent overwrite or replay.

The stored record contains only the canonical encoded commit request, its digest, timestamp and the hashes of the local journal, selection pointer, and recovery capsule. It contains no credentials, secrets, private witness keys or classroom data. A SHA-256 adjacent to locally writable bytes is **not independent authentication**; a malicious same-user process can replace these files. The normal file replacement sequence provides atomic visibility, not a cross-platform guarantee of power-loss persistence.

Before *any future external CAS*, a separately protected updater must check this proposal exists and matches exact bytes, repeat **fresh publisher/pip/native audits**, establish independently authenticated deployment consent, and obtain a protected physical-activation decision. None of those authorities is granted by persistence.

## Signed forward-recovery readback

`inspect_pending_forward_recovery()` holds the cooperating selection/journal locks and refuses a missing, corrupt, noncanonical or changed proposal; missing/changed recovery capsule; altered selection; or journal drift. With exact stored predecessor/successor receipt bytes it makes **one** fresh signed witness challenge via the Slice-42 readback function, including the expected witness revision and pinned signer. It checks the local snapshot again before return.

| Signed external head | Returned classification | Required next step |
| --- | --- | --- |
| Exact successor at expected revision + 1 | `SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED` | Forward reconcile protected physical software, durable active receipt and activation lifecycle. **Never restore the old pointer merely because local state is pending.** |
| Exact predecessor at original revision | `PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED` | The remote CAS could still be in flight. **Do not assume offline rollback is authorized** until the witness writer is independently fenced and outstanding writes have been resolved. |
| Unrecognized head, revision, signer, transport outage | Refusal with pending state untouched | Operator escalation and protected reconciliation; never retry CAS automatically. |

Neither successful observation removes the capsule, modifies the journal, persists an **active** receipt, confirms installed files or runs providers. The physical prior and candidate slots remain untouched. A local witness query does not substitute for independently protected filesystem/activation authority.

## Recovery and failure invariants

- Crash before proposal rename: no proposal (or only a disposable temporary file); no CAS may be initiated under this protocol. Stale temp cleanup is separate and cannot imply an activation outcome.
- Crash after proposal rename but before CAS: durable untrusted request is present, but successor remains uncommitted; signed prior head remains unresolved until outstanding writes are fenced.
- Crash during/after CAS: signed readback may identify an exact advanced successor, but physical software, local active receipt, and capsule **remain unresolved** until an independent forward-commit coordinator completes them.
- File mutation, missing pending state, stale signer, readback ambiguity or denial: fail closed. Never silently rewrite, reset, or delete the previous slot.

## Remaining work

A genuinely protected coordinator is still required to fence in-flight CAS requests, validate protected installed-byte state, make an authorized software switch, durably commit a verified *active* receipt, finish or compensate the pending recovery state, and expose an offline-safe production launcher only after these commitments align. This slice deliberately does not claim those capabilities.
