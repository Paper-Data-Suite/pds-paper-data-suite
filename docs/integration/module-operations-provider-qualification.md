# Suite #16 — Module operations: metadata census and evidence levels

**Status:** Slices 1–2 source-implemented, **not** installed provider/readiness/attention qualification. **Source baseline:** Suite `main` `75c2781ec7e233af351417bbbcf9d72d8a16ac5d`, Core `main` `a0d5e1a50580bbe025f0cad23c7e8524203a52ec` (2026-11-06). Revalidate before the final #16 acceptance review.

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
- **Slice 2 (this change):** deliberate `collect_module_operations_profile_diagnosis(metadata_inventory=...)` uses Core `diagnose_core_providers(provider_kind="module_operations")` only when explicitly requested. It independently projects profile-validation/error states per approved owner, counts unapproved diagnostics, recognizes declared readiness/attention callables but **never invokes** them, stores no Core profile object or raw provider message, and keeps source/launch/provenance evidence separate. A Core diagnostic factory may execute installed Python code; this is not an OS sandbox or an automatic home operation. Negative tests cover identity conflicts, missing/foreign owners, malformed results, Core diagnostic failure and sibling isolation. `provider.valid` does not mean `readiness evaluated` or `no attention`.
- **Slice 3 / final #16 review as needed:** isolated *official wheel* smoke with exact hashes, optional **explicit** Core-owned synthetic readiness/attention evaluation (never as part of metadata/home discovery), update the #51 dependency matrix with genuine evidence and deferrals; ensure #49 doctor/launch CLI regressions and CI pass.
- **Suite #52:** consume the availability inventory without performing provider execution while drawing the home; show missing/unqualified states honestly.
- **Suite #20–#23:** qualify actual attention and any inert `ModuleOwnerActionRef` handoff separately. Personal Notes/Tasks are not canonical module attention.

Do not reintroduce the deferred #49 signed-catalog publisher/installer machinery for ordinary manual-wheel provider discovery.

## Slice 3 — Exact-release wheel evidence and synthetic Core invocation vectors

**Implementation evidence only until the commands below run on real wheel assets.** The new [`scripts/issue16_official_wheel_acceptance.py`](../../scripts/issue16_official_wheel_acceptance.py) pins seven exact GitHub release wheel filenames, distribution identities, versions and **GitHub release asset SHA-256 digests observed on 2026-11-06**: Core v0.6.6 and the six public producer releases in the table above. This is a dated, reproducible acceptance set, **not** a new Suite dependency minimum, immutable provenance certificate, independent publisher signature, or authorization to install packages in a teacher environment.

The default mode reads **only local wheel ZIP bytes** and their `METADATA` / `entry_points.txt` in memory. It hashes the complete bytes before metadata inspection and checks each producer's exact Core operations v1 entry-point name and target. It never imports a wheel or calls a provider. Its bounded states are `not_supplied`, `digest_mismatch`, `invalid_archive`, `invalid_metadata`, `entry_point_missing`, `entry_point_mismatch`, and `verified_metadata`. **`verified_metadata` proves neither profile validity nor operational readiness/attention**; a discrepancy is evidence of an actual release/source gap to investigate, not a reason to patch Suite's approved identities without review.

After Slice 3 lands, the teacher/developer may run (PowerShell, in the Suite checkout):

```powershell
$python = ".\.venv\Scripts\python.exe"
$wheelhouse = Join-Path $HOME "Downloads\pds16_official_wheels"

# Optional explicit download: only the seven GitHub release assets pinned by SHA-256.
& $python scripts\issue16_official_wheel_acceptance.py `
    --wheelhouse $wheelhouse --fetch-official --require-complete

# Read-only repeat with no network, install, provider imports or callbacks.
& $python scripts\issue16_official_wheel_acceptance.py `
    --wheelhouse $wheelhouse --require-complete

# Separately authorized execution: installs ONLY to a disposable offline venv,
# then calls Core's zero-argument module-operations profile diagnosis. This
# executes installed Python package code; it is not an OS sandbox.
& $python scripts\issue16_official_wheel_acceptance.py `
    --wheelhouse $wheelhouse --profile-smoke
```

The last command performs no readiness/attention evaluation and **does not install or downgrade the active `.venv`**. Its isolated venv uses offline `pip --no-index --no-deps`; missing non-PDS dependency wheels may cause `profile_import_or_diagnosis_failed`. This outcome is **not qualified**, not a false provider absence, and must be recorded separately. Before the end-of-ticket acceptance, record actual output for each of the six wheels, Python/OS, hashes and Core version in a PR review note. The script suppresses subprocess diagnostics/private paths; more detailed troubleshooting belongs to separately approved testing, never a real student workspace. Downloads are opt-in, and no supplied wheel is overwritten on a digest mismatch. Network/download errors and isolated environment failures are honest blockers for that gate, **not** blockers for already-qualified metadata-only Suite home discovery.

`tests/test_issue16_official_wheel_acceptance.py` exercises exact metadata/digest refusal using synthetic, test-only ZIP fixtures; its successes **do not** assert the official wheels were downloaded. `tests/test_issue16_core_invocation_vectors.py` invokes *installed Core's public v1 functions against entirely synthetic callbacks* and distinguishes evaluated ready/false, evaluated empty attention, unavailable, capability absent, provider exception, invalid report, wrong-class context and foreign-owner inert action reference. Neither fixture test invokes real producer readiness/attention, edits student data or creates workspaces.

### Evidence / handoff gates

| Gate | Scope | State before developer runs the opt-in commands |
| --- | --- | --- |
| D0 | Core operations v1 and Suite owner boundaries | Documented in #16 and Core public contracts |
| D1 | Six producer source declarations; Slice 1 metadata-only and Slice 2 explicit profile-diagnosis projection | Source implemented; targeted local regression log required |
| D2a | Exact seven official GitHub release wheel hashes and static metadata | **PENDING real wheelhouse run**; expected digests recorded, not independently verified bytes in this change |
| D2b | Exact installed, disposable environment; six profile factory diagnosis results | **PENDING opt-in profile smoke**; report blocked outcomes, do not fabricate passes |
| D3 | Actual module-owned readiness/attention with qualified scope; user-facing action routing | **DEFERRED** to Suite #20–#23 and producer-owned adoption |
| D4 | Mixed-application teacher home/workflow and physical paper journeys | **DEFERRED** to Suite #52 and #27/#28 |

**Slice 3 completion gate:** updated docs, exact-wheel evidence tool, focused failure/ownership tests, static typing and CI. A failed optional real-wheel run must remain a visible release-qualification exception/producer follow-up, not trigger uncontrolled infrastructure changes in #16. Keep the Suite home metadata-only and never interpret a personal Task as producer attention.
