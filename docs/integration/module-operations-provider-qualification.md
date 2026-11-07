# Suite #16 — Module operations: metadata census and evidence levels

**Status:** Slice 1 implementation evidence, **not** a qualified provider/profile or teacher-attention release. **Source baseline:** Suite `main` `75c2781ec7e233af351417bbbcf9d72d8a16ac5d`, Core `main` `a0d5e1a50580bbe025f0cad23c7e8524203a52ec` (2026-11-06). Revalidate before the final #16 acceptance review.

## Owner and public contract

Suite consumes Core's `pds_core.provider_diagnostics.inspect_core_provider_entry_points(provider_kind="module_operations")` to enumerate **metadata only**. Core's `diagnose_core_providers(provider_kind="module_operations")` is an explicit, deeper operation that **loads and invokes** zero-argument factories; it does not invoke provider readiness or attention. The latter are separate `pds_core.module_operations` v1 calls that may read module-owned data and require deliberate scope/qualification. None of these operations grants application launch rights or authenticates wheel provenance. Ordinary #49 `pds modules` / `pds launch` remain authoritative for local launch eligibility.

The read-only Suite `collect_module_operations_metadata()` returns six rows in `APPROVED_COMPONENTS` order, preserving any separately supplied #49 launch state without gathering it as a side effect. It compares provider entry-point names and PEP 503-normalized distribution ownership against the Suite-approved identities, marks duplicates as ambiguous, counts unapproved rows but **never promotes** them to applications, and refuses to treat a Core metadata enumeration error as an empty provider list. Provider targets are deliberately not imported, executed, stored in the teacher-facing projection, or used to authorize a module.

## Source metadata census — not installed-wheel qualification

All six **current source** `pyproject.toml` files declare the Core v1 group `paper_data_suite.module_operations`. Their `pds_operations.py` source factories each declare readiness and attention callables. This is **D1 source evidence**, not D2 installed profile acceptance; the callback behavior and released wheel metadata must be independently tested.

| Approved ID | Distribution | Source factory target | Source Core requirement | Latest published release observed (not tested here) | Installed provider/profile / readiness / attention |
| --- | --- | --- | --- | --- | --- |
| scoreform | `scoreform` | `scoreform.pds_operations:get_module_operations_profile` | `pds-core>=0.6.5,<0.7` | v0.13.0 | **NOT QUALIFIED / NOT EVALUATED / NOT EVALUATED** |
| quillan | `quillan` | `quillan.pds_operations:get_module_operations_profile` | `pds-core>=0.6.5,<0.7` | v0.10.6 | **NOT QUALIFIED / NOT EVALUATED / NOT EVALUATED** |
| concord | `pds-concord` | `concord.pds_operations:get_module_operations_profile` | `pds-core>=0.6.6,<0.7` | v0.3.4 | **NOT QUALIFIED / NOT EVALUATED / NOT EVALUATED** |
| meridian | `pds-meridian` | `meridian.pds_operations:get_module_operations_profile` | `pds-core>=0.6.5,<0.7` | v0.4.2 | **NOT QUALIFIED / NOT EVALUATED / NOT EVALUATED** |
| vitrine | `pds-vitrine` | `vitrine.pds_operations:get_module_operations_profile` | `pds-core>=0.6.6,<0.7` | v0.4.0 | **NOT QUALIFIED / NOT EVALUATED / NOT EVALUATED** |
| portia | `pds-portia` | `portia.pds_operations:get_module_operations_profile` | `pds-core>=0.6.3,<0.7` | v0.2.0 | **NOT QUALIFIED / NOT EVALUATED / NOT EVALUATED** |

An installed-wheel acceptance record must identify exact artifact origin, version, SHA-256, active Core version, entry-point owner/name, profile identity, Core compatibility, supported capabilities, explicit synthetic evaluation outcome, and platform. It must say **NOT QUALIFIED** for any untested or unavailable pair. No implicit claim is made for installed wheels by checking a current source tree.

## Follow-up / handoff

- **Slice 1 (this change):** metadata-only public Core inspection; approved owner and duplicate detection; deterministic six-row projection; independent #49 launch-state field; negative tests. Absolutely no provider factory, readiness/attention callback, Notes, student records, workspace creation, network or process launch.
- **Slice 2:** explicit Core profile diagnosis, independently classified errors and optional, explicitly scoped synthetic capability invocation where safe. Do **not** reinterpret `provider.valid` as `readiness evaluated` or `no attention`.
- **Slice 3 / final #16 review as needed:** isolated *official wheel* smoke with exact hashes; update the #51 dependency matrix with genuine evidence and deferrals; ensure #49 doctor/launch CLI regressions and CI pass.
- **Suite #52:** consume the availability inventory without performing provider execution while drawing the home; show missing/unqualified states honestly.
- **Suite #20–#23:** qualify actual attention and any inert `ModuleOwnerActionRef` handoff separately. Personal Notes/Tasks are not canonical module attention.

Do not reintroduce the deferred #49 signed-catalog publisher/installer machinery for ordinary manual-wheel provider discovery.
