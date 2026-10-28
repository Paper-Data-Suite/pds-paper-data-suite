# Issue #49 — Slice 88: Protected capsule post-delete crash reconciliation

## Trust boundary

Slice 87 commits `CAPSULE_DELETE_DISPATCH_CLAIMED_OUTCOME_UNCERTAIN` **before** a one-shot independently operated capsule deletion. An unavailable callback, lost acknowledgment, crash, no-op adapter or delayed file operation must never permit deletion to be dispatched again. Slice 88 is *only* an independent reconciliation/certification protocol after that claim. It does not perform a filesystem operation or dispatch any deleter.

## Durable state

One protected SQLite table, `plan_capsule_postdelete_reconciliation_v1`, shares exactly the service-owned database connection of Slices 78–87. The immutable certificate is:

`CAPSULE_POSTDELETE_RECONCILED_NO_LAUNCH_AUTHORITY`

Its authority string remains `NO_REDELETE_RETRY_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY`. It binds installation, transaction, request, successor, signed witness generation/revision, SHA-256 of the complete durable Slice 87 dispatch claim, pinned capsule and receipt identities, independently verified absence/fence evidence, and a fresh independently accounted deletion-operation termination digest. It can be inserted **once**. The database's unique installation key and service transaction prevent replacing or repeating an earlier certificate.

## Required inputs

The coordinator requires the exact request/reservation/preclaim/protected receipt/deployment intent/prewrite marker/local receipt dispatch/convergence/capsule clearance preflight/capsule predelete marker and Slice 87 deletion claim. Each protected record must be re-read from the **same** protected SQLite connection under `BEGIN IMMEDIATE`, and must equal the supplied record. No client can choose a local filesystem path, deletion adapter, or recovery operation through this API.

Under independently maintained OS fencing, two separate observations each obtain:

* A service-originated `IndependentDeleteTerminationEvidence` binding the exact deletion claim and capsule identity, all prior deletion operations terminated, no surviving or resumable writer/deleter, exclusive directory fence, directory durability verified, and successor re-audit; and
* An independently operated `IndependentCapsuleDeleteReadback` binding the original active successor receipt bytes, pinned capsule/receipt identity, proposal/selection/journal, actual capsule bytes or physical absence, service fence and durability checks.

A fresh signed successor witness-head check is sandwiched between the independent samples. Any disagreement is a refusal. An independent service must ensure its fenced observations cannot be falsified by the teacher, stale cache, raced path replacement, symlink/reparse point, hard-link alias, or a delayed writer. Mere dataclass construction is **not** evidence of this enforcement.

## Outcomes

`inspect` is read-only and can report:

* `CAPSULE_ABSENT_PENDING_PROTECTED_CERTIFICATION` — exact successor present, no capsule observed; still no launch or retry permission.
* `CAPSULE_PRESENT_NO_DELETE_RETRY_AUTHORITY` — original capsule persists after uncertain dispatch; never dispatch again automatically.
* `CAPSULE_UNKNOWN_QUARANTINE_REQUIRED` — unrelated capsule bytes observed; quarantine and manual recovery required.

Missing/mismatched active successor, broken protected basis, tampered identity, unsupported callback values, unresolved operations, changed OS fence or changed witness all refuse. `certify_once` may append the protected certificate **only** on stable, repeated independently confirmed absence, never on still-present or unknown bytes. A crash around the SQLite commit is treated as uncertain; inspect the durable certificate, do not retry the filesystem operation.

## Intentionally excluded

No capsule deletion, retry, restore, rollback, slot switch, other cleanup, witness CAS or launcher readiness. Certificate verification and any later launcher activation must be independently authorized **in separate future slices**. Production Windows privileged service isolation, ACLs, handle pinning, filesystem persistence/barriers and real fault-injection acceptance are still separate engineering/operational obligations; synthetic Python fixture callbacks do not qualify them.
