# Issue #49 — Slice 94: Protected postlaunch runtime-health preflight

## Boundary

Slice 93 proves only that the one-shot dispatch was independently observed to start a process. **A process start is not a successful or supported application activation.** Slice 94 introduces a diagnostic, append-once health preflight bound to the immutable Slice 93 certificate and the existing protected installation chain. It does not invoke a launcher, touch a slot, mutate the active receipt, or activate an application.

`ProtectedLaunchHealthPreflightLedger` is created on the **same protected SQLite connection** as `ProtectedLaunchReconciler`. It creates `plan_launch_health_preflight_v1` with `installation_id` as a primary key and an exact, checked diagnostic status. It records the immutable hashes of the launch reconciliation, launch dispatch, process observation, and independently inspected runtime health.

The only success status is:

`POSTLAUNCH_RUNTIME_HEALTH_PREFLIGHT_RECORDED_NO_ACTIVATION_AUTHORITY`

The authority is:

`NO_PROCESS_LAUNCH_RETRY_ACTIVATE_SWITCH_ROLLBACK_OR_FILE_MUTATION_AUTHORITY`

A read of an existing record is diagnostic; duplicate recording is rejected. Any failure leaves the launch claim non-retryable and does not grant permission to launch, activate, switch, roll back, or modify files. An indeterminate SQLite commit is treated as uncertain, requiring inspection of durable state before any subsequent separate operation.

## Trust boundary and independent evidence

The coordinator requires the exact canonical request, typed protected records and stored SQLite witnesses, including the Slice 93 launch reconciliation certificate. The certificate must match the dispatch claim and its process-observation hash. Before and after a fresh signed successor-witness observation, the coordinator independently checks:

- Termination of the capsule-deletion operation and the exclusive service fence.
- The expected successor receipt and verified absence of the original recovery capsule.
- Process-start evidence for the exact dispatch and previously reconciled process observation.
- The **same** independently inspected runtime-health attestation: exact process instance and executable identity, service fence, lack of a second launch, readiness-probe success, verified successor, absent capsule, and unchanged protected files.

The runtime attestation carries a process-instance digest, readiness-probe digest, and positive heartbeat sequence. All required booleans must be the real `True`; unknown/false values, forged identities, invalid digests, missing attestations, changed heartbeat or mismatched observations refuse certification. Two identical samples bracket the independently verified signed witness. This does **not** claim a real Windows privilege boundary; a qualified launcher/health-monitor service must implement the independent inspection contract.

## Intentional exclusions

- No activation acceptance, process start, retry, rollback, slot selection or filesystem writer.
- No consumer of this diagnostic status may equate it to authorization to activate.
- No assumption that the Python callback or a synthetic test establishes OS process isolation, persistent liveness or producer authenticity.
- No unattended retry after lost acknowledgment or process disappearance.

A future separately scoped activation-admission boundary must define its own authorization, state transitions, real Windows implementation checks and failure/recovery procedures. It must never infer authority merely from this preflight's existence.

## Qualification

The additive Slice 94 archive includes a single production module, one isolated regression module, this architecture note and a validation record. The guarded Windows runner checks the exact Slice 93 commit, origin, branch and clean scope; performs Ruff import sorting/formatting/lint, strict mypy, isolated tests, all accumulated Issue #49 and CLI regressions, and dependency checks; then commits and pushes only if every gate succeeds.
