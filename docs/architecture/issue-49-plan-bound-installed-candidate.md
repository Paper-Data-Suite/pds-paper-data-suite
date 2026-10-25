# Issue #49 — Plan-bound staged-candidate correspondence (Slice 67)

## Problem and boundary

Slice 65 exposes a witnessed, signed-catalog update plan. Slice 66 checks the
complete signed physical wheelhouse against that plan. A **separate stage
verification** is still necessary: a publisher-authorized wheel on disk does
not establish that its bits, generated console wrappers, interpreter, and
native launch files were installed into the proposed isolated environment.

Slice 67 introduces `inspect_plan_bound_staged_candidate` as a **read-only
composition-to-installed-byte coordinator**, not an installer. The caller
supplies a previously and independently authenticated witness observation,
root-pinned catalog cache, exact requested targets, candidate prepared
transaction bytes, root-signed dependency-lock and publisher envelopes, and
root-signed native-stage evidence. All paths are explicit.

## Fail-closed checks

1. Confine both candidate stage and wheelhouse beneath an ordinary software
   root that is disjoint from the existing classroom workspace. Refuse
   symlink/reparse directory paths and overlapping stage/wheelhouse directories.
2. Recompute the signed complete wheelhouse approval against the exact plan,
   including publisher signatures for every selected registered PDS wheel and
   the root-signed transitive wheel lock.
3. Reverify the supplied prepared record against the exact signed wheelhouse.
   Check transaction roots, runtime, registry/lock digests and revision, all
   selected wheel filenames, versions and hashes, and every external wheel.
4. Reread the staged installed pip/native inventory through Slice 60's
   complete publisher-bound and root-signed native auditors. Its transaction,
   registry digest and signed PDS wheel identities must equal the plan.
5. Repeat all three observations, comparing results for drift; reject any
   mismatch or changes to the confined paths.

The returned result carries transaction, baseline witness revision, signed
lock, prepared-file, staged-pip, and native evidence digests. It is deliberately
incapable of selecting an active slot, writing a receipt, launching code, or
installing a package. No implicit network requests or subprocesses occur.

## Remaining operational work

A caller cannot treat its own witness observation, prepared JSON or the
returned diagnostic result as authorization. A trusted update manager still
needs protected witness/key custody, a real acquisition path for signed
transitive artifacts, explicit mutation consent, a controlled staging installer,
cooperating locks, protected active selection and receipt finalization, actual
foreground launcher acceptance, and package-preserving rollback. Those
boundaries are not supplied by this slice.

This is an additive module and does not change `pds launch`, `pds update`,
`pds modules`, `pds doctor`, bootstrap, or classroom workspace ownership.
