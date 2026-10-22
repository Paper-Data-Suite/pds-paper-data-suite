# Issue #49 — Slice 48: non-authorizing forward-recovery handoff correlation

## Decision

Provide a pure, read-only `prepare_forward_recovery_handoff()` preflight for the **successor-confirmed path only**. It correlates the exact canonical witness commit request (Slice 42), the service/local convergence finding (Slice 46), the service-owned writer-quiescence observation (Slice 45), and the requalified signed candidate byte observation (Slice 47). It produces an operator-oriented `ForwardRecoveryHandoff`, **never an activation credential**.

Nothing here changes `pds launch`, writes an active receipt, touches installation directories, clears `pending-slot-recovery.json`, resets a CAS fence, modifies a journal, invokes a witness, or authorizes offline rollback. There are no CLI routes or implicit startup actions.

## Conditions

- The signed-head convergence finding must be exactly `MATCHED_SUCCESSOR_HEAD_FORWARD_RECOVERY_REQUIRED` and retain its non-authorizing marker.
- The witness-service state must be exactly `SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED`, with the matching installation, request digest, signed successor revision and exact receipt digest. Service-side coordination only has operational significance where its supervisor truly controls **all** writers.
- The physical preflight must be `POST_CAS_SIGNED_BYTES_OBSERVED_FORWARD_RECOVERY_STILL_REQUIRED` and match the exact transaction, generation, successor receipt SHA-256, witness revision, expected stage path, pip inventory digest and native payload digest in the canonical successor receipt.
- The successor receipt must be the immediate generation successor to the predecessor receipt. Identifiers are derived from the canonical bounded Slice-42 request, not accepted merely because they appear in a local file.
- Missing/contradictory, predecessor-only, possibly-in-flight or permission-like observations fail closed. The preflight has no operation to clear or override them.

## Output and limitations

The result identifies the installed candidate and evidence digests for an **independent protected activation/reconciliation coordinator**, with status `FORWARD_HANDOFF_REQUIRES_PROTECTED_ACTIVATION_RECONCILIATION` and authority marker `NO_LAUNCH_ROLLBACK_RECEIPT_OR_SWITCH_AUTHORITY`.

These Python dataclasses can be forged, replayed, or become stale. This comparison does **not** authenticate their provenance, prove the OS stopped a writer, establish an immutable filesystem, guarantee that the signed head has not changed since observation, or verify physical bytes itself. Production implementation must obtain fresh protected evidence and perform an authorized, recoverable physical handoff before any durable active receipt or ordinary launcher can be advanced.

## Recovery guardrails

In particular, the pre-existing `restore_previous_selection()` in the untrusted candidate-selection layer predates an externally committed witness head and is **not safe to invoke once any CAS may have occurred**. Neither a currently observed predecessor head nor an editable local proposal file proves that an outstanding external writer is absent. Before wiring a production update workflow, this legacy method must be fenced against post-proposal rollback and all service-writer processes must be demonstrably excluded. Slice 48 does not alter that legacy method and **must not be interpreted as fixing it**.

## Deferred work

Introduce a truly protected coordinator with service-owned writer exclusion, OS-process joining, physical slot verification, durable active receipt commit, crash-consistent recovery and launch gating. Execute full Windows crash/power-failure acceptance with real signed releases. Only after those checks may any recovery lifecycle be marked complete.
