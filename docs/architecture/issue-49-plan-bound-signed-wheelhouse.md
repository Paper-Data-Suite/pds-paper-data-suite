# Issue #49 — Slice 66: Plan-Bound Signed Wheelhouse Preflight

## Purpose

Bridge authenticated **read-only update planning** (Slices 64–65) to the actual exact artifact inputs of a future managed installation, without performing installation or enabling a new launcher. A version-only plan is not sufficient to authorize executable packages. Every wheel, including transitive third-party dependencies, must be accounted for in a root-signed, complete lock.

## Contract

`inspect_plan_bound_wheelhouse` accepts authenticated `CatalogSnapshot` claims, a transient `WitnessSelectedStageObservation` from the independent checkpoint and installed-byte audit path, explicit component targets, the target Python/platform, an isolated local wheelhouse, the original signed registry, signed dependency-lock envelope, publisher envelopes for selected modules, and an independently provisioned `TrustedKeyring`.

The coordinator **recomputes** the plan rather than accepting a caller-authored `CompositionReviewPlan`. It requires the complete signed lock's root distribution set to equal the full resulting managed PDS composition. The signed wheelhouse verifier enforces exact wheel digests, wheel compatibility, and dependency closure for the local interpreter/platform. All PDS distributions in the wheelhouse must be registered and present in the plan; unknown `pds-*` dependencies are refused, as are omitted or extra publisher documents. Each selected PDS wheel must match both the signed catalog's delegated publisher document and actual inspected wheel identity/metadata. The audit runs twice and rejects different observations.

External dependencies are not permitted through a generic package resolver. Their exact identity and bytes must be included in the separately authenticated full lock. The resulting report distinguishes publisher-authorized PDS wheels from externally root-locked transitive wheels.

## Boundaries and remaining steps

- This call performs **no network download, wheel installation, module import, script execution, active-slot mutation, witness write, or classroom workspace access**.
- It does not confer permission to stage, activate, issue an installed-state receipt, roll back, or launch. The transient witness observation and catalog trust state must be reauthenticated inside the eventual protected mutation transaction.
- The root-signed lock and publisher key custody must be provisioned independently. Merely putting public keys and signatures alongside the requested wheels is not sufficient to establish an independent authority.
- The lock currently targets **the executing interpreter and platform**, not arbitrary remote build hosts. Cross-platform qualification requires running against each supported target environment.
- Teacher authorization, authenticated release acquisition, actual isolated installation, pip/native/launcher audit, transaction locking, witness CAS/receipt custody, rollback, and final foreground launch remain separate Issue #49 requirements.

No historical v0.1.0 manifest or current `pds modules`, `pds update --plan`, and `pds launch` behavior is changed by this slice.
