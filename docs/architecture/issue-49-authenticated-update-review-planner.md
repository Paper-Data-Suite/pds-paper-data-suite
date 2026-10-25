# Issue #49 — Slice 64: authenticated composition update review

## Scope

Introduces a **pure, deterministic review planner** for one requested PDS-module version change, explicit addition/removal, or multiple requested changes. It works from a separately signature-verified `CatalogSnapshot` (Slice 4) and a fresh `WitnessSelectedStageObservation` (Slice 62). Both are **inputs**, not a new trust root: a caller must provision trust and obtain fresh evidence independently. No filesystem, subprocess, network or API access happens inside this planner.

This is not a production update plan yet. It is a **candidate plan precursor**. The selected-stage observation is transient, local software can be replaced after inspection, signed release claims do not prove downloaded wheel bytes, and the planner cannot authorize installation or launch. All later protected activation, independent trust provisioning, signed external-wheel lock, physical stage inspection, runtime contract and rollback requirements remain mandatory.

## Plan inputs and semantics

- `snapshot`: authenticated signed registry, module-release documents and signed exact integration claims.
- `observed`: previously obtained read-only witness-selected, physically correlated stage observation, **not** a protected active-installation credential.
- `requested_targets`: explicit map from approved registered PDS component IDs to exact signed release versions; `None` deliberately removes an already observed module. All other observed modules remain unless a declared dependency forces an approved version change.
- `python_minor`, `platform_tag`: review target environment, not independently trusted deployment facts. Wheel tag and native/platform installation acceptance remain separate.

The planner refuses unknown IDs, unknown/revoked targets, altered baseline wheel hashes, mismatched delegated publisher identities, an empty final composition, invalid runtime requirements, direct URL or extras dependencies, conflicting explicit removals/versions, unsatisfiable dependencies, and bounded-iteration cycles.

Its dependency closure algorithm prefers the existing signed release when acceptable; otherwise it selects the highest matching **non-revoked, Python-compatible signed release** for required registered PDS modules. It does not silently delete other modules or resolve arbitrary external packages. A conflicting graph is refused rather than optimistically installed. The required signed root-authorized full wheel lock (including all transitive dependencies) is still unverified at this stage.

The proposed changes include `ADD`, `UPGRADE`, `DOWNGRADE`, `REMOVE`, `UNCHANGED`, originating from teacher request, dependency closure or retention. Per-feature impact is derived only from a matching signed **exact artifact** and Python/platform scope; losing one claim never globally blocks the application. External `Requires-Dist` entries are enumerated for later signed lock planning.

## Security model / next boundary

`CompositionReviewPlan.status` and `.authority` explicitly deny execution and mutation. Neither the planner nor its output can be passed as an activation credential. Subsequent slices must bind this plan to actual versioned/downloaded publisher wheel evidence, root-authorized complete wheel lock, platform wheel tags, native payload signatures, explicit teacher confirmation, and a protected active receipt under a controlled recoverable transaction. The public teacher-facing CLI is not changed in Slice 64.
