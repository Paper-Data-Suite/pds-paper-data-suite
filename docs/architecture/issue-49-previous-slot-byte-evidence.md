# Issue #49 — Slice 13: Authenticated previous-slot byte observations

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base commit:** `14ca000` (exact full SHA guarded by the Windows runner)
**Status:** Read-only software verification infrastructure. Not a production active-installation receipt.

## Why this boundary exists

Slice 12's `candidate-selection.json` is intentionally user-editable and explicitly **not** an authoritative active-installation record. Merely finding an existing directory, or trusting a JSON pointer and an associated SHA-256, cannot establish that the previous software installation is genuine, ever ran, or can be safely restored.

`evergreen_previous_install` adds a **read-only previous-software-byte recheck** rather than self-certifying an active receipt. It reads the existing validated candidate-selection pointer only when no recovery marker is pending, verifies both stage and wheelhouse are ordinary descendants of the approved Suite-local software root, and compares the pointer's transaction and input-envelope hashes. It then calls Slice 10's full signed native-evidence verification. That path rechecks the staged virtualenv, wheelhouse, dependency lock, signed registry, installed metadata, console wrappers and native executable hashes with an independently provisioned `TrustedKeyring`.

A successful observation binds exact transaction, stage and wheelhouse references, generation, signed-envelope digests, prepared record, signed native payload digest and native revision. A strict, canonical, bounded JSON observation record may be serialized without writing it to disk. Verification of an existing record **repeats the underlying signed artifact checks** instead of trusting its fields. An optional expected-record digest can be compared with the exact bytes, but it provides continuity only when anchored outside user-replaceable metadata.

## Explicit non-authority and offline behavior

`PreviousSlotObservation`, `VerifiedPreviousSlotBytes`, and the serialized record do **not** represent proof of historical activation, trusted prior installation, acceptance testing, update success, recoverable physical state or permission to launch. There is no `can_launch` or equivalent property. Neither local record bytes nor their SHA-256 are cryptographic authorities. A user able to replace both the pointer and the saved record can change recorded history; current signed source evidence only proves the bytes being checked.

This gate requires **fresh** signatures for its repeated verification. An expired online catalog must not itself disable an independently verified installed offline classroom app, so this API is **not** a production offline launch preflight. That requires a protected, durable installed-state proof and a separate offline revocation/freshness model. Missing/expired provenance fails this candidate check closed rather than disguising failure as success.

No production signing keys are included. Tests use deterministic synthetic root and publisher keys, not teacher data. The implementation does not install packages, run pip, launch Python from the stage, mutate previous or candidate physical software, write a receipt, access classroom documents, or change the normal `pds launch` implementation.

## Follow-on work

1. Connect trusted previous-slot evidence to Slice 11's `expected_previous_receipt_sha256` and Slice 12's selection transition with explicit rejection when protected continuity is unavailable; do not use a caller-supplied hash as authority.
2. Build installed-state lifecycle with distinct prepared, accepted, activated, recovering, and recovered outcomes. Verify candidate acceptance and preserve a real previous installed state before enabling the pointer to select production launchers.
3. Design a protected, monotonic receipt/continuity authority and offline validation, together with practical reproducible native launcher/interpreter provenance and genuine staged-pip acceptance. No unreviewed signing of local teacher binaries.
4. Add real update planning, teacher approval, per-module launch and per-feature integration status without touching the Core classroom workspace.
