# Issue #49 — Slice 25: Journal-bound publisher/pip/native candidate preflight

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Exact base:** `52f5233754d536583f4084e1dc1a1a151c064b99`
**Disposition:** Read-only software-lifecycle evidence, not managed activation.

## Purpose and contract

The new `inspect_journal_bound_publisher_pip_candidate` provides one bounded
entry point to correlate previously independent proofs of one candidate:

1. A pending journal at revision 1, `candidate_verified`, with exact digest
   commitments to the prepared record, root registry, dependency lock and
   root-signed staged executable inventory.
2. The root-signed dependency lock AND delegated, independently signed release
   evidence for every registered PDS distribution in the full closure.
3. A genuine pip-style installation whose source files, `RECORD`, authorized
   console launchers, and local-wheel `direct_url.json` match authenticated
   wheel inputs, without allowing uncontrolled scripts or code-generation paths.
4. The exact signed staged Python interpreter and native console executable
   digests from the root-native evidence policy.

The journal stage and wheelhouse must remain distinct, safe directory children
of a software root outside the teacher's classroom workspace. The selection
and transaction locks serialize cooperating update writers. Pending candidate
selection recovery blocks the observation. The caller may supply only a
host-compatible layout, and the candidate must be unarmed. The package and
native audits are repeated before returning; journal and publisher-input
snapshots are checked again after inspection.

`ObservedJournalPipCandidate` records transaction ID, journal revision,
software-relative paths, source and native inventory digests, delegated
publisher identities, supported external dependency identities, and public
root launcher targets. It intentionally exposes **no** `can_launch`,
`activate`, `qualified_integration`, or active receipt assertion.

## Security boundary and remaining work

A root-signed lock proves a dependency closure, not every PDS publisher.
Authenticated PDS publisher releases do not prove unauthenticated external
wheel provenance. In particular, Core must have an independently qualified
release authority whenever it is used as a critical installed dependency.

Signed native evidence depends on trustworthy production provisioning and
cannot be self-signed by the teacher's installation. The locally editable
journal is not a protected monotonic receipt. A same-user attacker can race
filesystem reads, replace an entire software directory, or change both the
journal and selection pointer; cooperative locks and repeated observations
do not establish a hardened OS execution boundary.

There is no real installer, live module invocation, launcher wiring, activation,
receipt commit, automatic update discovery, or student data access here.
An honest production update still requires OS-safe immutable candidate staging,
independently authenticated interpreter and external dependency provenance,
Core and named module contract acceptance, protected active-state continuity,
explicit user authorization, and tested activation/rollback recovery.
