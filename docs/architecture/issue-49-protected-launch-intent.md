# Issue #49 — Slice 90: protected non-dispatching launch intent

## Purpose

Following Slice 89's protected non-activating launcher readiness preflight, a
separate service-owned ledger records that a particular **installation,
transaction, signed successor, executable identity and service boundary** has
passed renewed verification. The reservation itself is **not an authorization
to start a process**. This is a diagnostic bridge toward an explicitly distinct
future launch dispatch design.

The protected row has status
`LAUNCH_INTENT_RESERVED_NO_PROCESS_DISPATCH` and authority
`NO_PROCESS_EXECUTION_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY`.

## Protected chain

The ledger uses the **same** protected SQLite connection as Slices 78–89. The
service must independently authorize every operation. Inside one
`BEGIN IMMEDIATE` transaction it verifies the caller's canonical request,
protected finalization reservation, publication preclaim, successor receipt,
deployment intent, prewrite marker, one-shot local receipt dispatch claim,
local convergence certificate, capsule-clearance preflight, predelete marker,
one-shot deletion claim, postdelete certificate and actual, **persisted** Slice
89 preflight. Missing, mismatched, tampered or already-reserved records fail
closed. A uniqueness constraint enforces once-per-installation reservation.

The renewed independent physical evidence includes the absence of the capsule,
unchanged installed successor receipt, terminated deletion operations,
exclusive filesystem fencing, runtime dependency verification, installed
executable identity, independently provisioned service boundary, and no
in-flight launcher. The coordinator requires **two identical** service-held
samples separated by a fresh signed successor witness check. Their derived
runtime and deletion evidence digests must equal the persisted Slice 89
preflight digests. Any drift or expiry prevents reservation.

## Safety and isolation

This module contains **no** launcher adapter, process-spawning API, executable
path supplied by a teacher, local receipt writer, capsule delete, rollback,
slot switch, or witness-CAS operation. Intent replay is refused without new
physical probes. A failure before COMMIT cannot produce a partial protected
intent; a committed row does not grant future execution authority.

Dataclass values and callbacks are *not* proof of OS custody. Independently
provisioned Windows service identity, ACL protection, read-only file
inspections, no-inflight locks, physical durability, crash injection, and
real launcher behavior are external acceptance gates. Passing Python unit
tests does not satisfy these obligations.

## Future boundary

A later slice can define its own protected one-shot prelaunch uncertainty
barrier and a separate, independently authorized dispatch adapter, but it
**must not** treat the presence of this record as a bearer capability or
permission to execute.
