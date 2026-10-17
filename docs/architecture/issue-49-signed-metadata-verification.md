# Issue #49: Ed25519 signature and delegation verification (Slice 3)

**Status:** Implementation with focused synthetic-key acceptance, NOT a production trust rollout.
**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Parent contract:** `docs/architecture/issue-49-catalog-envelope-contract.md`

## Security boundary and scope

`paper_data_suite.evergreen_catalog_verification` verifies the **exact original
signed payload bytes** from Slice 2 envelopes with the audited `cryptography`
Ed25519 implementation. It does not serialize JSON for signature checking.
The module never retrieves keys from an envelope or untrusted release claims.

Three independent signed roles are enforced:

1. **Registry/root:** a caller-provisioned `TrustedKeyring` pins exact Ed25519
   public keys, root signer identities, and a threshold. A registry must meet
   that threshold. Unknown, undelegated, and invalid extra signatures fail.
2. **Module release:** the root-verified registry delegates specific key IDs to
   exactly one component ID, repository, and distribution. A module release must
   match all three identities and validate under that module's delegated key.
3. **Integration:** a separately delegated integration key signs exact-scoped
   integration claims. A module signer cannot substitute for this role.

Key roles must be disjoint: a root cannot also sign module releases; a module's
signer cannot be assigned to another module or to integration. Distinct key IDs
cannot alias identical public-key bytes. The verified registry carries a trust
policy fingerprint; a leaf verifier rejects a different keyring substituted
between root and delegated verification.

`TrustedKeyring` is a **trust injection point for later bootstrapping**, not a
way to discover trusted keys. Its keys must originate from a separately vetted,
protected, pinned or root-authorized publisher policy. Loading attacker keys
from the same downloaded envelope and using them in `TrustedKeyring` would
completely bypass the threat model. **Do not wire to production launch yet.**

## Time and replay rules

The caller supplies an explicitly timezone-aware UTC-comparable `now` value.
Issue and expiration times are signed; validity is `[issued_at, expires_at)`.
Expired/future documents cannot authorize *new* metadata evaluation.

`RevisionCheckpoint` can reject a lower signed revision and signed
**equivocation** (different payload digest at the same revision). Equal revision
with identical payload is idempotent. The checkpoint belongs to one unique
metadata identity: registry, module component, or integration feature. Callers
MUST store separate checkpoints for each and atomically persist the next
checkpoint with trusted cache state. This slice has **no persistent protected
anti-rollback store** and must not claim one.

A signature-verification freshness failure is NOT permission to delete a
previously authenticated local software installation. Future normal classroom
launch uses independently verified installed receipts and is offline-safe;
future online update acceptance evaluates current signed authorization.
Known locally confirmed revocations must eventually block production launches.

## Explicit non-authorities

Returning `VerifiedRegistryDocument`, `VerifiedModuleDocument`, or
`VerifiedIntegrationDocument` means **only** that the signed claims passed
cryptographic and role checks under the supplied keys, window, and checkpoint.
It does **not** assert that:

- the bytes of any official GitHub wheel were downloaded, verified, installed,
  or bound to a trusted managed-installation receipt;
- any transitive wheel was authenticated;
- a wheel's `METADATA`, `Requires-Dist`, or `entry_points.txt` matches the
  publisher's claims;
- the full integration participant set is installed, identical to the attested
  SHA-256 set, on a qualified platform/Python, or has passed a runtime check;
- a given version is launch-eligible, an integration is permitted, or an
  unchecked `LaunchPreflight(release_trust=TRUSTED)` may be constructed;
- signing keys are production-pinned, securely rotated, remotely revoked, or
  current against an offline-unseen publication event.

The implementation makes no network requests, reads no workspace, and does not
write a cache, install packages, import modules, or change existing Suite launch,
modules, doctor, compatibility, or bootstrap behavior.

## Remaining trust work before production activation

- Provision a **real** independent PDS root-of-trust and signed publication
  workflow. No synthetic test private key may enter a released artifact.
- Define root-authorized delegated public-key onboarding and root/key rotation.
  Slice 2 only lists delegation **key IDs**: the initial keyring is preprovisioned
  and does not yet let an unseen public key join without a trusted keyring
  update. This is a deliberate incomplete boundary, not evergreen enrollment.
- Store monotonic role/identity-specific revisions and current trusted catalog
  atomically with crash-safe rollback/equivocation detection; define its OS
  trust/tamper limitations.
- Bind authenticated release claims to exact official wheels, their metadata,
  transitive dependencies, and a verified installed receipt, then integrate
  read-only module inspection and launch policy.
- Define root/publisher compromise and revocation handling. Expiry alone is
  insufficient for revocation propagation or all offline cases.

The existing v0.1.0 historical release manifest and all its assertions remain
unchanged. Runtime package dependency `cryptography>=45,<47` is declared for
future installed use; this slice does not load cryptography from any existing
Suite command path.
