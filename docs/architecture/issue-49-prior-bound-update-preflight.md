# Issue #49 — Slice 14: Prior-bound update preflight

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `6ec9065` (guarded runner verifies exact full commit)
**Status:** Read-only, isolated infrastructure; not production activation.

## Purpose

Before treating a proposed update as safely reversible, verify **both** the candidate software and the physical software that would be restored on rollback. A locally editable selection pointer or a text receipt is not sufficient to establish the prior installation's integrity. The preceding slices supply authenticated wheel locks, per-wheel metadata checks, staged Python/console metadata, signed native executable evidence, a prepared composition, an update intent journal, candidate selection and an observed previous-slot record. Slice 14 binds those boundaries together for **one read-only preflight**.

`paper_data_suite.evergreen_prior_update.verify_prior_bound_candidate` takes an approved software root distinct from the classroom workspace, an exact transaction ID and journal revision, raw candidate signed documents, raw prior signed documents, a prior observation record, an independently supplied trusted keyring, and an aware clock. It never trusts caller-constructed `Verified*` data as its authority.

The preflight requires:

1. An existing journal in the `candidate_verified` phase with the exact expected revision, and a nonempty prior-record digest. It rejects armed, aborted and recovery-required journal states.
2. Candidate signed-envelope bytes exactly match all four hashes recorded in the journal. It reconstructs the journal's stage/wheelhouse paths under the approved software root and re-verifies the candidate's authenticated wheelhouse, staged metadata and root-signed native executable bytes.
3. The exact serialized prior observation hashes to the journal's `expected_previous_receipt_sha256`. That record is **then reverified against the currently selected previous slot**, fresh independently trusted signed metadata, source-wheel bytes and native executable bytes; the record itself cannot establish its own trust.
4. Candidate and previous transaction IDs differ, and both software stages and both wheelhouse directories are physically disjoint (no equal/nested directory pairs). This preserves the possibility of restoring prior packages rather than only editing a pointer.
5. The journal timestamp does not postdate verification. Signed metadata must satisfy its current freshness windows; this preflight does not reinterpret expired online metadata as protected offline-installation provenance.
6. No pending selection recovery is present. A recovery marker causes previous-slot re-verification to fail closed rather than permitting another update.

Output is `ObservedUpdateContinuity`: transaction IDs, observed selection generation, journal revision, the exact previous-record digest, and bounded root-relative stage/wheelhouse references. This dataclass has no `can_launch`, `installed`, `active`, `authorized_rollback`, or equivalent privilege.

## Explicit authority limitations

The previous-record digest **stored in the same locally replaceable journal** is a reference-binding check, not a protected monotonic anchor. An attacker who can replace the journal, prior selection and record can claim a false history even though the current bytes match an authentic published release. The preflight therefore cannot prove that the prior environment was historically active or successfully installed.

The check is also not transactional with subsequent mutation. A real activator MUST repeat it under a coordinated lock and verify durable protected continuity before changing a production environment. The approved production root-signing publication process, native Windows interpreter/wrapper provenance, real `pip` installation acceptance, Core/module provider smoke checks, persistent activation receipts, and safe rollback activation remain future gates.

**No production integration:** No live `pds launch` changes, no network requests, no installer/pip/subprocess execution, no package or pointer mutations, and no reads or writes to classroom data. This slice adds no private signer material. Synthetic private keys remain in tests only.

## Next step

Use the reverified prior/candidate boundary inside a properly coordinated update transaction; establish durable active-state authority and safe activation/rollback before connecting `pds update`, `pds doctor`, or normal module launching. An unprotected, internally consistent observation is not grounds to launch software.
