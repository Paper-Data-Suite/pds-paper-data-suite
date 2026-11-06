# Issue #49 — Slice 24: Publisher-bound real-pip candidate preflight

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** Slice 23 commit `c70f798` (full hash verified by runner)
**Scope:** Read-only, opt-in candidate inspection. No production wiring.

## Problem

Slice 20 proves delegated PDS publisher authorization before running the
synthetic staged-console acceptance probe. Slice 23 verifies real offline-pip
installation layouts, including wheel-origin `direct_url.json`, installed
`RECORD` entries, and generated Windows/POSIX console wrappers. Neither proof
on its own joins **publisher authorization** to **the bytes actually installed
by pip**. A signed *dependency lock* alone cannot stand in for PDS publisher
release authority.

## New composition-level gate

`evergreen_publisher_pip_preflight.audit_publisher_bound_pip_candidate()`:

1. Reauthenticates every registered PDS wheel in the closed dependency lock
   against the separately registered publisher signing delegation. This
   includes registered transitive PDS dependencies, not only requested roots.
2. Uses Slice 21–23's strict pip installation audit with
   `require_launcher_records=True`. Wheel payloads, relocations, PEP 610 local
   origin, installer metadata, installed `RECORD`, and owned console-launcher
   bytes must all reconcile to the exact authenticated wheelhouse.
3. Reinspects the staged virtualenv's console targets and requires every
   requested root application's name, owner, and callable target to match the
   authenticated publisher release claim. Every observed console wrapper must
   have an exact owned installed-`RECORD` entry.
4. Reauthenticates publisher metadata after the disk inspection and rejects
   disagreement with the earlier observation.
5. Returns an immutable, non-authorizing observation of the exact inventory
   hash, publisher payload digests, root console identities, and external
   distributions that have only root-lock (not delegated PDS) authorization.

The preflight does not execute or import staged code, download wheels, install
anything, create an active receipt, or access the PDS classroom workspace. It
must not be exposed as a boolean `can_launch` decision. Unknown dependencies
such as external Core wheels are not silently promoted to signed PDS module
releases; they remain separately identified for future provenance decisions.

## Security and incompleteness

This is a point-in-time file observation, not an operating-system sandbox or
continuous integrity guarantee. The prior native-executable evidence gate and
publisher-root signing process remain separate requirements. This slice does
not prove Python executable provenance, interpreter safety, teacher approval,
Core API compatibility, prior active-state history, or the absence of a
concurrent same-user replacement attack. It is **not** a protected installed
receipt and must not make the Slice 12 candidate-selection pointer trusted.

The next integration layer can invoke this preflight from a journal-bound,
explicit candidate acceptance transaction before permitting any isolated
public import probes, then recheck it after the probes. Real released PDS
artifacts and Windows ARM64/x64 must be qualified before activation.
