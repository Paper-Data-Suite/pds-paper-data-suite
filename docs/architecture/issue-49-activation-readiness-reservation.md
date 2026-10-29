# Issue #49, Slice 95 — Protected activation-readiness reservation

## Objective

An independently observed process start (Slice 93) and a protected postlaunch runtime-health preflight (Slice 94) are necessary but not sufficient for installing or activating a new runtime. Slice 95 establishes an **append-once, non-activating reservation** to record a stable activation-fence inspection. It deliberately does **not** implement activation, change a slot pointer, publish an active receipt, start a process, or grant a subsequent call permission to do any of those things.

The only successful state is:

`ACTIVATION_READINESS_RESERVED_NO_ACTIVATION_DISPATCH`

The authority string explicitly denies activation dispatch, slot switching, launch retries, rollback, and filesystem mutation. A reservation is diagnostic evidence, not a capability token.

## Existing protected chain

The `ProtectedActivationReadinessLedger` is constructed from the *actual* `ProtectedLaunchHealthPreflightLedger`, not an arbitrary database connection. The protected SQLite connection is required to be identical throughout the Slice 81–94 chain. It refuses a connection with an external active transaction. Prior to doing any independently managed observation, it checks:

- Canonical request and reserved successor identities.
- Correct Slice 89–93 launch preflight, intent, uncertainty, dispatch, and reconciliation identities.
- A well-formed Slice 94 health record whose SHA-256 values bind it to the exact Slice 93 reconciliation and Slice 92 dispatch claim.
- The **persisted** versions of the convergence, capsule-clearance, predelete marker, delete dispatch, postdelete certificate, launcher readiness, launch intent, prelaunch marker, process dispatch, process reconciliation, and runtime-health preflight. All must match the supplied protected objects.
- No existing Slice 95 reservation for this installation.

After taking `BEGIN IMMEDIATE`, the coordinator reuses the established service-owned physical and witness paths. A sampling pass checks the independently observed deletion-termination fence, exact successor/capsule physical status, unchanged process-start observation, and exact health evidence from Slice 94. A distinct `IndependentActivationFenceInspection` must also assert that the **same process instance** remains bound to the approved executable and service boundary, and that an independently administered exclusive activation fence is held with no prior activation attempt, slot transition, second launch, or in-flight recovery.

A fresh signed successor witness is read **between two matching sample sets**. Drifting observations, missing health, revoked fences, forged records, unreadable durable state, missing signed witness, a reappearing capsule, or a changed successor receipt cause refusal. No step in this code retries a prior launch.

## Persistence and crash behavior

The table `plan_activation_readiness_v1` has an installation-ID primary key, exactly 16 columns, and a SQLite `CHECK` limiting the persisted status to the sole non-activating value. It stores SHA-256 commitments to the Slice 94 preflight, Slice 93 reconciliation, Slice 92 dispatch claim, current process observation, runtime health, and activation-fence inspection.

The reservation commits once under `BEGIN IMMEDIATE`; a duplicate attempt is refused. A failed transaction is rolled back without deleting or altering earlier protected records. On an uncertain SQLite commit, callers must **observe durable state**; they must not retry activation or infer authorization from an exception or callback return. `observe()` validates structure, identity shapes, and the exact status. External connection reopen can inspect the stored row.

## Security boundary and exclusions

`IndependentActivationFenceInspection` is a service-interface contract. Its Python dataclass booleans, callback, and SHA-256 fields are **not** proof that the Windows OS has established a real security boundary. Trust depends on an independently accepted privileged Windows process and activation service, with filesystem ownership, process instance binding, exclusive lease/fencing, and independently signed observations. Unit tests use synthetic evidence.

This slice contains no OS activation operation, process spawning API, slot switch, active receipt mutation, rollback, or privileged service implementation. The next phase must design and qualify a *separate* protected activation intent and any eventual dispatch/reconciliation protocol without treating this reservation as automatic authority.
