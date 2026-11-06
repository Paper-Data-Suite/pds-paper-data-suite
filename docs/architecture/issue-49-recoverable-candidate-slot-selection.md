# Issue #49 — Slice 12: Reversible candidate-slot selection

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base commit:** `9bf4c59` (full commit checked by runner)
**Status:** Isolated software-lifecycle infrastructure, not production activation.

## Security and operational contract

`evergreen_activation_slots.switch_verified_candidate_selection` advances an
**inert** Suite-local selection pointer only after confirming:

- An existing Slice 11 journal with the matching transaction ID and phase
  `activation_intent` (a `candidate_verified` or aborted journal cannot switch).
- Byte-for-byte matches for prepared record, signed registry, dependency lock,
  and native evidence against the journal's recorded SHA-256 values.
- Fresh verification of the staged virtual environment, installed metadata,
  source wheelhouse, and independently root-signed exact native executable
  evidence; no caller-created `Verified*` object is accepted as authority.
- Both the staging directory and wheelhouse remain inside the approved
  software root, separate from the classroom workspace, and are not symlinks
  or detectable Windows reparse points.

The pointer is `candidate-selection.json`, not `active.json`. Its data model
is deliberately `UntrustedSlotSelection`: transaction, stage location,
prepared/native digests, generation. It offers **no** `can_launch`, `trusted`,
`installed`, or `activated` assertion. Its contents are replaceable by the
local OS user and are **not** an authenticated installed-composition receipt.

## Two-file crash protocol

A global exclusive `candidate-selection.lock` serializes cooperating writers.
The operation atomically persists `pending-slot-recovery.json` BEFORE replacing
`candidate-selection.json`. The recovery capsule binds a transaction to both
old and new exact pointer hashes and preserves the original pointer bytes.

On an interruption:

- If no candidate pointer was written, recovery sees the previous pointer (or
  absence) and safely clears the pending capsule.
- If the candidate pointer was written, recovery restores the exact saved
  previous pointer bytes; for an initial installation it deletes the candidate
  pointer. Physical software directories are never changed or deleted.
- If the pointer matches neither the prior nor the proposed candidate, or the
  recovery capsule has been edited, recovery refuses to overwrite ambiguity.
- If power fails after restoration but before the capsule is removed, the
  recovery operation remains idempotent and may be repeated.

`read_candidate_selection` refuses all pending recovery, rather than treating
an interrupted switch as healthy. The caller must explicitly reconcile with
`restore_previous_selection`; there is **no automatic promotion**.

No standalone `confirm candidate` method is supplied. In a later slice,
confirmation must include **actual managed installed-state verification,
independently authenticated prior-state continuity, and completed smoke tests**.
Until that exists, the candidate pointer is not eligible to be used by the
production launcher.

## Prior-slot and receipt limitation

For a previous selection, the coordinator requires a real, non-link prior slot
directory before switching, leaving those packages intact for rollback. It
cannot establish that a locally editable prior pointer represents a trusted
previous installation. An expected prior authenticated receipt in Slice 11
cannot be satisfied by this selector and is **explicitly refused** until the
previous-installed-state verification adapter is delivered. This restriction
avoids conflating physical rollback with authenticated rollback.

The test suite uses synthetic signed packages and native binaries, not real
teacher environments. There is no invocation of pip, no network lookup, no
subprocess or import of candidate programs, no classroom data access, and no
change to current Suite launcher, bootstrap, or doctor commands.

## Limitations and next boundary

This is **not** yet a safe complete managed update. A local user who can modify
all files can change or restore the pointer, capsule, journal, and/or stage.
File hashing before an atomic pointer switch does not exclude hostile same-user
concurrent mutation. Real Windows file handle/reparse/hardlink protection,
durably protected release/receipt continuity, reproducible native signing,
qualified installed-Core/module contracts, and explicit transaction success
semantics are still required.

Next: verify authenticated prior installed-composition receipts, run genuine
isolated installer and candidate acceptance checks, establish a managed
activation/rollback authority for foreground launching, and wire teacher-facing
updates without modifying classroom files.
