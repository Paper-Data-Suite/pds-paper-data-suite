# Issue #49 — Slice 41: Witness-bound successor-receipt draft

## Scope

`draft_witness_bound_successor_receipt()` produces **only an in-memory, canonical proposed successor receipt** after Slice 40's inert selection. It is an additive module with no CLI or production dispatch integration. It does not install software, execute providers, persist a receipt, change selection, clear pending recovery, alter the journal, commit a witness head, or authorize a launch.

The existing service's `/v1/receipt/head` endpoint is **read-only**. `MonotonicCheckpointStore.commit_receipt()` is a service-side CAS building block, not a client-authorized activation or a remotely exposed endpoint. Treating a locally drafted receipt as permission to call that service method is forbidden. Independent service authorization, deployment protection, physical activation qualification, a separate authenticated write contract and crash-reconciliation design are prerequisites for any future head advancement.

## Preconditions: pending, explicitly unresolved transition

1. Validate bounded opaque signed-envelope input and whole-second aware UTC time. Work strictly outside the classroom workspace. Obtain cooperating **selection then transaction** locks, matching earlier slices.
2. Require an exact revision-2 `ACTIVATION_INTENT` journal; canonical currently selected successor pointer; and a canonical `pending-slot-recovery.json` capsule with the exact hash of the current selection, preserved old selection bytes and preserved old selection hash. **Absence of a capsule is a refusal**, not evidence of success.
3. Require the previous selection from the recovery capsule to match the parsed exact predecessor receipt; require generation +1 for the candidate selection; compare prior and candidate signed-envelope digests to the receipt and journal respectively; refuse overlapping or missing software/wheelhouse directories.
4. Under both locks, independently reverify the old stage's signed native evidence and observation record; audit old delegated-publisher identity, pip-installed bytes and launcher records; verify these against the previous receipt. Independently audit the selected candidate's delegated publishers/pip layout and root-signed native bytes.
5. Issue a fresh, challenge-bound signed head-read to the independently provisioned witness. The head must still be the exact previous receipt. Repeat both complete stage audits after the witness response and reject changed software observations or expired witness statements.
6. Reread the selection, recovery capsule and journal while still holding both locks; reject concurrent drift and caller-envelope mutation.
7. Build canonical receipt **bytes** from the fresh candidate observation and an `ExternallyPinnedReceiptHead` derived *only* from the signed witness response. Its generation must be predecessor +1 and its `previous_receipt_sha256` must match the witness head. Verify exact transaction, stage, native and pip inventory identity. Return the draft bytes, SHA-256 and the expected predecessor witness revision. Never persist or publish them in this slice.

The returned `WitnessBoundSuccessorDraft` status is `DRAFT_ONLY_CHECKPOINT_NOT_COMMITTED_RECOVERY_STILL_PENDING`; it is **not a trust token**, an approved active state, or authorization for a remote CAS. Neither same-user cooperative locks nor local pointer equality protects against malicious filesystem replacement after verification. The supplied trust keys and witness transport must be independently provisioned.

## CAS and recovery boundary

A candidate receipt is only a *proposal*. A later writer must verify signed publisher/native/pip bytes again inside a protected transaction; require independently authenticated operator/user approval and an actually controlled software activation; persist a recoverable commit protocol across a witness CAS; and positively confirm the independently signed **new** witness head. Witness commits cannot be rolled back merely by restoring a local pointer: the head is monotonic. If a head was advanced and the local process crashes before finishing, a separate, authenticated forward-recovery procedure (not Slice 40's offline old-pointer restoration) is mandatory. An offline witness outage before any head advance must not prevent safe restoration of the old pointer.

**No production `pds launch` behavior changes.** Any future finished updater must preserve one classroom workspace and clearly separate release provenance, launcher eligibility, scoped integration qualification, and active receipt continuity.

## Next slice candidate

Define a strict, authenticated witness-CAS request/response protocol with explicit service-side authorization, installation-scoped compare-and-swap preconditions, prior/successor receipt binding, and lost-acknowledgment recovery semantics. Do **not** activate production launching until a separate end-to-end software/receipt/witness commit protocol has been reviewed and physically exercised on Windows.
