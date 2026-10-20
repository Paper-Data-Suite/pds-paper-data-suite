# Issue #49 — Slice 40: witness-aware reversible candidate selection

## Authority boundary

Two opt-in, non-CLI functions implement a **reversible local software-selection hint**, not an authenticated active installation:

- `select_witness_bound_candidate_slot()` transitions an already-armed Slice 39 journal (exact revision 2 `ACTIVATION_INTENT`) into a pending *inert* candidate-selection file change.
- `reconcile_witness_bound_selection_offline()` restores the exact previous selection from a pending recovery capsule and records journal revision 3 `RECOVERY_REQUIRED`. The witness must **not** be contacted for this rollback.

Neither function changes the normal `pds launch` path, issues a trusted active receipt, advances the witness head, installs packages, executes a module, deletes any staged software, or alters the Core-selected classroom workspace. The journal, receipt and both selection files are locally editable. The external signing key, signed witness statement, and publisher metadata must be independently provisioned to the caller; local files and test doubles cannot establish historical activation.

## Witness-gated inert switch

1. Bound raw input sizes and identities, require an aware whole-second clock, and copy both immutable-by-contract module-envelope maps.
2. Resolve nonoverlapping ordinary software/classroom roots. Acquire the same lock order as previous Suite transitions: **selection lock**, followed by **transaction journal lock**. Refuse unreconciled recovery capsules.
3. Require exactly journal revision 2 `ACTIVATION_INTENT`, a canonical selected prior slot, and evidence digests matching the journal. Require the selected prior to match the exact prior receipt (generation, transaction, stage, signed input digests); reject overlap among prior/candidate stage and wheelhouse directories.
4. Revalidate the previous native/signed observation record against the signed stage, audit prior delegated-publisher identity, installed pip RECORD files and launcher ownership, bind those observations to the prior receipt, and independently audit candidate publisher/pip/native bytes. These checks do not execute candidate code.
5. **While holding both cooperating locks**, issue a fresh challenge and verify the independent witness's signature, exact previous receipt head, installation identity, signer, freshness and optional minimum revision. This read is not a compare-and-swap authorization or a witness commitment.
6. Repeat *all four* signed prior/candidate audits after the witness response. Refuse any difference, expired signed reply window, changed input-envelope map, changed selection/journal bytes, or newly pending recovery.
7. Atomically write `pending-slot-recovery.json` with the exact old selection preimage, its digest and the digest of the proposed selection. **Only after that succeeds**, atomically replace `candidate-selection.json` to point at the new candidate and its next generation. Leave journal revision 2 armed and the witness's previously committed head unchanged.
8. `read_candidate_selection()` intentionally refuses the pending capsule; this prevents other cooperating readers from treating the selected candidate as an ordinary stable hint. No new production launcher is registered.

A successful response is `INERT_SELECTION_PENDING_EXPLICIT_RECOVERY`; it **never** says the candidate is active, installed, fully integrated, or authorized to launch. The entire step is preparatory until a separately designed authenticated active-receipt and external witness compare-and-swap protocol exists.

## Offline recovery and crash table

The recovery function also holds selection then journal locks. It requires the exact pending capsule and matching armed/recovery journal, reconstructs the candidate selection deterministically, and accepts only the prior preimage or the calculated candidate digest as current selection. An unrelated selection is **never overwritten**. It restores the prior bytes if necessary, atomically records journal revision 3 `RECOVERY_REQUIRED`, verifies unchanged capsule/selection state, then removes the capsule.

| Interruption | Persisted files | Safe next operation |
| --- | --- | --- |
| Before capsule write | Old pointer, armed journal; no capsule | Do not infer activation. No selection write occurred; operator may review an independent attempt |
| After capsule write; before pointer write | Old pointer, capsule, armed journal | Offline reconciliation checks the old preimage, marks recovery required, clears capsule |
| After pointer write; before any receipt/witness commit | Candidate **inert** pointer, capsule, armed journal | Offline reconciliation restores old pointer; no automatic candidate promotion |
| After pointer restore; before journal write | Old pointer, capsule, armed journal | Retry offline reconciliation idempotently |
| After recovery journal write; before capsule removal | Old pointer, capsule, revision 3 `RECOVERY_REQUIRED` | Retry offline reconciliation idempotently; preserve revision 3 |
| Capsule missing, pointer unrelated, or malformed state | Ambiguous local history | Refuse automatic changes; operator investigates software and independently authenticated witness head |

The offline routine's result is `OLD_INERT_POINTER_RESTORED_FULL_RECOVERY_REQUIRED`. It does **not** certify restored package integrity or close the update transaction. Existing journal recovery classification continues to call for manual active-installation reconciliation, even after an inert pointer rollback.

## Threats and remaining gates

The cooperating lock files are not OS-protected against same-user attackers or privileged malware. Native and pip checks are point-in-time checks; an attacker who can mutate the stage after verification is not excluded by this slice. No automatic stale-lock deletion is allowed. An authenticated remote *read* is not a remote compare-and-swap commitment, and does not provide transactional atomicity with a local pointer update. A later production activator must establish protected software state, exact new active receipt, witness CAS commitment, and post-commit recovery before any `pds launch` routing changes.

## Next slice

Design the signed successor-receipt and witness compare-and-swap **preparation and failure classification** contract, including the difference between a prepared receipt, a committed witness head, a selected inert slot, and a verified installed active environment. Do not wire production launch to this experimental selection.
