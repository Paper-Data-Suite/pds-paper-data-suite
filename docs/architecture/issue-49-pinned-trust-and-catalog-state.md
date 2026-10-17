# Issue #49: Digest-pinned trust policy and verified catalog cache (Slice 4)

**Status:** Implemented as isolated infrastructure; **not** connected to production launch, package installs, doctor, updates, or Core workspace selection.
**Base commit:** `e7157e1` on `49-evergreen-launch-and-supported-composition-upgrades`.

## Policy provisioning is not self-trust

`evergreen_trust_provisioning.load_digest_pinned_trust_policy` accepts a bounded strict JSON policy with `record_type=pds_evergreen_pinned_keyring`, `schema_version=1`, positive `revision`, public Ed25519 keys (raw 32-byte canonical base64), disjoint root-key identities and a root signature threshold. The independent `pinned_sha256` is checked against the **exact input bytes before parsing**. It returns the Slice 3 `TrustedKeyring` only if the independent pin and the complete typed keyring contract validate.

**The pin must originate from separately reviewed, trusted Suite release/deployment code or another independently authenticated policy authority.** Do not compute the pin from the downloaded policy, accept it from a CLI option, borrow it from GitHub, or let an untrusted catalog choose it. The test suite computes pins from synthetic fixtures to test the code; that is never acceptable for a production trust anchor.

No production root keys, private keys, or production policy digest have been provisioned by this slice. Private signing material must never be distributed in Suite artifacts.

This initial policy is *digest pinned*, not a signed root-rotation implementation. Ordinary future **releases under already pinned delegated keys** require no Suite wheel update; onboarding *new signing keys* or rotating compromised root keys requires a subsequent, independently authenticated update or trusted policy transition. Until that protocol is implemented, reject unknown replacement keys rather than silently trusting them.

## Signed catalog cache and local history

`evergreen_catalog_state.save_catalog_cache` validates real Ed25519 registry, module and integration envelopes under an independently supplied `TrustedKeyring`. It compares every identity-specific revision/digest with the last cryptographically reverified local state, then writes a bounded versioned JSON snapshot through a same-directory temporary file and atomic replace. Module and feature history cannot disappear silently in a routine update. A lockfile serializes cooperating update writers; interrupted or conflicting updates leave the previous valid cache untouched. `load_catalog_cache` always re-verifies signatures, delegation, signed windows and the trust fingerprint at the supplied aware clock time. It returns signed catalog **claims**, not executable permissions.

The cache stores only release-signing envelopes, keyring fingerprints, and update acceptance time. No roster, workspace, scan, score, behavior, or personally identifying classroom data is stored or inspected. The caller must select an approved Suite-local metadata directory **outside the classroom workspace**, create it separately, and ensure suitable user/OS permissions. The path checker rejects obvious symlinked directory components and symlinked target files; complete Windows reparse-point hardening and protected local deployment state remain mandatory before enabling production writes.

### Anti-rollback limitations

Within an intact cooperating local cache, lower signed revisions, equivocation at the same revision, duplicate identities, unexpected dropped documents, and obvious local clock regressions are rejected. Historical signed documents are reverified inside an overlapping signed validity window before their revision checkpoints are used, even if they have since expired. Current metadata authorization still requires current signed validity; historical re-verification does not grant freshness.

**This file is not a tamper-resistant monotonic counter.** A user, malware, or backup restore with permission to replace the *entire cache and its history* can defeat local rollback bookkeeping. Filesystem atomicity and a signature cannot solve that rollback problem. Before claiming deployment-grade rollback resistance, implement stronger trusted continuity (for example, an authenticated transparency checkpoint, separately protected local anchor, or equivalent carefully qualified design), root transition/rotation and recovery procedures. Offline devices cannot detect unpublished revocations in real time. The signed cache must never be treated as proof that installed wheel bytes are genuine.

Expired online metadata must not destroy an already independently verified *installed* application or block normal offline teacher workflows; that later policy depends on a verified managed-installation receipt. The cached signed metadata alone never produces `LaunchPreflight(release_trust=TRUSTED)`.

## Future work and required authority boundaries

1. Establish actual production root-key ownership, publication governance, independent pins, and safe signer rotation/revocation, with synthetic signing keys strictly limited to tests.
2. Bind authenticated catalog claims to exact downloaded wheel hashes, real distribution metadata, transitive dependencies and installed-artifact receipts.
3. Address approved cache directory, Windows junction/reparse safety, durable rollback anchors, corruption recovery and offline freshness semantics.
4. Wire independent launch eligibility and integration qualification only after those trust and installation checks pass.

This slice adds no network request, no package install, no source checkout execution, no changed `pds launch` behavior, no workspace writes, and no synthetic trust key inside the published Suite wheel.
