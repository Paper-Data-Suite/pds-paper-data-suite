# Issue #49 — Slice 26: Scoped signed exact-integration evidence

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** Slice 25 commit `147fde3` (full SHA guarded by runner)
**Scope:** One additive, read-only feature-evidence adapter; no launcher wiring.

## Why a separate capability decision is required

Slices 19–25 independently establish delegated PDS publisher identities, a
real-pip installed-file audit, signed native executable hashes, and the exact
journal-bound *candidate* identity. Those facts cannot prove that two modules
have passed a named cross-module integration test. Conversely, an unqualified
cross-module feature must not disable an otherwise sound individual launcher.

`inspect_journal_exact_integration` calls the existing fully authenticated
journal-bound preflight from raw inputs. It additionally verifies an integration
attestation signed by the **separately delegated integration authority** in the
root-verified registry. It binds the signed artifact claims to exact SHA-256
wheel identities already required in the publisher-authenticated prepared
composition. The requested feature ID and exact required participant set must
match, as must signed Python minor and platform coverage.

The operation exposes these distinct *evidence* outcomes:

- `exact_attested`: the independently signed exact participant set reports
  `passed` for this feature, interpreter minor, and platform.
- `unqualified`: no signed integration attestation was supplied or the supplied
  valid attestation is not applicable to this exact feature/composition.
- `attested_failure`: an applicable independently signed attestation reports
  `failed` for this named feature; unrelated module launch status is unchanged.

A missing signed integration document is not an authenticity failure of the
underlying publisher-verified installation. An invalid integration signature,
unknown delegation, stale/replayed attestation, malformed scope, or unauthentic
candidate **does** cause fail-closed verification error.

## Required scope and Core limitation

The caller supplies a stable feature contract comprising a feature ID and the
*complete required component-ID set*. The signed integration attestation must
bind exactly that set; partial and extra participants do not inherit
qualification. No feature target is executed from a claim. The operation never
imports module code, launches Python, runs pip, downloads, or writes any file.

**All attested component IDs must be independently registered and publisher-
authorized PDS wheels.** Dependencies that currently appear only as root-signed
external distribution pins — including a Core release not yet delegated its
own component identity — cannot be silently treated as integration-qualified.
This is deliberate: Core's public routing/operations contracts need explicit
registered release provenance and subsequently concrete provider probes.

## Security and operational limits

- Both the registry and integration documents are verified from signed bytes;
  caller-provided key material is not accepted as an authority.
- The signed integration `evidence_sha256` authenticates an authority's *claim*
  about test evidence. It does not retrieve or independently reproduce tests.
- Signed wheel hashes are compared against the reauthenticated journal-bound
  candidate's publisher-backed exact wheel pins, never guessed from names.
- The journal and candidate stage remain same-user mutable. Duplicate local
  re-verification does not provide protected active-installation continuity,
  resistant-to-hostile-concurrency file handles, or a persistent launch receipt.
- A signed positive result is `EXACT_ATTESTED` **evidence**, not operational
  permission. This adapter exposes no `can_launch`, `activate`, or global
  `compatible` property. Absence of broad Suite qualification never becomes a
  global block on individual module launch.
- Production integration authority publication, actual PDS Core release
  provenance, feature-specific smoke probes, protected checkpoints, and
  live status/doctor/update wiring remain subsequent release gates.

This slice is intentionally additive and keeps the teacher workspace, active
installation, current `pds launch`, and historical v0.1.0 compatibility manifest
unchanged.
