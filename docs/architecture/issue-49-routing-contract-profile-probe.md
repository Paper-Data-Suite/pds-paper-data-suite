# Issue #49 — Core PDS2 Routing Contract Profile Probe (Slice 30)

**Status:** additive opt-in acceptance primitive; **not** production launch wiring, software activation, Core compatibility guarantee, or an active-state receipt.

## Contract boundary

Core exposes the installed `paper_data_suite.modules` entry-point group through `pds_core.module_profiles`. A module's provider is a zero-argument callable returning `ModuleProfile`. `validate_module_profile` confirms that the profile is structurally valid, including that its route handler and optional registration validator are callable; this is not permission to call either callback.

`probe_signed_routing_contract` reuses the signature-bound pip installation and native interpreter verification of Slice 28. For an explicitly approved isolated staged candidate it:

1. Reauthenticates publisher signatures, wheel bytes, pip-installed payloads, the named routing declaration and root-signed native executable bytes. Rejects undeclared/foreign provider targets.
2. Requires explicit `allow_candidate_execution=True`, a bounded timeout, and a software location outside the classroom workspace. An absent optional declaration reports `not_declared`, with no subprocess execution.
3. Runs the exact staged Python interpreter with `-I -B` in a disposable directory under the *software* root. No network or classroom workspace access is requested.
4. Checks `pds-core` is installed and owns `pds_core/module_profiles.py` as a distribution file, and confirms the imported validator file is that installed file. Rechecks that the provider entry point belongs to the registered distribution and has the exact authenticated target.
5. Calls only the zero-argument profile factory; uses Core's `validate_module_profile`. Requires the profile's `module_id` to equal the declared registered module and support Core's own `CORE_ROUTING_CONTRACT_VERSION`. For the PDS2 workflow specifically, requires QR schema `PDS2`, route-registration schema `1`, and dispatchable status `active`.
6. Reauthenticates the entire installed candidate and compares the before/after observations. A subprocess error, changed installed file, changed native executable or changed evidence fails closed.

Only `pds2_profile_valid_not_dispatched` and `not_declared` are successful result states. An unsupported, invalid, throwing or otherwise unusable provider produces a failure, never an inferred module-wide verdict.

## Deliberate limits

- The provider factory executes candidate code, which may have side effects. `-I`, a sanitized environment and a timeout are **not a security sandbox**. Only explicitly approved throwaway test installations should be probed. The subprocess may access user files absent OS-level isolation.
- Neither a route handler nor its registration validator is called. The probe does not open scans, dispatch retained-source pages, mutate Core routes, process student data or demonstrate the real PDS2 workflow.
- Provider structural compatibility **does not authorize software launching**, native executable use, any live integrations, or an upgrade. Journal arming, protected active installation continuity, and full provider contract integration are separate gates.
- Existing independently verifiable module launch eligibility is not revoked when an optional routing provider is absent.
- Core ownership checks are tied to the staged installation inventory; trusted installed Core wheel identity and module publisher authentication are inherited from prior signed installation preflights. The probe creates no new independent trust anchor.

## Public API

`paper_data_suite.evergreen_routing_contract_probe.probe_signed_routing_contract`

The returned `ObservedRoutingContract` includes the exact transaction identity and the previously authenticated pip inventory/native/declaration fingerprints. It deliberately does not include `can_launch`, `ready`, or dispatch authorization fields.

This slice is additive and does not touch Suite's CLI, active slots, OneDrive workspace or production module execution.
