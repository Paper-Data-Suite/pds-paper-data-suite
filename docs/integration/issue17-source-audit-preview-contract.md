# Suite #17 — Slice 1: Source audit and frozen read-only preview contract

**Issue:** [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)
**Starting Suite `main`:** `6dd9d421e52866b40f8b5e242557cf86a15bb84c` (2026-11-08)
**Core `main`:** `a0d5e1a50580bbe025f0cad23c7e8524203a52ec`; **latest published Core:** `v0.6.6`
**Status:** Slice 1 source/schema/fixture delivery; **no decoder, workspace access, provider execution or paper processing**. Not a qualified installed multi-module scan integration.

## One teacher workflow, staged engineering

Teacher experience after #17–#19: **Select source → review candidate destinations and unresolved pages → explicitly authorize processing → review owner-specific results**. Slice 1 freezes the in-memory observation boundary so #17 can add read-only decoding and #18 can later authorize Core retention and dispatch without confusing preview state with a durable record. This is **not** a standalone classroom application; any development-only CLI preview must remain a subordinate step to the eventual #19 Teacher Home workflow.

The user-facing `Process Returned Papers` home entry remains disabled until #19 is qualified; #17 does not relabel it as a complete processor. A simple opt-in preview command may aid diagnostics in later slices, but it is **not required as an independently marketed feature**.

## Inspected released Core contracts

| Concern | Public owner/interface | What #17 may do | What it must **not** do |
| --- | --- | --- | --- |
| PDS2 QR | Core `pds_core.pds2.parse_pds2_payload` | Parse decoded text to typed `RouteLocator` | Infer student, author, subject, assignment or a page's logical order |
| Registration | Core `pds_core.route_registrations.load_route_registration` | Optional exact, read-only structural lookup in an explicitly chosen, authorized workspace | Treat structural lookup as domain target validation or producer dispatch approval |
| Provider declaration | Core `inspect_core_provider_entry_points(provider_kind="routing_module")` | Metadata-only six-approved-component inventory; compare owning distribution to Suite registry | Import provider factory, build lenient dispatch registry or infer official publisher authenticity |
| Profile diagnostic | Core `diagnose_core_providers(provider_kind="routing_module")` | Explicit optional validation in a suitably trusted/isolated environment | Invoke a route handler or equate `provider.valid` with real routing qualification |
| Runtime dispatch | Core `pds_core.module_dispatch.dispatch_route(s)` | Document handoff for #18 only | **Call from #17 preview** |
| Source custody | Core `pds_core.scan_retention.retain_source_scan` | Document handoff for #18 only | **Call from #17 preview** |
| Shared inbox | Core `pds_core.scan_routes.scans_inbox_dir` | Suggest a bounded, teacher-selected source path | Autoload inbox contents, archive files or write workspace records |
| Page raster/QR decoding | **No universal Core public reader** | #17 implements bounded file/PDF raster and QR-observation adapter in Slice 2 | Fork Core PDS2 grammar, call producer-owned *mutating* scan intake, claim native decoder is a sandbox |

Core `RetainedSourceScan` is produced by deliberate custody and is **not** a preview record. A preview's SHA-256 observation is advisory; #18 must re-open and hash/retain the selected original again, check the active workspace, revalidate all targets and obtain explicit authorization.

## Producer and published-artifact census

| Module | `main` SHA on 2026-11-08 | Official wheel | Published `paper_data_suite.modules` routing entry-point | Slice 1 classification |
| --- | --- | --- | --- | --- |
| ScoreForm | `dbb4159bb2c4d04889742de746be42a394130170` | `scoreform-0.13.0` | `scoreform.pds_module:get_module_profile` | Declared; execution/dispatch unqualified by this slice |
| Quillan | `93cf0ae84887d79377e6f77c1d0c818af24688a5` | `quillan-0.10.6` | `quillan.pds_module:get_module_profile` | Declared; execution/dispatch unqualified |
| Concord | `4f2767e9e927b42dc15441bd31df91e7e6899d76` | `pds_concord-0.3.4` | `concord.pds_module:get_module_profile` | Declared; `pypdfium2` composition conflict pending |
| Meridian | `fc05b248139ce0eb8b58aadddc0c04cc96677d07` | `pds_meridian-0.4.2` | None | **Not declared**, not assumed a paper producer |
| Vitrine | `072a1ed653ea2e17932ff72964cb78300abfe5fa` | `pds_vitrine-0.4.0` | `vitrine.pds_module:get_module_profile` | Declared for Reflection, not arbitrary portfolio processing |
| Portia | `2bf30bba4daca0dd523824b3bf4aef5e72478f14` | `pds_portia-0.2.0` | None | **Not published/qualified**; developer-owned internal intake does not grant Suite routing |

These observations are from repository source and the published release-tag metadata. `paper_data_suite.module_operations` is **not** the routing entry-point group. The four declarations are not proof of installed-wheel runtime compatibility, authentication, or real PDF processing. Suite #16's operations-provider census is reusable **as a design pattern**, not as a routing authorization decision.

### PDFium co-installation conflict

Concord `pyproject.toml` requires `pypdfium2>=4.30,<5`; Vitrine's optional **paper/dev** extras require `pypdfium2>=5.13,<6`. These cannot both be installed as requested in a single interpreter, although Vitrine's base profile does not force the extra. Concord's observed `_default_decode()` uses `PdfDocument(path)` with per-page `page.render(scale=2).to_pil()`, rather than removed `PdfDocument.render()`; a v5 migration is **plausible but untested**. **[Concord #170](https://github.com/Paper-Data-Suite/pds-concord/issues/170)** owns compatibility evaluation, resource-lifetime changes, PDF/QR regression, exact installed-wheel verification and a compatible official release. Do not override Vitrine's newer constraints or force incompatible wheels into a teacher environment. Hold only the affected **combined installed-paper qualification**, not Slice 2's source decoder or Core #238 work.

