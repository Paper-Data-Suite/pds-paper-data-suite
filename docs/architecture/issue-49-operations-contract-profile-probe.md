# Issue #49 — Slice 29: Explicit Core operations profile qualification

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `2d2ce8f` (runner validates the exact full commit)
**Status:** Isolated acceptance infrastructure; not production activation.

## Distinct claims

Slice 27 authenticated the provider declaration; Slice 28 verified that its
entry point could be imported and resolved to a callable. Neither check
invoked the provider factory or validated the resulting Core profile.

`probe_signed_operations_contract` adds **one intentionally narrow contract**:
`paper_data_suite.module_operations`, validated by the installed Core
`pds_core.module_operations.validate_module_operations_profile` function.
The candidate's signed wheelhouse, publisher release metadata, installed files,
launcher RECORD, and native executable bytes are checked through the existing
provider import preflight both **before and after** the factory invocation.

The staged interpreter runs with `-I -B`, no stdin, discarded stdout/stderr,
a temporary HOME/config/cache directory outside the classroom workspace, and
a bounded timeout. It checks installed `pds-core` distribution metadata and
that `pds_core/module_operations.py` is owned by that distribution. It resolves
the exact registered entry point, invokes the **zero-argument profile factory**,
passes the returned object to Core's validator, verifies `module_id` matches the
approved component, and requires Core's own operations-contract version in
the profile's supported version set.

It never calls the profile's `readiness_provider` or `attention_provider`, nor
any module operation, registration validator, route handler, or teacher-facing
command. An absent optional module-operations entry point is `NOT_DECLARED`;
an invalid profile raises a bounded, generic error rather than becoming a global
module launch failure.

## Explicit safety and provenance limits

- **The provider factory executes candidate Python code.** The process is not
  a sandbox; filesystem/user-level isolation from hostile code is not assured.
  Require deliberate user approval and use an appropriately isolated host for
  untrusted candidates. This probe is never invoked by ordinary launch, doctor,
  passive discovery, or background updates.
- The installed `pds-core` wheel is presently authenticated as an external
  closed dependency through the root-signed lock. The separately trusted Core
  publisher/migration provenance required by production remains unresolved.
- A valid operations profile is not evidence that its readiness/attention
  callbacks run successfully or produce safe classroom outcomes. Treat each
  named feature independently; never promote this observation to launch rights.
- This slice does not establish activated-installation history, a protected
  receipt, an upgrade transaction commit, or environment rollback correctness.
- A same-user process can mutate staged files concurrently despite the
  pre/post verification. No OS-level hostile-process containment is claimed.
- Tests exercise the genuine offline pip staging path for a *negative* Core
  compatibility case and use synthetic fixture evidence for positive
  orchestration. Actual released Core/module wheels need separate acceptance.

## Follow-on qualification

Check actual released Core and module wheel public operations profiles, then
scope any active provider invocations and PDS2 routing/publication interfaces
independently. Build authenticated installed-state continuity before integrating
with the teacher launcher or claiming a recovered software environment works.
