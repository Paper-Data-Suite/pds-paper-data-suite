# Issue #49 — Slice 19: Publisher-bound prepared composition

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `a1aecae544b549763a0897e14091d1bc0be9c4eb`
**Scope:** Additive, read-only release-provenance verification; no production wiring.

## Trust separation

An authenticated root-signed dependency lock can authorize a complete set of
installable wheel bytes, including external dependencies. It does **not**, by
itself, prove that a wheel presented as Quillan, Portia, or another PDS module
is an official stable release approved by that module's delegated publisher.
The `verify_publisher_bound_composition` adapter restores this separate trust
boundary before any root wheel can be considered publisher-authenticated.

Inputs are raw, independently authenticated **again during each call**:

- Root-signed registry, validated against the pinned keyring and optional
  registry continuity checkpoint.
- Root-signed, Python/platform-specific dependency lock, the exact closed
  wheelhouse, and the canonical prepared record, with optional lock checkpoint.
- One release envelope from the root-delegated publisher for **every registered
  PDS distribution in the selected wheelhouse**, including dependencies not
  explicitly listed as root applications.

Release envelopes are keyed by the registry's component IDs, not by wheel-supplied
package claims. A missing, duplicate, unknown, revoked, expired, or incorrectly
signed module release is rejected. Every signed release must describe exactly
the locked filename, distribution, version, SHA-256, dependency metadata,
console-script name and target. Wheel members are inspected by the existing
release-artifact verifier, including metadata/filename consistency.

**Every selected root application must be registered.** A root-signed
third-party dependency can remain an external locked wheel but does not become
a PDS application by being present in a wheelhouse. An external dependency
whose name resembles a PDS component does not receive release delegation
unless it is listed in the independently verified registry; root registration
and publisher metadata are the authority, not a package-name prefix.

## Returned observations and exclusions

The result lists publisher-authorized PDS wheel identities and external
root-lock-only dependency names. It is a snapshot of supplied local bytes, **not
an installation receipt, active-state proof, launch permission, import success,
or an integration attestation**. The function does not install, extract,
execute, import, contact GitHub, write installed state, or access the classroom
workspace. It intentionally does not yet authenticate the Python runtime,
generated executable templates, or the installed software file inventory. Those
boundaries remain covered by separate staged verification modules.

Same-user file replacement between inspections remains a system-level threat;
protection against it requires stronger installation ownership, concurrency
controls and protected active-state continuity. This slice does not establish
production publisher-key deployment; tests use synthetic signing keys.

## Next boundary

Combine this independent publisher evidence with candidate runtime/public
contract acceptance **before** accepting any activation transaction. Then
qualify real Windows pip installation layouts and platform-native launchers,
followed by protected installed receipts, controlled activation/rollback and
teacher-facing `pds update`, `pds modules`, `pds doctor`, and evergreen
`pds launch` integration.
