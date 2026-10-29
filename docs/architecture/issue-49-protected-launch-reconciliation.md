# Issue #49 — Slice 93: Protected post-launch uncertainty reconciliation

## Scope and boundary

Slice 92 creates `plan_launch_dispatch_v1` before invoking an independently administered launcher **at most once**. A lost acknowledgment, missing process, or process crash may leave the outcome uncertain. Slice 93 observes that **existing** one-shot claim. It cannot invoke a launcher and must not convert uncertain outcomes into retry authority.

`ProtectedLaunchReconciler` uses the **same protected SQLite connection** and service authorization as Slice 92. Its `reconcile_once` entry point requires the complete, persisted Slices 78–92 lineage, including the exact armed prelaunch marker, exact launch-intent reservation, and exact dispatch claim. It does not reconstruct launch authority from a caller-provided claim alone.

## Durable and external ordering

1. Authenticate the service operation; refuse missing or malformed evidence or an active transaction.
2. Enter `BEGIN IMMEDIATE` and reread the protected local receipt and every persisted recovery/launch record through the existing guarded service methods. Compare those records to the supplied typed lineage. Require the exact one-shot dispatch claim. Refuse duplicate reconciliation **before** new external observations.
3. Obtain an independently fenced deletion-termination report, current capsule/installed-receipt readback, and service-owned process-start observation. Reject an in-flight deleter, changed successor, reappearing capsule, mismatched service/executable identity, second-dispatch evidence, or changed protected classroom data.
4. Verify a **fresh, signed successor witness** between two matching, independent physical/process samples. A callback return is not evidence of process start.
5. If both independent process samples report `True`, append a single protected SQLite certificate, `PROCESS_START_INDEPENDENTLY_RECONCILED_NO_ACTIVATION_AUTHORITY`, and commit. The certificate binds the exact launch dispatch claim hash, executable and service identities, target, and process observation digest. It is diagnostic **only**.
6. If both samples report `False`, return `PROCESS_NOT_OBSERVED_NO_RELAUNCH_AUTHORITY` without a certificate. If both report `None`, return `PROCESS_OUTCOME_UNKNOWN_NO_RELAUNCH_AUTHORITY` without a certificate. Contradictory samples or invalid service fences are refused, not classified as success.

The original Slice 92 dispatch claim persists in all cases. Absence of a Slice 93 certificate never authorizes a second process dispatch. Re-running **inspection** after a false or unknown observation may discover a previously unobserved start, but is not a launch retry. Once the certificate exists, repeat certification is refused.

## Trust distinction and production acceptance

This slice defines a guarded coordinator and test-only service callbacks. Its Python protocols and dataclasses are **not proof of OS isolation, process identity, PID-reuse exclusion, executable signature verification, service custody, or reliable Windows process-start auditing**. The independently administered Windows service must prove these properties in separate production acceptance. A process-start observation is not application health, readiness, successful user session, activation, or a license to modify slots. Slice 89's prelaunch `no_launcher_execution_attempted` observation must not be misrepresented as a fresh postlaunch fact.

`ProtectedLaunchReconciler` implements no `launch`, `retry`, `activate`, `rollback`, `switch`, or filesystem writer. These authorities cannot be inferred from the certificate or diagnostic statuses.

## Crash and concurrency model

The one-shot dispatch claim is already committed by Slice 92 before any external process-start call. Slice 93 can be restarted after a lost acknowledgment without calling the launcher. A reconciliation transaction contains all locked readbacks and the optional certificate insert; a crash before its commit leaves the earlier launch claim and allows inspection again, **not dispatch**. A crash around reconciliation commit may make the certificate's status uncertain; the caller must use authorized read-only `observe` rather than assuming failure or recreating a launch. The SQLite primary key and guarded duplicate check prevent normal duplicate certification; recovery from database corruption remains an administrative concern, not automatic replay authority.

## Non-goals

No actual Windows `CreateProcess`, privileged service installation, activation acknowledgement, slot switch, post-start application health acceptance, cross-host leader election, rollback, deletion, or teacher-facing launch command is introduced.
