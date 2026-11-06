# Issue #49 — Slice 39: witness-gated crash-recoverable activation intent

## Scope and authority

`arm_witness_bound_activation_intent()` adds a guarded journal transition from exact revision 1 `CANDIDATE_VERIFIED` to revision 2 `ACTIVATION_INTENT`. It is an **additive, opt-in, non-launching** module. No Suite dispatcher, active selection, environment, packages, classroom workspace, active receipt, witness checkpoint, or CLI path is changed. The returned object is evidence of a journal write **only**, not a deployment or launch token.

A locally writable journal, selection file, previous-slot observation, and active receipt cannot attest their own history. The supplied witness transport and Ed25519 public key must be provisioned independently of locally writable Suite artifacts. The signed external witness must authenticate the **exact previous receipt bytes**, with challenge freshness, installation ID, witness ID, monotonically bounded witness revision, pinned signing key, receipt generation and predecessor continuity checked by the existing witness verifier. A reachable or cryptographically correct endpoint is not by itself proof of independent administration.

## Guarded transition

1. Validate bounded raw inputs and a whole-second UTC-aware validation instant, copy both module-envelope maps, and reject incompatible layouts.
2. Resolve ordinary software and classroom roots; acquire the **selection lock first**, then the **transaction journal lock** (the ordering used by existing two-sided switch logic). Reject unresolved pending recovery.
3. Require canonical selected predecessor and exact unarmed journal revision 1. Check candidate signed-input SHA-256 bindings and prior observation-record digest, selected predecessor and receipt identity, receipt signed-input hashes, generation and time bounds. Require four non-overlapping, extant directory roots, including the previous wheelhouse.
4. Re-verify previous signed native bytes and its previous observation record; independently audit previous delegated-publisher identity, actual pip installed files, and launcher records. Bind the resulting exact pip inventory and publisher identities to the previous receipt. Audit the candidate delegated publisher/pip files and root-signed native bytes. These are **fresh audits**, not caller-provided `ObservedJournalPipCandidate` objects.
5. Under both locks, issue a fresh external challenge and verify the signed previous head. Fail closed on offline, invalid signature, mismatched receipt, freshness or revision errors.
6. Re-run the two-sided signed native/publisher/pip audits **after** the witness reply. Reject unequal observations, expired signed window, changed caller-envelope maps, journal/selection drift or new pending recovery.
7. Atomically replace only `transactions/<transaction>.json` with `ACTIVATION_INTENT` revision 2, with existing write/flush/rename semantics. Release both locks on success or refusal.

No pending slot recovery capsule or selection switch is produced in this slice. After a process stops following the journal write, the journal remains `ACTIVATION_INTENT` and `classify_recovery()` returns `manual_active_install_reconciliation_required`. This state never authorizes restarting into or automatically promoting the candidate. Existing recovery/switch modules remain separate, and a future controlled activation must re-verify **again** under an appropriate protected transaction.

## Threat model and exclusions

- The locks protect **cooperating Suite writers**, not a hostile same-user process, privileged malware, or an external attacker able to swap files after inspection. This slice does not claim OS-protected installation identity, immutable directories, or protected-key provisioning. No runtime launch activation is allowed.
- The witness is read-only: arming intent does not publish a new witness head. A future successful switch requires a separate durable active receipt + independently authorized, compare-and-swap witness checkpoint commit, failure handling, and a physically recoverable installation.
- The caller-provided clock must be accurate; monotonic elapsed time rejects a witness reply that expires while the second audit runs. A signed head cannot guarantee detection of revocation while offline.
- No untrusted stage code or provider imports may be executed as part of this transition. A local journal marker is not an authenticated release or independent history store.

## Follow-up

The next slice should define a witness-aware reversible selection and post-switch recovery protocol (including a crash at every boundary), without routing production `pds launch` to it until receipt/witness commit and installed-state integrity are independently established.
