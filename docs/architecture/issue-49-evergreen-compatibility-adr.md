# ADR: Issue #49 — Evergreen Launching Without False Integration Qualification

**Status:** Accepted for implementation planning (Slice 1); no production launch change yet
**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Date:** October 17, 2026
**Scope:** Suite software lifecycle and compatibility authority, not classroom data

## Context and failure reproduced by existing source

The v0.1.0 bundled `release_compatibility_v1.json` binds exact package versions,
public entry points, and SHA-256 values. In `applications._observation`, the
installed-version inequality short-circuits before public launcher checking;
Suite and Core also must exactly match the historical bundle. Thus Quillan
0.10.0 was unusable through the v0.1.0 Suite launcher despite being usable
through its own installed console command. The v0.1.0 assertions are historical
and **must not** be rewritten to imply that later modules shipped with v0.1.0.

**Decision:** Retain the exact historical release manifest and introduce a
separate authenticated active-installation composition. Independently verified
module launch and separately scoped integration qualification become different
observations. Future module releases do not require a new Suite wheel, yet
unknown release identities never become trusted by having a higher version.

## Authority and compatibility dimensions

| Dimension | Authority | Can advance independently? |
| --- | --- | --- |
| Historical Suite baseline | Immutable Suite release wheel/manifest | No, by definition |
| Trusted release identity | Signed approved release metadata + verified wheel | Yes |
| Installed composition | Locally verified managed install receipt | Yes, after transaction |
| Launch eligibility | Suite policy over trusted install/runtime observations | Yes |
| Public capability eligibility | Actual relevant Core/module contracts | Yes, per capability |
| Exact integration qualification | Signed, artifact-scoped test attestation | Yes |

A module is **launchable** if an independently authorized installed artifact has
matching local receipt/provenance, a safe owned console entry point, a compatible
interpreter/dependency graph, and a healthy update state. None of those checks
requires equality with the historical Suite wheel's module version.

An **integration** is permitted only when the named feature's declared policy
has evidence: either an exact test attestation for features requiring one, or
verified compatible public contracts for features designed to be
contract-compatible. The module launcher itself may remain usable if this
integration fails or is unqualified.

**No boolean `compatible` shall collapse these dimensions.** Preserve clear
states: unavailable/not installed, independently eligible, exact qualified,
contract supported, unqualified, blocked, and unknown. The source of every
assertion must be distinct and auditable.

## Initial pure policy (Slice 1)

`paper_data_suite.evergreen_policy` provides deterministic types and decisions:

- `LaunchPreflight`: validated **trusted-adapter observations** only; it neither
  discovers nor authenticates releases.
- `assess_launch`: returns available, not installed, or blocked, with stable
  reason codes; it has **no historical Suite or module version input**.
- `assess_integration`: returns exact, contract-supported, unqualified, or
  unavailable outcomes for **one named feature**; requiring exact qualification
  never degrades to approximate-version acceptance.

This module is **not wired into** `pds launch`, `pds modules`, `pds doctor`,
bootstrap, or package updating. Existing behavior remains intact in Slice 1.
Future adapters MUST authenticate and verify observations before creating
`LaunchPreflight`; constructing all-true inputs from arbitrary module metadata
would be a vulnerability. A pure policy result is not a signed attestation.

## Trust design decision

Choose a reviewed, versioned signed-metadata design with TUF-like separation of
root authority, approved module-delegated release targets, snapshot/version
anti-rollback, freshness policy, and signed integration attestations. The
implementation must select a reviewed concrete scheme and document its precise
verification rules before production network/catalog code is connected.
**Do not implement home-grown signature verification.** Initial trusted root
keys/policy may be embedded in a Suite wheel; independent signed, delegated
metadata may be updated without rebuilding that wheel.

A trusted module release binds:

1. Fixed component ID, authorized publisher/repository and distribution name.
2. Stable version/tag, official wheel filename, digest and supported platform.
3. Approved public launcher name/target and optional public entry points.
4. Signed issuance, expiration, monotonic sequence, key delegation and
   revocation/supersession state.
5. Actual wheel metadata, including `Requires-Python`, `Requires-Dist`, and
   entry-point ownership, checked against authorized claims.

The **publisher signature authorizes the release artifact**, not its correctness
in every workflow. A separately signed exact integration attestation identifies
tested wheel digests, feature scope, environment, and results.

**Transitive wheels are executable too.** An updater must authenticate its full
installation closure (for example a verified hash-locked wheelhouse), not only
PDS modules, before running installation/imports. Do not allow untrusted
resolver downloads, mutable branch heads, development builds, or accidental
package-index substitution.

