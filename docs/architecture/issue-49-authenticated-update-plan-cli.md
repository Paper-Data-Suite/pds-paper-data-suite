# Issue #49, Slice 65 — Explicit authenticated update review command

## Scope

Implement a **read-only teacher entry point** to the Slice 64 composition planner while retaining all of Issue #49's security and lifecycle requirements. No source/installation state is mutated, no wheel is downloaded, no process is launched, and no classroom workspace is read beyond the existing explicit Slice 63 boundary validations. The only permitted external interaction is the operator-requested provisioned HTTPS witness challenge.

```text
pds update --plan --target quillan=0.10.0 \
    --catalog-cache CATALOG.json \
    --trust-policy POLICY.json \
    --trust-sha256 <independently-pinned-policy-sha256> \
    --witness-config SELECTED-WITNESS.json
```

Use multiple `--target component=version` arguments to request a mixed composition. An explicit `component=REMOVE` denotes a requested removal; its dependent components must remain satisfiable. Versions are exact signed release claims, not `latest` aliases, development branches, untrusted local metadata, URLs, or package names chosen from PATH. The target platform and Python version come from the invoking Python interpreter for review only and are not independently authenticated target runtime measurements.

## Integration boundary

Slice 63 previously validated all witness configuration, trust pins, cached signatures, signed evidence inventory, and two fresh externally signed witness responses before formatting a text diagnostic. Refactor its implementation minimally into:

- `inspect_selected_witness_catalog_evidence`: same checked pathway, returning the authenticated `CatalogSnapshot` and transient `WitnessSelectedStageObservation` to a trusted Suite caller; does not grant execution authority.
- `inspect_selected_witness_catalog_audit`: unchanged public signature, now renders those checked observations; legacy CLI behavior and test expectations remain intact.

Slice 65 parses targets before invoking this evidence reader, invokes `plan_authenticated_composition_review` only after the verified pair is returned, and renders the requested/due-to-dependency changes, exact scope losses/gains, unresolved external requirements, and proposed wheel hashes. **No authenticated claim that a release exists means its wheel has been downloaded or installed.** In particular, a complete signed transitive wheel lock, staged verification, privileged activation, protected receipt, recoverable update, and separate foreground-launch verification are not implemented by this slice.

## Refusal and backward compatibility

Incomplete flags, duplicate/invalid targets, unsigned/revoked/incompatible release versions, unresolved dependency closure, missing/unsafe trust/evidence inputs, invalid witness responses, or changed staged files refuse without any fallback to the historical exact-version launcher. `pds update` without `--plan` refuses. Existing `pds modules`, `pds doctor`, and `pds launch` remain unchanged and offline.

The witness configuration is supplied explicitly and its pins must originate independently; the config JSON itself is not an authority. Errors are bounded descriptions that do not include secret keys, student data, or full machine paths. Default teacher use must not invoke the witness.

## Deferred work

A guided whole-composition "choose latest" experience, read-only online update discovery, independently provisioned production trust roots/signatures, authenticated complete wheelhouse preparation, consent, protected managed activation and receipt finalization, rollback/forward recovery, and real installed-wheel acceptance remain separate #49 integration/qualification gates. These must not be inferred from a successful plan.
