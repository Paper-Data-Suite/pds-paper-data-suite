# Issue #49 — Slice 91: protected prelaunch uncertainty

## Scope and security boundary

Slice 91 adds `ProtectedPrelaunchUncertaintyLedger` on the *identical service-owned SQLite connection* used by protected Slices 78–90. This is an immutable, append-once **prelaunch uncertainty barrier**, not a permission token or execution mechanism.

The only new durable record is `plan_prelaunch_uncertainty_v1`, keyed by installation identity. Its status is `PRELAUNCH_UNCERTAINTY_ARMED_NO_PROCESS_DISPATCH`, and its authority explicitly forbids rearming, launch, retries, slot changes, rollback, CAS, and filesystem mutation. There is no process-execution callback, operating-system launcher, file writer or deletion adapter in this slice.

## Binding and transaction sequence

1. Require an authentic protected-service actor and the exact database connection; reject a caller-controlled or in-transaction connection.
2. Reconstruct and check the canonical witness request, reservation, preclaim, protected successor receipt, deployment intent, local prewrite marker, local dispatch claim, convergence record, clearance preflight, predelete marker, delete claim, postdelete certificate, Slice 89 readiness record, and Slice 90 launch-intent reservation.
3. Begin `BEGIN IMMEDIATE`, read the exact durable records from the same database, and compare their full dataclass values to the supplied binding records. Refuse missing, changed, malformed, and replayed entries before any independent physical sampling.
4. Under independently administered service fencing, inspect deletion termination, local successor receipt, capsule absence, launcher/runtime provenance and the status asserting no launcher execution has occurred. The physical reader and launcher reader remain provisioned outside client control; the Python types alone do not prove their provenance.
5. Match the observed executable and service-boundary identities and the canonical runtime and postdelete evidence SHA-256 digests against the reserved Slice 90 launch intent and Slice 89 readiness. Require a fresh signed successor witness head *between two matching independent samples*.
6. Insert the append-once prelaunch uncertainty marker and commit before returning. The marker binds the exact Slice 90 intent and the independently verified runtime evidence. A second arming attempt must be refused without repeating the physical reads.

The marker must never be interpreted as an executable-launch permit. A later service launch dispatcher, if developed, must establish its own independent authorization, durable dispatch claim **before** external process invocation, and no automatic replay after any uncertain launch outcome. This slice does not supply such a dispatcher.

## Crash and separation properties

Crash before database commit means no new prelaunch marker; no process dispatch was possible through Slice 91. Crash after commit leaves a permanent one-shot barrier; a lost acknowledgment is not permission to arm again or to start a process. A protection boundary between a Python callback and the true OS service must not be assumed.

Do not treat the passing synthetic tests as production qualification of privileged Windows filesystem custody, durability, process creation, launcher identity, service permissions, file locking or crash injection. Classroom and user files remain outside this component's mutable scope.
