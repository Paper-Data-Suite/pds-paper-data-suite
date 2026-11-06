# Issue #49 — Slice 6: Closed, hash-pinned offline wheelhouse inspection

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

**Status:** Isolated read-only inspection; **no production installation or launcher changes**.

## Problem and scope

Signing a PDS module release does not authenticate its transitive dependency
wheels. A package installer can run code from dependencies that did not come
from the PDS publisher. Before future update activation, the complete set of
wheels for the intended interpreter and platform must be known, individually
hash-bound, and checked against declared dependencies. No unreviewed resolver
fallback or additional index download may be permitted.

`paper_data_suite.evergreen_wheelhouse.inspect_closed_wheelhouse` supplies one
read-only gate for that pipeline. Inputs are a directory, exact wheel filenames
and lowercase SHA-256 hashes, and explicitly selected root distributions.
Output is a `WheelhouseInspection` containing the observed wheel identities and
active dependency edges. It is **not** a cryptographic signing authority, a
managed-install receipt, a certificate, or launch authorization.

## Checks

- Reject absent/extra files, duplicate wheel pins, duplicate normalized
  distributions, link/reparse-point wheelhouse targets, bad filenames, hash
  mismatches, and wheels incompatible with the **current** Python/platform.
- Read exact `METADATA` and `WHEEL` from one `.dist-info` directory and require
  `RECORD`. Compare distribution and version to the wheel filename. Check
  `Requires-Python`, declared wheel tags, and PEP 508 dependencies.
- Require each active dependency to resolve to an exact pinned wheel whose
  version satisfies its specifier. Evaluate environment markers for the current
  process and resolve requested dependency extras using `Provides-Extra`.
  Cycles are bounded by visited `(distribution, extra)` states.
- Reject undeclared extras, direct-URL requirements, dependencies absent from
  the lock, and unrelated pinned wheels not reachable from the requested roots.
- Bound wheel count, file size, archive member count, metadata reads, and
  uncompressed member sizes. Reject unsafe paths, duplicates, and ZIP symlinks.
- Read each wheel from the same opened file for hashing and metadata parsing,
  with a second hash to detect ordinary replacement during inspection.

This code never runs `pip`, imports a wheel, extracts archive files, fetches
online metadata, modifies the classroom workspace, reads student data, records
an installation, or alters Suite launcher eligibility.

## Critical trust boundary

**A SHA-256 pin supplied by an arbitrary caller is not an authenticated pin.**
An attacker can replace *both* the wheel and the expected digest. Callers MUST
verify an independently authorized, complete dependency-lock manifest before
using these observations as an installation gate. Existing Slice 5 PDS release
claims authenticate named PDS wheel digests; third-party dependency wheels
still require their own approved lock authority.

The future installer must recheck the complete wheelhouse, use offline
`--no-index` installation from exact locked artifacts, verify installed
metadata and import/launcher ownership in the staged environment, and record
its evidence in a protected, recoverable managed-composition receipt. An
arbitrary caller-constructed `WheelhouseInspection` or `WheelPin` is not proof
of these properties. Existing standalone and historical Suite launch behavior
remains unchanged by this slice.

## Additional limitations

The inspection targets the current machine's interpreter and environment
markers; cross-platform planning requires an explicit, separately qualified
target-environment protocol. Filesystem checks are best effort, not complete
protection against hostile concurrent same-user filesystem mutation or every
Windows junction ancestor. The approved staging directory must be controlled
by the later installer. `pip` may build or use external packages if invoked
without strict offline constraints; this slice does not invoke it.

The next boundaries are a **signed complete wheelhouse lock**, active-install
composition records, staging/rollback, and finally production launch wiring.
