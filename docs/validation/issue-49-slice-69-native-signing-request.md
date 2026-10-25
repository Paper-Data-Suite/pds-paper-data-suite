# Issue #49 — Slice 69 validation record

**Feature:** Deterministic, unsigned, plan-bound candidate native signing request.

**Baseline required:** `e6bd878` on `49-evergreen-launch-and-supported-composition-upgrades`.

**Review scope:** Four additive files only: production source, regression tests, architecture, validation. No modifications to existing CLI, launch, `doctor`, or active-installation code. No default invocation of the native request builder.

## Automated checks

The focused Slice 69 tests use stand-ins for earlier signed-envelope and pip auditors and real disposable native-file bytes. They cover deterministic schema/hash and transaction bindings, absence of signature/authority, refusal of invalid trust/revision/clock/expiry/envelope, exact stage-path confinement, pip inventory and signed witness mismatches, native file absence or symlink, between-pass file mutation, and signed-wheel or pip verification failure. They do not demonstrate that a real authority signed an official interpreter or that production signing infrastructure exists.

- Local isolated tests: **21 passed**; isolated stand-ins are not substitutes for official signed-artifact acceptance.
- Full Windows gate (pending): Ruff import-order/format/lint; strict mypy on the new production module; complete Issue #49 Slices 1–69 and existing CLI tests; `python -m pip check`; exact scoped commit and push.
- Windows symlink tests may skip on unprivileged hosts; permission skips are not a substitute for environments able to run those checks.

## Acceptance boundary

A positive builder result means **only** that the unsigned requested inventory of already staged bytes was consistently generated from a plan-bound audit. Native artifacts remain untrusted for activation until an external authorized signer verifies their provenance and issues a root-quorum envelope, the physical bytes are rechecked, and the witnessed update transaction passes its subsequent safe activation and recovery controls.
