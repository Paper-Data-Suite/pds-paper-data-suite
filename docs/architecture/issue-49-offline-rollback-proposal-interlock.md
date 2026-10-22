# Issue #49 — Slice 49: offline rollback proposal interlock

## Decision

Prevent two **legacy inert pointer restoration** functions from overwriting the selected successor or deleting the pending recovery capsule after the Slice-43 durable successor proposal could have been submitted to an independently operated witness CAS. The two guarded entry points are `restore_previous_selection()` and `reconcile_witness_bound_selection_offline()`.

This is an intentionally narrow additive fail-closed interlock, **not a trusted rollback certificate** or an activation coordinator. The established pre-proposal inert-only crash recovery remains available. Post-proposal failures stay pending for protected reconciliation. The new helper does not contact a witness, change the journal, switch runtime launch, or commit any receipt.

## Guard semantics

- After taking the existing cooperating selection lock, but before restoring an old pointer, each path checks `transactions/<transaction_id>.successor-proposal.json` through `Path.lstat()`.
- Presence blocks recovery **regardless of contents**. A corrupt JSON record, a directory or a symlink is never treated as permission to proceed. Any OS error other than an absent entry also fails closed.
- The transaction ID must be exactly 32 lowercase hexadecimal characters. Neither the record nor any symlink destination is opened to decide whether to block.
- With a missing proposal, the original narrow inert-pointer semantics are retained, including previous journal and capsule guards. No new automatic remote query, network dependency, or application execution is introduced.
- Failure preserves the pointer, capsule, journal, staged candidate/prior directories and classroom workspace; no silent cleanup or retry.

## Security and limitations

An untrusted local proposal is **not** an authenticated proof of remote commit. **Absence is not an authenticated proof of no commit**: deletion/tampering by a same-user writer, bypass of cooperating locks, damaged directories, or an independently untracked CAS could evade the presence guard. The two guarded functions remain unsuitable as independently protected rollback mechanisms. Production needs genuine witness-writer fencing, authenticated signed readback and service-owned physical-state coordination to decide rollback or forward reconciliation.

The Slice-48 forward-recovery handoff is a non-authorizing observation. A visible successor head requires **forward** reconciliation and cannot be undone by restoring a previous local selection. No new activation authority is conferred.

## Residual work

Build a separately protected active-receipt and physical-installation coordinator that consumes independently authenticated service evidence, handles cross-process crash/fencing boundaries, and deliberately finishes forward recovery. Validate the end-to-end path on Windows and supported platforms before enabling teacher production launch.
