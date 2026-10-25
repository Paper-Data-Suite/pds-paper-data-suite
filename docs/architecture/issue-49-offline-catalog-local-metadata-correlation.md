# Issue #49 — Slice 59: opt-in offline signed-catalog / local package-metadata correlation

## Purpose

Extend Slice 58's already authenticated offline catalog preview with a separately requested `pds modules --compare-local-metadata` mode. It reads package-version metadata visible to **this Python interpreter** using `importlib.metadata.version`, and correlates each reported version with the releases in the previously authenticated, digest-pinned catalog snapshot. The local package metadata remains **untrusted**, even when a version string matches a signed claim. Existing `pds modules` and Slice 58's signed-catalog-only preview remain unchanged.

The three original Slice 58 options (`--catalog-cache`, `--trust-policy`, `--trust-sha256`) remain mandatory; the comparison flag without all three refuses with usage status 2. All flags are explicit and read-only. There is no automatic remote catalog fetch, no credentials or key installation, no module import, no subprocess, no package write, and no interactive activation.

## Classification and limits

For each component registered by the cryptographically verified root registry, report the distribution's observed package metadata version or its absence. State separately whether there is a matching **signed release claim**, whether the matching release is revoked, whether there is no current signed release document, or whether the locally reported version is unlisted. Bound and reject unsafe version fields, including control characters and excessive lengths. Refuse unsupported snapshots and classify metadata-reader failures generically without leaking paths, exceptions or free-form metadata payloads.

A missing version means **the current interpreter** reports no matching distribution; it does not prove that no software exists elsewhere. A matching signed version (and its claimed wheel SHA-256) means only that a released wheel has the *same version label*. No installed wheel bytes, installed `RECORD`, native executable, launcher ownership, active environment selection, update journal, independent witness head, or OS-level authorization has been validated. Do not derive `LaunchPreflight` from these observations. Revoked and unlisted local metadata must not fall back to historical bundled qualification as an approval decision.

## Follow-on gates retained

The core Issue #49 objective still requires a protected authoritative active-composition receipt, fresh physical installed-byte revalidation, trusted publisher and dependency-lock checks, verified interpreter and launcher confinement, atomic update finalization/recovery, and `pds launch`/doctor/bootstrap integration. Slice 59 intentionally does not claim these are solved. This is the first non-mutating teacher-facing bridge between signed publisher release discovery and the current interpreter's observable distribution versions.
