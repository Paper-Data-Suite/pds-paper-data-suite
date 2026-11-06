# Issue #49 — Slice 16: Prior-bound, recoverable candidate selection

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base commit:** `483c863` (the exact commit is checked by the runner)
**Status:** Internal candidate-selection infrastructure; no installed-state authority.

## Contract

`evergreen_prior_switch.switch_armed_prior_bound_selection` extends the
reversible pointer mechanism to updates that have a previous installation.
Unlike the initial-install selector, it requires the precise Slice 15
`activation_intent` journal revision and a byte-for-byte matching prior
observation, not merely a pointer claiming an older stage.

The coordinator acquires the global selection lock **before** the transaction
journal lock. With both cooperating locks held, it:

1. Refuses a pending recovery marker, missing previous selection, stale or
   unarmed journal, missing prior record binding, or unexpected evidence digest.
2. Rechecks previous selected software with `verify_previous_slot_record`,
   including signed wheel/dependency provenance and signed native executable
   evidence. The previous record must match the exact journal hash.
3. Independently rechecks the proposed staged candidate using
   `verify_signed_staged_native_evidence` and the exact journal evidence bytes.
4. Verifies distinct prior/candidate transaction IDs, current selected
   generation, and four mutually nonoverlapping managed software directories.
5. Atomically writes `pending-slot-recovery.json`, preserving the exact prior
   pointer bytes, **before** atomically replacing `candidate-selection.json`.
6. Leaves both software installations, the update journal, and the classroom
   workspace unchanged. Releases both locks on success or failure.

`restore_previous_selection`, introduced in Slice 12, handles interruptions
before or after pointer replacement and restores the exact old pointer when
there is no third-party divergence. Recovery is intentionally required after
**every** selection attempt: there is no confirmation or promotion API.

## What is not established

This function returns an `UntrustedSlotSelection`. It cannot demonstrate that
an older installation was historically activated, that its locally editable
journal or receipt is protected from same-user rewriting, or that a native
executable will stay unchanged after hashing. It does not run a candidate,
install wheels, invoke pip, switch the live `pds launch` dispatcher, or grant
permission to launch. The signed-native test evidence is synthetic: a real
publisher-controlled signing/distribution mechanism remains a prerequisite.

Locks serialize cooperating callers, not hostile same-user processes.
Concurrent file replacement, Windows hardlinks, protected monotonically
increasing installed-state continuity, robust crash durability, and production
smoke/rollback orchestration remain work for later slices. A local pointer
**must not** be used as a substitute for authenticated active-install state.

## Follow-on scope

Create a supervised acceptance contract for installed dependency closure,
public launcher ownership, isolated smoke checks, and a specifically authorized
active-state receipt. Only then should Suite wiring or teacher-controlled
update operations switch which software is launched.
