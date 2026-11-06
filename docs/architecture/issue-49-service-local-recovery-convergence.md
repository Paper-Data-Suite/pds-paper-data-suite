# Issue #49 — Slice 46: Non-authorizing service/local recovery convergence

## Decision and scope

Introduce a **pure**, opt-in cross-boundary comparison of three existing bounded objects: a canonical Slice-42 `WitnessCommitRequest`, a Slice-45 `WitnessWriterQuiescenceState`, and a Slice-43 `ForwardRecoveryObservation`. The output is an operator-facing `RecoveryConvergenceFinding` and **never** an activation, rollback, old-pointer-restoration, witness CAS, or launch credential.

There is no new Suite CLI command, production `pds launch` integration, witness service endpoint, on-disk state, classroom workspace action, process execution, independent service authentication, or active receipt write. This module does **not** stop a writer, lock either system, fetch a fresh head, independently inspect installed files, or certify a remote service. Objects are passed by the caller and can be forged. Use this only after **separate** trusted capture of the service state and fresh signed local readback in a protected operator workflow. Matching two reported hashes is not a cryptographic attestation of their provenance.

## Exact comparison

1. Revalidate the complete canonical witness request. Derive its SHA-256, exact predecessor/successor receipt hashes and their parsed generations and transaction identifiers directly from receipt bytes.
2. Require service installation ID and canonical request SHA-256 to match the request. Refuse nonstandard `authority` labels, unknown states, conflicting service signed-head fields, or malformed local observation objects.
3. Require the local observer to name the *successor transaction*, even when the old witness head is visible; require exact revision, generation, and SHA-256 for its signed old or new head. Refuse any alien, stale, impossible, or forged-looking claim.
4. If the service gate is still admitted, possibly dispatched, or stopping, return `WRITER_NOT_QUIESCED_HEAD_ONLY_OBSERVED` even if the local observer sees an exact signed predecessor **or successor**. Preserve all recovery/fence records; obtain independently administered stopped-writer evidence.
5. If the service reports a sealed stopped-prior or stopped-successor state, require the service revision and digest to equal the exact corresponding local observation, and require identical prior/successor classification. Mismatches are **errors**, not downgraded into an authorized rollback.
6. An agreeing prior head yields `MATCHED_PRIOR_HEAD_REVIEW_STILL_REQUIRED`. An agreeing successor yields `MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED`. Both retain `NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY`. They are **historical consistency findings** and may become stale immediately.

## Security limitations

- Local dataclasses and service dataclasses are not signed interchange certificates. This slice cannot prove independently protected service provenance, writer termination, or continued quiescence.
- Two signed-head observations at different times can agree while the witness changes later. Protected software activation needs a separate transactional and operational admission/fencing guarantee.
- A correctly signed successor head does not prove installed program files, a durable active receipt, or teacher execution authorization. Old head plus a stopped-service assertion is still insufficient for automatic rollback.
- Comparisons do not silently repair divergences. No automatic retry, witness reset, cleanup of `pending-slot-recovery.json`, or clearing the Slice-44/45 service ledgers.

## Follow-up

Develop a separately protected, physically qualified activation/recovery coordinator and an authenticated handoff format for service attestations, tested against real Windows process isolation and crash boundaries. Do not route teacher production launching through these preflight building blocks until that independent authority exists.
