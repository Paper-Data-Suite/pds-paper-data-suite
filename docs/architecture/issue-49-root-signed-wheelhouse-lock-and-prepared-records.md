# Issue #49 — Slice 7: Root-signed wheelhouse locks and prepared composition records

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

**Status:** Additive, read-only trust and prospective-installation infrastructure. Production Suite launching, updater, doctor, bootstrap, workspace, and all installed artifacts remain unchanged.

## Dependency lock authority

`evergreen_dependency_lock.verify_signed_dependency_lock` accepts a bounded v1 JSON envelope containing the exact payload bytes in canonical base64, and root Ed25519 signatures over this **domain-separated** message:

```
b"pds-evergreen-wheelhouse-lock-v1\x00" + exact_payload_bytes
```

The caller MUST independently provision `TrustedKeyring` from the digest-pinned / authorized-rotation trust path of Slices 4–5. **Not** from a downloaded lock or self-supplied policy SHA. The verifier reauthenticates the **raw signed registry envelope** under that keyring and checks the lock's `registry_payload_sha256` against the verified registry. Only independently approved **root signer IDs** may sign the lock; root quorum is enforced, and forged, extra, undelegated, reused, or malformed signatures fail closed. The registry itself uses its existing signed format and distinct signature context. The dependency lock adds no module self-authorizing privilege.

The signed payload requires exactly `record_type`, `schema_version=1`, `revision`, UTC `issued_at` and `expires_at`, `registry_payload_sha256`, current `python_minor`, current `platform`, explicit `roots`, and the **entire** approved wheel list of exact filenames and lowercase SHA-256 digests. Parsing rejects duplicate JSON fields, unsupported versions, unbounded structures, repeated normalized distribution identities, malformed hashes/paths, wrong platform/interpreter, and expired or not-yet-issued documents. Checkpoints, if supplied from an independently continuous store, reject revision downgrade and same-revision equivocation.

`verify_signed_locked_wheelhouse` next calls the Slice 6 inspector with **only pins recovered from the signed bytes**. That gate checks the complete reachable dependency closure, physical wheel hashes, Python/platform tags, metadata, environment markers, and no extra or missing files. Untrusted user-supplied `WheelPin` objects, arbitrary package-index downloads, and unreferenced wheels cannot add installation authority.

### Root delegation and publisher distinction

For this initial contract the **approved root quorum signs a whole wheelhouse lock**, including all third-party dependency hashes. This is stronger than trusting a user-supplied hash list, but a root signature still does **not** substitute for each PDS module publisher's separately delegated signature under Slice 3. A production update must cross-check matching PDS wheels against current **publisher-signed release documents**, including revocation status. Do not use a root wheelhouse lock to bypass module release provenance or infer an integration attestation.

The lock is bound to the exact current verified registry payload, so intentionally changing registry revisions/content requires a new corresponding signed lock. This is an operational choice with an explicit publication cost; a future formally delegated independent lock-signing role may replace root-signing after an independently authorized contract migration.

## Prepared, NOT installed composition records

`evergreen_install_records.prepare_composition_record` takes **raw signed registry and lock envelopes**, the independently approved keyring, current time, exact wheelhouse directory, and one lowercase 32-hex transaction identifier. It re-verifies signatures and inspected bytes, then returns a data-only `UnverifiedPreparedRecord`. The canonical JSON schema is:

- `record_type=pds_evergreen_prepared_composition`, `schema_version=1`, `phase=prepared_not_installed`;
- transaction ID and timezone-explicit `prepared_at`;
- current Python minor and platform;
- exact trust fingerprint, registry payload digest, lock digest and revision;
- root distributions, exact package identity/version/wheel hash entries, and dependency edges.

`parse_unverified_prepared_record` enforces strict bounded canonical JSON with no unknown/duplicate fields and **cannot convert** a record to an installed receipt. `verify_prepared_record_against_wheelhouse` re-verifies original signing envelopes and current wheel bytes and matches *all* recorded metadata again. A changed wheel/lock/trust context or changed claim fails closed. Receipt serialization is **not cryptographic signing**; anyone who can edit the file can forge a candidate record. Transaction identifiers and the preparation timestamp are not independent trust anchors.

A candidate record **does not demonstrate** that any wheel was installed or that a Python environment remains intact. It is forbidden to use `UnverifiedPreparedRecord` or `VerifiedLockedWheelhouse` to set `LaunchPreflight.release_trust=TRUSTED`, report `installation_healthy`, run packages, or claim an active composition.

## Operational guarantees and remaining gates

No side effects: both modules are read-only and never call pip, create directories, write receipts, launch code, import wheel contents, touch teacher/classroom files, or contact GitHub. The bundle contains no production or synthetic private key outside test source. The bundled historical compatibility manifest remains unmodified.

Outstanding before enabling evergreen launch:

1. Production-owned/pinned root public keys, independent publication governance and trust continuity/recovery.
2. A durable approved metadata/lock checkpoint not wholly replaceable with the catalog cache; current local checkpoint objects alone do not prevent full-cache replay or machine compromise.
3. Cross-check each PDS module wheel against its signed *module release* authorization and revocations; don't rely on root wheelhouse lock alone.
4. Private staged environment: immutable exact wheelhouse, offline installation with no indexes/builds, installed `RECORD` verification and dependency checks, safe owned launchers, post-install smoke tests.
5. Protected **active** installed-composition receipt and recoverable atomic activation/rollback with explicit failure states; Windows junction/reparse hardening, teacher-visible diagnostics and eventual update planning.
6. Clear distinction between independently launchable modules and per-feature exact/contract integration qualification.

The verifier checks the active interpreter and platform, not an arbitrary claimed future target. Offline already-verified installations must remain usable based on independent installation provenance even when new catalog metadata is not fresh; the signed lock cannot by itself establish that provenance. Tests use deterministic **synthetic** signing keys only.
