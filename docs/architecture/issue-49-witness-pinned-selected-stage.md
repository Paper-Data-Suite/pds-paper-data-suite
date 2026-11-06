# Issue #49 · Slice 62 — Witness-pinned selected-stage diagnostic

## Purpose

Slice 61 made signature-verified staged candidates accessible through an opt-in CLI diagnostic. Slice 62 adds a **separate, explicitly invoked API** to compare a locally selected slot and *claimed* receipt with an independently signed, fresh witness head and signed physical installed-file observations. It is not a production launcher and is **not wired into `pds launch`, `pds doctor`, or the normal offline `pds modules` path**.

The intent is to make the gap between stage verification and protected active-state authority testable. A locally edited `candidate-selection.json` or receipt never authenticates itself; the witness must have a separately provisioned Ed25519 public key and independently controlled persistent monotonic state. The root/delegated publisher trust keyring must likewise be provisioned independently of candidate files.

## Ordered read-only checks

1. Reject malformed inputs, overlapping software/classroom directory trees, unsafe paths, absent selection, and pending slot-recovery marker before contacting a witness.
2. Strictly parse canonical receipt bytes and match selection transaction, generation, stage path, prepared digest, and native-envelope digest. Check receipt registry/lock digests against caller-supplied original signed envelopes.
3. Resolve the stage and wheelhouse **only** from receipt paths under the trusted software root using existing managed path confinement checks. Never accept an absolute or arbitrary path inside a receipt.
4. Query the independently configured witness using a new challenge. Verify its signature, installation and witness identities, time window, monotonically pinned head, and both predecessor and successor continuity through the existing witness verifier. A mismatched head refuses the workflow before physical audit.
5. Invoke Slice 60's signed registry/publisher + repeated pip/native-byte auditor, then match the result to receipt transaction, signed-registry digest, publisher digests, pip inventory digest, and native payload digest.
6. Repeat the signed publisher/pip audit to compare the **entire receipt-supplied console ownership and external dependency lists**, fields not exported by Slice 60's compact diagnostic result.
7. Re-read the locally selected pointer; request a **second fresh signed witness challenge** at least as recent as the first, refuse witness revision changes during audit, and read the pointer once more.
8. Return a typed observation with `NO_ACTIVE_LAUNCH_RECEIPT_WRITE_OR_ACTIVATION_AUTHORITY`. The caller may print diagnostics but may not use this object to launch, switch, attest an installed ACTIVE state, write a receipt, or clean up recovery markers.

## Limitations and future security work

The two signed witness reads plus multiple physical audits are **not an atomic OS-protected transaction**. Same-user modification, replacement after the final check, mutable pointer/receipt custody, privileged lifecycle interlocks, and trustworthy native executable provenance require separate deployment and implementation. `query_checkpoint_witness` is a deliberately provisioned network-dependent path and must **not** become a dependency for ordinary offline launches. Successfully verifying the witness's signature does not prove the remote service correctly protects its own monotonic database: operational configuration and independent approvals remain necessary.

No files are created, overwritten, installed, activated, launched, rolled back, or deleted. Classroom content is neither opened nor modified. A witness query consumes remote service resources but performs no service-side CAS write.

## Next boundary

Protected active-receipt finalization, private local custody/rollback anchoring, recovery convergence and an atomic pre-exec eligibility check are prerequisites before any `pds launch` path can rely on these observations. Explicit per-module and whole-composition update commands remain unimplemented.
