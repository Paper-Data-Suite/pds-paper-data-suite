# Issue #49 — Slice 92 protected one-shot launch dispatch

## Boundary and scope

Slice 92 adds `ProtectedLaunchDispatcher` and its durable SQLite table,
`plan_launch_dispatch_v1`. A record of status
`LAUNCH_DISPATCH_CLAIMED_PROCESS_OUTCOME_UNCERTAIN` is committed **before**
a single externally administered process-launch call. This contract is the
next boundary after the separately committed Slice 91 prelaunch marker.

The protocol revalidates the protected Slice 78–91 chain under one SQLite
`BEGIN IMMEDIATE` transaction, checks its immutable exact records, confirms
the absent recovery capsule and successor receipt, repeats the independently
pinned runtime/OS-fence and delete-termination observation, and checks a
fresh signed successor witness head between matching samples. No operation
can be dispatched without a previously persisted one-shot prelaunch marker.

## External launch contract

`IndependentProcessLauncher` is an interface for a separately provisioned
privileged service and must never be implemented by a teacher-controlled
callback in production. Its executable identity comes from the protected
launch-intent reservation, not from an arbitrary path supplied by a caller.

The library **does not contain a Windows process-launch implementation**. It
cannot prove OS custody, ACL protection, actual executable integrity,
service process identity, exclusive launch fencing, correct process-tree
ownership, durable SQLite deployment, or immunity to same-user tampering.
These require separately verified service implementation and acceptance.

A crash or exception after commit, lost callback acknowledgment, return from
a no-op launcher, or inconclusive independent readback leaves the claim in
place. A second call refuses **before** any physical or witness inspection.
There is no automatic retry, second process start, rollback, slot switch,
file cleanup or activation authority. Recovery may only inspect, not launch.

## Readback

`IndependentProcessStartReadback` is diagnostic only, and its booleans and
identities must be independently provisioned and protected. Positive process
observation is not authentication of process ownership, readiness, health,
installation activation or permission to switch the teacher's active slot.

The immediate diagnostic states are:

- `PROCESS_START_OBSERVED_ACTIVATION_NOT_AUTHORIZED`
- `PROCESS_NOT_OBSERVED_NO_RETRY_AUTHORITY`
- `PROCESS_OUTCOME_UNKNOWN_QUARANTINE_REQUIRED`

All retain `NO_RELAUNCH_ACTIVATE_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY`.
Future process attestation, health, runtime crash reconciliation and true
activation require separate protected boundaries and independent acceptance.

## Database and concurrency

The dispatch claim uses the *same* independently administered SQLite
connection as Slices 78–91, with one row per installation and a database
status CHECK constraint. `BEGIN IMMEDIATE` serializes cooperating service
writers and enforces append-once dispatch, but cannot itself fence an
untrusted process or prove filesystem durability. An uncertain COMMIT must
be handled as an unresolved claim: **never rerun the dispatch**.

Production must also enforce cross-process launch fencing and an OS-level
one-shot execution token so a process dying after COMMIT cannot lead to a
second start from another worker. Testing the pure Python callbacks alone
does not establish those guarantees.
