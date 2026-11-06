# Issue #49 — Slice 58: explicit offline, authenticated release-catalog preview

## Decision and scope

Keep the historical `pds modules` output unchanged by default. Add an **opt-in diagnostic** invocation:

```text
pds modules --catalog-cache PATH --trust-policy PATH --trust-sha256 HEX64
```

The new path never silently falls back to the bundled v0.1.0 version-qualified inventory if validation fails. Missing any one of the three options is an error. The preview performs no network access, package execution, installation, update, launch, workspace access or receipt mutation.

`--trust-sha256` MUST originate from an independently trusted distribution/administrator channel; supplying a value on the command line is **not itself evidence of independent authority**. The trust-policy bytes must match that digest. The policy's Ed25519 root/delegated signer keys are then used to reauthenticate the signed cached registry, module-release documents and integration documents *at the current UTC time*. All existing catalog signature, expiry, registry-delegation, revocation-field and replay-checkpoint rules remain in the existing verifiers. The cache itself remains a locally replaceable store, not a protected monotonic checkpoint.

## Teacher presentation

The output distinguishes:

- **Registered module and delegated signing identity** (signed metadata only).
- **Exact claimed wheel version and SHA-256**, with revoked records clearly identified.
- **Signed integration-result claims**, explicitly not installed-wheel or capability qualification.
- **Installed integrity, actual launch eligibility, update readiness, and exact integration status: NOT ASSESSED**.

This is deliberately not a substitute for a signed active installation receipt, service-independent witness continuity, fresh installed-wheel inspection, OS-protected activation or a safe launch switch. None of the newly authenticated releases automatically becomes available to `pds launch` from this command. A separate slice must bridge genuinely verified installed-state evidence into launch and doctor; that bridge must not reuse the bundled exact manifest as a requirement for independent launch eligibility.

## Safety notes

The new preview validates and bounds path reads, excludes symlinks/Windows reparse points, performs current-time cryptographic revalidation of cached envelopes and reports generic failure if authentication fails. A malicious local actor capable of changing either the cache and command-line trust anchor may still supply a mutually matching pair: user-supplied pins do not solve independent provisioning. The existing `pds modules` and `pds launch` defaults, workspace ownership and classroom data remain unchanged. This diagnostic cannot assert that any wheel is installed or that any launch should be permitted.

## Next work

Deploy an administrator-pinned trust root that users cannot silently override, plus an independently witnessed installed-state receipt and currently verified physical bytes. Only after those prerequisites should `pds modules` and `pds launch` adopt forward-compatible production eligibility. Integration qualification continues to require independent exact artifact fingerprints, never just signed version labels.
