# Issue #49 — Slice 5: Root-key transition and exact signed wheel verification

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

**Status:** Additive isolated infrastructure. Does not change the launcher, teacher updates, installed receipts, Core workspace, or published Suite release authority.

## Root-key transition without reissuing the Suite wheel

`evergreen_trust_rotation.verify_trust_transition` accepts **only** a previously independently pinned `PinnedTrustPolicy` and a bounded JSON transition containing the **exact next policy bytes** in canonical base64. The signed message is:

```text
b"pds-evergreen-policy-transition-v1\x00" +
old_policy_sha256_ascii + b"\x00" + exact_new_policy_bytes
```

Its result is an *authorized transition candidate*, not an activated trust policy. It verifies the prior root signature threshold using the previous policy's keyring, then independently verifies the new root signature threshold using the candidate new policy's public keys. The new policy must pass the existing strict parser and have a strictly higher policy revision. Every signature is Ed25519 over **the same domain-separated transition message**; extra or undelegated signers, invalid signatures, duplicates, unknown fields, and malformed base64 fail closed.

Old-root signatures are essential: a new key cannot self-authorize its own onboarding. New-root signatures prove the next quorum controls the keys before activation. If the old root quorum is lost or compromised, recovery needs a separately reviewed out-of-band trusted distribution—not arbitrary catalog metadata. Private keys are never generated, stored or embedded in runtime artifacts by this implementation.

The caller must independently establish the authenticity of the **previous** pin and the continuity of policy revision. This slice deliberately has **no local trust-policy installation or cache mutation**, no durable rollback anchor, no recovery protocol, and no network publication. A locally replaceable file cannot provide robust anti-rollback by itself. Production activation must bind root transitions to the protected installation state, preserve the transition chain and reverify catalog signatures under the newly active keyring.

## Exact release artifact verification

`evergreen_release_artifacts.verify_signed_release_wheel` accepts the **raw signed registry and module release envelopes** plus an independently trusted keyring and validation time. Unlike a caller-supplied `Verified*` dataclass, raw envelopes are reauthenticated on this call, enforcing the root quorum and module-specific publisher delegation.

An accepted selected release must be stable, present in signed publisher claims and not marked revoked. The local wheel must match the signed **exact filename and SHA-256**. Before interpreting executable wheel metadata, the verifier checks bounded size, ZIP path-safety, unique member names, a single correct `dist-info` identity, mandatory `METADATA`, `WHEEL` and `RECORD`, correct Python `Name`, `Version`, exact `Requires-Python`, exact `Requires-Dist`, and a unique expected console script target. Dependencies must also parse as valid packaging requirements. Metadata reads are bounded; the file is hashed and parsed through **the same open file descriptor**, then rehashed to detect modification during inspection. No code from the wheel is imported, extracted or executed.

`VerifiedReleaseWheel` asserts only that one local wheel matched live authenticated signed claims and internal metadata. It **does not** establish a trusted installed distribution/launcher, runtime Python compatibility, a transitive-dependency lock, cross-module interoperability, or an installed environment receipt. The publisher's signed version is not a broad integration attestation. The previously authenticated catalog's **monotonic rollback checkpoint** is enforced by the separate Slice 4 cache implementation; this standalone inspection routine alone does not preserve history.

Wheel paths are not extracted, and an attacker with concurrent filesystem write access still requires stronger staged-file ownership and no-reparse guards before installation. Full Windows junction/reparse safety, immutable staging, OS-protected transition state, transitive artifact provenance, installed distribution RECORD checks, and transactional update activation are later milestones. A valid signed wheel must not be used for production launch until those gates are satisfied.

## Dependency policy

`packaging>=24,<27` becomes an ordinary runtime dependency: `parse_wheel_filename`, `canonicalize_name` and `Requirement` are necessary for secure wheel identity and dependency parsing. The `cryptography>=45,<47` dependency from Slice 3 remains unchanged.

## Tests and acceptance

Synthetic Ed25519 fixtures verify old/new root quorums, role separation, previous-anchor binding, corrupted policy bytes, policy revision advance, signature replay rejection, and the exact binary wheel metadata path. Tampered official-looking wheel bytes, invalid release signatures, unauthorized publishers, wrong package versions, malformed metadata, script substitution, malicious ZIP member names and explicit revocation are rejected. Synthetic keys are test-only and not deployable publisher keys.

All existing v0.1.0 Suite launch/doctor/bootstrap semantics are unchanged in this slice. No production publisher keys or official release attestations are invented. Future milestones must specify how real publishers sign assets, distribute trust metadata, and protect the installed active composition before ever enabling an evergreen production launch.