Portia's later public-routing and attention handoff remains [Portia #67](https://github.com/Paper-Data-Suite/pds-portia/issues/67). Neither Portia nor Meridian must be artificially routed as ScoreForm/Quillan/Concord/Vitrine work.

## Frozen v1 observation model (in-memory only)

Implementation: `paper_data_suite.returned_paper_preview_contract`. Synthetic contract vectors: `tests/fixtures/issue17/preview_vectors_v1.json`.

| Model | Contract | Privacy/authorization limit |
| --- | --- | --- |
| `PagePreview` | One-based physical `page_number`, `status`, optional approved-format **candidate module ID**, optional `registration_status` | No raw QR text, `RouteLocator`, filename, route ID, target, student ID, module output or exception. `candidate_unverified` does **not** mean routed |
| `SourcePreview` | One-based `source_number`, source status, contiguous pages and optional lowercase SHA-256 advisory | Source number is **not** a durable retained-source ID. No path hierarchy or sensitive filename. Failed source cannot claim observed pages |
| `ModuleRoutingPreview` | Core module ID plus **distinct** metadata and explicitly evaluated profile state | Not release provenance, launch eligibility, domain readiness or authorization. Bad declaration cannot claim a valid provider profile |
| `IntakePreview` | `contract_version="1"`, ordered sources and routing rows, literal `processing_performed=False` | Immutable, ephemeral, never persisted as a custody or processing receipt |

Page status vocabulary: `candidate_unverified`, `missing_qr`, `unreadable_qr`, `invalid_or_foreign_qr`, `ambiguous_qr`, `page_decode_failed`. Source status vocabulary: `observed`, `source_unavailable`, `unsupported_format`, `resource_limit`, `backend_unavailable`, `source_decode_failed`. Registration vocabulary: `not_checked`, `workspace_unavailable`, `registration_not_found`, `registration_invalid`, `registration_inactive`, `structurally_consistent`. None of these assert that a producer handler was called.

The model deliberately **does not transport Core's typed locator** across the teacher-facing view. Slice 2/3 may hold a Core locator only within a transient private read-only decoder/controller object for exact optional lookup. It must not persist/serialize that object in Suite settings or diagnostics, convert it to student attribution or hand it directly to #18 as authority. Source/hash checks and page selection are repeated by #18 on authorized execution.

The synthetic fixture documents a **mixed twelve-page** observation with seven candidate pages across four supported published modules, Portia, and an unknown module, plus absent/unreadable/ambiguous/invalid/failed states. Additional cases cover missing native PDF backend, oversized source, unsupported format, valid PDS2 for six module IDs and invalid legacy/foreign/duplicate/Unicode/oversized QR strings. These are *logical* vectors; Slice 2 will produce real QR image/PDF fixtures and verify the physical rendering/decoder boundary.

## Nonmutation, privacy and dependency gates

1. **No automatic side effects**: no workspace creation, Core custody, Core dispatch, producer module callbacks, Grade/Score/Portia writes, receipt storage or source archival. Imports and model construction are pure. Any later temporary decode outputs must live outside the classroom workspace and be cleaned up.
2. **No authority confusion**: a QR candidate, registration observation, metadata declaration and profile-validation result are different claims. Actual dispatch and teacher authorization are future #18 concerns.
3. **Safe reporting**: only bounded code-like statuses and source/page positions cross into standard teacher presentation. Do not expose raw QR strings, private routes/targets, filenames with student names, file paths, scanned page bytes or exception tracebacks in ordinary display/diagnostics.
4. **No optimistic parser fallback**: Core's ASCII/256-byte PDS2 grammar is authoritative. No legacy PDS1/OMR1 acceptance. Multi-QR pages must remain ambiguous unless exact duplicates deduplicate to one distinct valid candidate; a malformed nonduplicate QR cannot silently disappear.
5. **Independent absence**: uninstalled, missing, unqualified or foreign producers do not suppress observations of other pages. Future strict Core runtime registry must still fail closed on conflicts rather than assembling a partially trusted registry.
6. **No false green claim**: source/fixture tests ≠ native scanner test ≠ installed-wheel test ≠ genuine teacher-authorized processing. Use distinct evidence labels.

## Slice 1 acceptance and handoff

- [x] Source audit and current-release routing-participant matrix documented, including source SHAs, Core installed-versus-source caveat and Concord #170.
- [x] `PREVIEW_CONTRACT_VERSION="1"` models with immutable, bounded, non-authorizing statuses and physical/source ordering invariants.
- [x] Synthetic JSON vectors for mixed modules, unsupported/missing inputs, missing/ambiguous/foreign/invalid QR, and selected valid Core PDS2 payloads.
- [x] Contract tests prevent mismatched page-module status, noncontiguous physical pages/sources, malformed fingerprints, false `processing_performed` claims and invalid routing-profile promotion.
- [ ] Focused tests on actual installed Core (CI/teacher host evidence recorded separately).
- [ ] Real PDF/image page raster + QR decoding (Slice 2, not claimed here).
- [ ] Any full teacher processing or official mixed-module composition qualification (#18–#19, not claimed here).

**Slice 2 handoff:** implement an injected, bounded, strictly read-only decoder and a deterministic observation producer consuming this contract; verify with synthetic PDF and QR image fixtures. Do not import/reuse producer **mutating** intake entry points. Preserve an opt-in future CLI/test harness only as a means to qualify the staged teacher workflow, not as an unrelated standalone application.
