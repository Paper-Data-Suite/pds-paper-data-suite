# Issue #49 — Slice 78: independently protected finalization reservation

## Decision: durable pre-publication fence, not an active-receipt write

Slices 73–75 drafted, admitted, and once-only dispatched a canonical witness successor. Slices 76–77 read back an independently pinned service/witness head, reaudited successor package/native bytes, and inspected the exact pending local selection/capsule/journal under cooperating locks. None of those checks establishes authority to finalize an installed system: local dataclasses and files can be replaced by the teacher-local process; earlier service observations may expire or drift; a signed witness head does not prove physically installed bytes remain unchanged.

Slice 78 adds an **opt-in, independently administered service-side SQLite reservation**, keyed once per installation. It is named `PREPARED_NO_ACTIVE_RECEIPT_WRITE`. This is a *precondition for designing a future atomic protected finalizer*, not a capability to publish active receipt bytes or clear pending recovery. There is no teacher CLI, HTTP writer route, arbitrary package execution, launch permission, witness CAS, slot mutation, journal phase update, capsule deletion, or rollback.

## Admission input and independent trust obligations

`ProtectedPlanFinalizationFence.reserve()` accepts the exact canonical serialized witness commit request and a Slice 77 `PlanFinalizationPreflight` review. Both are **untrusted values**. The coordinator reparses the canonical bounded request and successor receipt; checks that request hash, installation, transaction, successor hash/generation, and witness revision agree with the report; refuses altered status/authority and noncanonical SHA values.

Before entering SQLite's `BEGIN IMMEDIATE` transaction it requires:

1. `authorize(installation_id, "reserve_finalization", service_context)` to return literally `True`. The service actor identity is provisioned and authenticated outside classroom-controlled state.
2. A separate service-owned `independently_read_evidence(request, service_context)` callback to provide `IndependentFinalizationEvidence`. In production this callback must independently inspect a current stopped-writer witness state, authentic physical package-byte audits, operator consent, and exact protected installation/pending-recovery preimages. A client-provided callback or a dataclass copied from Slice 77 **is not evidence of independent verification**.
3. Exact agreement on the canonical request hash, signed head revision, successor generation/hash, local proposal/selection/capsule/journal digests, and signed service envelope digest. The service also supplies its own 64-character digest of independently controlled evidence; missing, altered, or false stop/bytes/consent assertions are rejected.

The source-level callback contract cannot establish protected OS key custody, ACLs, signing, operator identity, process isolation, global writer control, package provenance, physical installation ownership, or stable external checkpoint trust. Deployment remains blocked until these are actually independently provisioned and accepted. In-memory SQLite and synthetic callbacks in tests are never production substitutes.

## Durable state and crash semantics

The service-side table is `plan_finalization_fence_v1`, with `installation_id` as its primary key. The sole representable state is `PREPARED_NO_ACTIVE_RECEIPT_WRITE`. Within one SQLite `BEGIN IMMEDIATE` transaction, reserve requires no existing installation row, inserts the immutable exact digest tuple, and commits once. There is no UPDATE, DELETE, reset, rearm, automatic retry, or compensation method. A replay is refused **even with identical request bytes**; a different successor for the same installation is also refused.

If the process dies before COMMIT, SQLite transaction recovery may leave no row. If COMMIT acknowledgement is lost, the service must inspect `observe()` with independent authorization; **do not automatically replay**. Since this slice does not touch local receipt/capsule files, a missing row does not imply active state; later service-owned reconciliation must inspect the full checkpoint/physical state before any action. The service administrator must enforce SQLite FULL-sync/durable storage and ACLs, backup policy, exclusive finalizer ownership, and crash validation; Python code cannot enforce those platform guarantees.

`observe()` requires independent authorization, checks the only accepted marker and digests, and returns a non-authorizing `ProtectedFinalizationReservation` or `None`. It never implies the publisher executed or cleanup is permitted.

## Follow-on implementation boundary

A subsequent slice must design the physical finalization transaction with clear ordering and durability for: protected OS-level receipt preimage and target receipt publication, independently verified witness successor, authenticated writer quiescence, journal/selection consistency, recovery capsule persistence until confirmed completed, crash recovery for all partial writes, and explicit teacher launch readiness *after* independently verified completion. No token created in Slice 78 may be trusted as a bearer grant; subsequent operations must refresh physical and remote state under an independently administered lock/fence. An installation not independently controlled must remain in pending recovery, with manual service remediation instead of opportunistic rollback.
