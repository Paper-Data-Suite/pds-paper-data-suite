# Issue #49 — Slice 89: Protected, non-activating launcher readiness preflight

## Boundary and intent

Slice 88's `CAPSULE_POSTDELETE_RECONCILED_NO_LAUNCH_AUTHORITY` is a **completion certificate for deletion recovery**, not a permission to run the successor. Slice 89 adds a separate, one-shot **read-only preflight** on the same independently provisioned, service-owned protected SQLite connection. It does not start any executable, switch active slots, clear another artifact, invoke witness CAS, retry the local receipt writer or repeat deletion.

The new stored status is:

`LAUNCH_READINESS_PREFLIGHT_RECORDED_NO_LAUNCH_DISPATCH`

The negative authority is:

`NO_LAUNCH_SWITCH_ROLLBACK_CAS_REDELETE_OR_WRITER_AUTHORITY`

The table `plan_launcher_readiness_preflight_v1` is append-once by installation id and records installation/transaction/request/successor, generation/revision, complete postdelete certificate digest, exact deletion claim digest, pinned local receipt and capsule identities, independent launcher runtime evidence digest and independent repeated postdelete evidence digest. An exception before COMMIT leaves no stored preflight; the caller must resolve the protected state rather than interpreting an uncertain transaction as launch authorization.

## Protected chain and physical evidence

Under service `BEGIN IMMEDIATE`, the coordinator checks the exact canonical request, finalization reservation, publication preclaim, protected receipt, local deployment intent, prewrite uncertainty marker, receipt dispatch claim, protected local convergence, capsule clearance preflight, capsule predelete uncertainty, capsule delete claim and postdelete completion certificate. The actual durable protected records must match their expected values. The postdelete certificate must retain its original negative authority and bind the exact protected deletion claim.

The independently operated service (not the teacher application) must keep the relevant OS installation and directory fences **continuously held** during two physical examinations and the fresh signed successor witness read. Each examination obtains:

1. Independently accounted delete-operation termination bound to the exact deletion claim and capsule identity, with no remaining/resumable deleting or writing process and verified directory durability.
2. Independent postdelete readback of the **actual exact successor receipt bytes**, original pinned filesystem identities, selection and journal, and physically confirmed capsule absence. A present/unknown capsule fails.
3. Independent read-only launcher/runtime examination binding the protected request, selection and journal, pinned executable and installed dependency graph digests, OS service boundary, absence of in-flight launchers and safety of user/classroom data. The service must certify **no executable was launched** during the probe.

Two samples must agree, with a fresh signed successor witness head in between. No caller-supplied path, JSON claim, `True` boolean, Python callback or dataclass construction is an OS security boundary. Production requires the service to authenticate its own evidence and keep the handle/locks stable across evidence collection and COMMIT. Service ACLs, symlink/reparse resistance, installed code provenance, dependency requalification, crash durability, and hardware/OS fault-injection acceptance remain separate deliverables.

## Critical distinction

A protected readiness preflight is **diagnostic evidence**, not a launch token. Neither its `observe` nor `prepare_once` method provides a launcher operation. Later slices must separately design authorization, single-use dispatch fencing, post-launch observation and fallback procedures. No launch can be assumed safe merely because an immutable preflight row exists; installed bytes, service configuration and environment can change later.

## Fail closed

Wrong actor, forged or drifted protected records, absent Slice 88 certificate, active predecessor or changed successor, capsule reappearance, unsigned witness, in-flight delete/write/launch, changed OS fence or runtime identity, duplicate preflight and mismatched repeated samples all refuse. A crash before/during SQLite COMMIT is resolved by protected `observe`; no automatically repeated effectful action exists in this slice.
