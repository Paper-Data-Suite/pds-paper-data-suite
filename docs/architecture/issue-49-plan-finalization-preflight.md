# Issue #49 — Slice 77: successor finalization preflight without publication

## Decision: finalization must not be a stale report or a local-only write

Slice 76 can reauthenticate a plan-bound successor using an independently pinned service HTTPS exchange, signed witness observation and two installed publisher/pip/native byte audits. It cannot safely authorize active-receipt publication or recovery-capsule deletion. In particular, a locally constructed `PlanForwardRecoveryReview` is forgeable, the local candidate-selection pointer is mutable, and the cooperating Python selection/journal locks do not isolate privileged writers. Slice 77 therefore adds **one more read-only preflight** before designing a durable finalizer. It expressly does **not** finalize the update.

`inspect_plan_finalization_preflight()` consumes the exact Slice 73/74 plan records, Slice 75 stopped-writer result and Slice 72 inert selection. It reparses the canonical witness request with the existing Slice 75/74 helper. Rather than accepting a supplied Slice 76 review as a bearer credential, it **calls Slice 76 again** with independently provisioned service client, witness transport, pinned keys and release trust. This redoes the established one-shot mTLS authenticated service observation and real installed-byte requalification. An operator-supplied result cannot skip that call.

## Locked local preflight, after independent review

The coordinator then reacquires the existing **selection → journal** cooperating locks (the same lock order used by Slice 43), rereads the durable exact successor proposal and verifies its parsed canonical request against the plan. The existing Slice 43 `_snapshot()` requires the pending recovery capsule, its exact old selection preimage, inert candidate selection and activation-intent journal to be present and byte-consistent with the proposal and both active-receipt contents. The preflight explicitly requires `_snapshot() == stored_proposal_snapshot`; this protects against changing local claim bytes between persistence and inspection (within the cooperative-lock threat model).

While those locks remain held, the coordinator obtains a **new** independently signed successor witness observation via `inspect_uncertain_witness_commit()`. Only the exact successor digest, generation, revision and `SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED` status are accepted. It rereads the proposal and local snapshot before releasing locks; any missing file, symlink/reparse refusal, lock contention, head mismatch, readback drift or elapsed budget violation fails closed. All existing API errors preserve pending state. The lock files are temporary coordination artifacts, not finalization records.

The result carries hashes of the proposal, pending selection, recovery capsule, journal and service envelope, plus the exact request/successor identities. It has status `LOCAL_FINALIZATION_PREFLIGHT_REVIEW_ONLY_RECOVERY_CAPSULE_REQUIRED` and authority `NO_RECEIPT_WRITE_CAPSULE_CLEANUP_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY`. The capsule remains untouched. It contains no receipt-publication or activation method, no approved unlock record, and no teacher CLI/HTTP writer. No active-receipt or software installation file is changed.

## What Slice 77 cannot establish

- The independently provisioned service must actually hold a protected TLS signing key and pin, authenticate operator consent, and stop/join all potential CAS writers; a Python callback or dataclass does not establish that.
- The remote physical-byte review and subsequent local locked snapshot are **not one atomic protected filesystem transaction**. Same-user tampering, external privileged writes and independently changing witness state remain possible after observation. A 30-second elapsed budget does not fix that.
- The current `UntrustedActiveReceipt` schema is a strictly parsed hashable claim, **not an OS-protected active-installation record**. A signed witness successor must not be copied into a teacher-writable file and treated as launch entitlement.
- Existing local atomic helpers use rename and best-effort fsync; they do not provide a multi-file transaction across local receipt, journal, pointer and pending capsule, nor crash-safe cleanup of uncertain prior CAS.
- The next slice must design and validate a **separately administered durable finalization transaction**, with protected receipt storage, authenticated service-bound current-state comparison, physical installation verification, rollback refusal, explicit recovery states and idempotent crash reconciliation. No recovery capsule may be erased before protected finalization is independently read back. Production launch eligibility is still a later independent decision.

## Guardrails

This slice is four new files only. There is no package installation, witness CAS attempt, selection mutation, local receipt publication, recovery-capsule deletion, classroom workspace mutation, upgrade activation, or `pds launch` change. An unresolved or predecessor-only signed head remains fenced. Local synthetic tests replace only the previously tested pinned-remote/physical verification; actual signed local witness reads, protected-candidate proposal parsers, cooperating locks and recovery capsule are exercised. Full Windows qualification remains mandatory before commit.