### Offline and revocation trade-off

Previously verified, locally healthy modules should remain launchable while
GitHub is unreachable. Unknown or unverified new versions cannot be approved
offline. Catalog expiration/revocation freshness is a separately reported
observation: merely being offline does not retroactively falsify a locally
established authorized release. Explicit locally known revocation **does**
block launch. Define an incident response for compromised keys/releases and
stale metadata that avoids silently enabling newly disallowed installs.

Anti-rollback requires trusted, monotonic local metadata state; a cached signed
snapshot alone is insufficient. A fully compromised or restored local machine
may require out-of-band recovery/reconciliation. No remote revocation can be
known instantly while disconnected.

## Threat model and non-goals

Potential attackers/control surfaces: forged GitHub asset or catalog; compromised
mirror; malicious extra package; wrong wheel with same name/version; false
provider owner; duplicated/shadowed console script; hostile `PATH`/
`PYTHONPATH`; stale/rollback release index; compromised publisher key;
interrupted installer; manipulated local receipt; Windows symlink/junction/path
escape; manual pip drift and mixed Core versions.

Required countermeasures: pinned initial root trust; signed delegated identities;
exact wheel digests; normalized ownership; dependency-closure authentication;
`pip check`; current-environment launcher confinement; no shell interpolation;
read-only preflight; staged installed-wheel testing; atomic activation; verified
receipt/recovery; rejection of unknown or newly revoked artifacts.

A local receipt is **not proof of artifact identity by itself**. It must be
associated with verified wheel/install evidence and protected/checked against
package drift; limitations of same-user filesystem tampering must be documented.
No installation mutates the Core-selected workspace or module-owned records.

Neither module-origin `ModuleOwnerActionRef` nor a self-asserted version range
constitutes executable authorization. A module can have an eligible launcher
while a routing, publication, Meridian-consumption or Vitrine feature remains
unqualified or unavailable. No integration is silently promoted.

## Migration and component discovery

The v0.1.0 manifest and CI tests remain immutable historical baselines.
Installations enrolled into the new managed channel receive a separate
versioned active-composition receipt after artifact verification. If a legacy
installation cannot be independently verified, enrollment is blocked pending
repair rather than self-attested.

An approved registry may later add Meridian, Portia or a new explicitly
recognized Suite application without a Suite wheel release. Mere membership in
the GitHub organization is **not** sufficient (e.g. Clavis is not automatically
a classroom Suite application). Module-operations presence, routing,
publication, and console launching remain distinct capability families.

## Update workflow and recoverability

`pds updates check` authenticates metadata without installation. `pds update
--plan`, `pds update <module>`, and guided `pds update` plan the exact targeted
and dependency-closure changes with ADD/UPGRADE/DOWNGRADE/REMOVE/UNCHANGED and
feature-qualification effects. No background upgrades. A managed update is
review-before-write, artifact-authenticated, staged, dependency/launcher-tested,
activated recoverably, then recorded atomically.

Use one ordinary active teacher-facing Suite environment. Private candidate
staging does not impose multiple manually maintained environments. If any
transaction step fails, restore the prior working software/receipt, report
recovery-required status, and never claim an unverified mixed composition is
healthy. Preserve exact workspace bytes; software installation does not perform
module domain-data migration.

## Dependency ordering and gates

1. Slice 1: this ADR, threat model, pure independent policy, focused tests.
2. Signed catalog/attestation contract and a **real reviewed verifier** with
   synthetic signed fixtures and anti-rollback/expiry/revocation tests.
3. Active-composition receipt and migration, first in pure/test-only storage.
4. Wire launch observations to validated authenticated release + receipt;
   preserve legacy path until the new path is trustworthy.
5. Capability-specific integration qualification, independent of launching.
6. Read-only check/plan, per-module dependency-closure update planning.
7. Staged apply/recovery, bootstrap and doctor reconciliation.
8. Exact installed wheels and physical Windows acceptance; release freeze.

Core v0.6.6 and current official module releases form an initial *candidate*
integration matrix; release tags and wheel digests must be refreshed and checked
at freeze. In-progress Concord/Meridian/Portia work must not block the pure
launcher contract, but may affect later integration tests.

**Acceptance boundary for Slice 1:** the new policy and tests exist and pass;
all legacy Suite tests and behavior are intentionally unchanged; no trust key,
network catalog, launch relaxation, filesystem write or update command has been
introduced. The next slice must not use this model to launch new versions
without a real authenticated trust adapter.
