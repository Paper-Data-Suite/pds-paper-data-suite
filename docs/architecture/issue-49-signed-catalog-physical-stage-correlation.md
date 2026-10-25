# Issue #49 — Slice 60: signed catalog ↔ physical staged composition correlation

## Purpose

Slice 59's `pds modules --compare-local-metadata` displays the version reported by the *current interpreter*, which a local process may alter freely. It is neither evidence of installed-wheel bytes nor a verified active installation. Slice 60 introduces a separate **explicitly invoked, read-only library coordinator** for *staged candidate* evidence, named `inspect_catalog_bound_staged_bytes`. The existing teacher-facing `pds modules` command and historical `pds launch` path are unchanged. In particular, **the Slice 60 function is not called automatically by `pds modules`** and cannot authorize launch or activation.

## Inputs and checks

Callers must independently provision and verify an authenticated catalog snapshot and public-key trust ring. The coordinator takes the original root-signed registry, root-signed dependency lock and native-inventory envelopes, delegated module release envelopes, prepared record, wheelhouse, staged virtualenv location, and current aware clock. These inputs are not launch credentials.

1. Reverify the registry signature against the externally trusted keyring; refuse unless the fresh verified record exactly matches the cached registry.
2. Reverify each supplied publisher release envelope and require it to equal the cached verified module document. The cached snapshot and independently supplied signed envelopes must not be mixed across revisions or publisher identities.
3. Parse the untrusted prepared record. Require its registry digest and trust fingerprint to match the authenticated registry. For every PDS distribution in the prepared wheel set, require an exact version, filename and SHA-256 hash from its publisher's *current signed* catalog release claims. Refuse revoked, unlisted or mismatched releases and missing/extra module envelopes. Root-locked transitive dependencies are separately audited by the existing whole-wheelhouse auditor, not promoted to PDS publisher identity.
4. Invoke the existing `audit_publisher_bound_pip_candidate`, which independently verifies signed publisher wheels, root lock, installed pip-file hashes, RECORD and console-script ownership. Invoke `verify_signed_staged_native_evidence`, which independently checks root-signed native launcher and interpreter byte inventory.
5. Perform the pip/native pair of reads twice, rejecting inconsistent results, mismatched transaction IDs, signed registry or lock digests, publisher digests or stage identity. This is a drift-detection precaution and **not** an atomic snapshot.

The returned `CatalogStageCorrelation` holds only component IDs, exact staged version/wheel hashes, publisher payload hashes and observed pip/native digests. Status is `SIGNED_STAGED_BYTES_OBSERVED_NOT_ACTIVE`, with **no launch, update, rollback, active receipt, CAS or activation authority**. Existing independent witness checks and protected active-receipt/slot transition remain mandatory for an eventual production launch path.

## Security limitations

Authenticated package and native byte observations do not establish trusted *active* installation state. The caller must not substitute metadata from the current interpreter for the physically audited stage. The stage's on-disk bytes remain subject to local replacement between reads; OS-protected locks/permissions and active selection need a separate implementation. Test doubles exercise coordinator sequencing and refusals; the delegated publisher/pip and native auditors are tested in their own earlier slices. This slice does not provision a signer, TLS service or trusted monotonic checkpoint, run any package, or read classroom data.

## Follow-on integration

A subsequent slice can expose this richer candidate audit under explicit teacher review once approved staging paths, trust bootstrap and physically separate software roots are provisioned. Active installed-state verification, signed witness continuity, safe activation and evergreen launcher routing remain independent requirements. No production `pds launch` path should consume this status as permission to execute.
