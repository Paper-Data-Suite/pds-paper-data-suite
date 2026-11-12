# Suite #18, Slice 1: authorized-processing contract audit and frozen v1 seam

**Status:** Source-only planning contract. No authorization, scan retention, Core dispatch, provider import, producer write, or new CLI action is enabled by this slice.

**Suite issue:** [#18](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/18)

**Branch:** `18-core-retain-first-mixed-paper-dispatch`

**Drafting baselines (revalidate for each subsequent slice):** Suite `main` and newly created #18 branch `64ff97e304c5bcdbac8166a6d41a017181e20f35`; Core `main` `a0d5e1a50580bbe025f0cad23c7e8524203a52ec`; official Core v0.6.6. Suite's release compatibility manifest remains pinned to Core **0.6.3**, and the official Suite release is v0.1.0. No declared release pins were changed.

## Why this contract is necessary

The merged #17 [`IntakePreview`](../../paper_data_suite/returned_paper_preview_contract.py) is observational: a `PagePreview` has a page number, status, and *candidate module ID*. It deliberately contains no raw QR payload, complete `pds_core.routing_models.RouteLocator`, retained scan, teacher approval, or route-registration target. Constructing a dispatch request from an #17 preview would be fabrication. The first mutating slice must therefore re-read selected sources, obtain separate teacher approval, call Core retention, and decode the **retained bytes** afresh before attempting to construct real typed Core requests.

The new [`returned_paper_processing_contract.py`](../../paper_data_suite/returned_paper_processing_contract.py) establishes only these nonmutating shared shapes:

| Type/service | Responsibility | Explicit prohibition |
| --- | --- | --- |
| `PlannedSourceV1` | Keep a private, absolute path associated with the matching immutable #17 `SourcePreview` | Not a Core retained-source receipt; path-shape checks are not filesystem authorization |
| `SelectedPhysicalPageV1` | Preserve one-based selected physical-page identity and exact #17 observation | Not a PDS2 locator or approval |
| `PaperProcessingPlanV1` | Bind explicitly selected sources and pages to one specified workspace; `authorized=False` is immutable | Cannot carry/write consent; never reads or modifies filesystem |
| `build_processing_plan` | Produce the exact bounded plan from an `IntakePreview` and explicit selected page pairs, retaining input order | No implicit “all pages”, inferred route, automatic inbox selection, or provider load |
| `PhysicalPageOutcomeV1` | Distinguish selected/not attempted/retained/unresolved/unqualified/failed/returned/uncertain/review-write-failed pages | A “handler returned” state is **not** academic publication; an actual Core `RouteLocator` is required for a dispatch state |
| `SourceProcessingOutcomeV1` | Represent retention knowledge; a positively retained source requires a real Core `RetainedSourceScan` | Missing in-memory receipt is not proof no writer ran after a crash |
| `PaperProcessingReportV1` | Match every source and physical page to its selected plan, including unselected and unresolved pages | No silent omission, reordering or unauthorized page handling |
| `count_processing_outcomes` | Stable private-data-free status counts | Never call `repr()`/`str()` on producer module results |

The v1 contract is pure and creates no filesystem data. Its Python dataclasses are frozen and use `repr=False` for sensitive path and internal retained references. `PaperProcessingPlanV1.authorized` is fixed to `False`; a later slice must define an **independently checked** consequential approval capability, not flip a plan flag. A plan/source SHA-256 is an **advisory comparison**, not custody or identity. Path validation here checks shape only: symlink/reparse, workspace ownership, changed-file races, resource limits, and exact retained provenance belong to the corresponding later runtime checks.

## Observed Core public APIs (release v0.6.6)

- `pds_core.scan_retention.retain_source_scan(root, source_file_path, ...)` creates one **exclusive Core retained copy** of the entire source and returns `RetainedSourceScan`: `source_scan_id`, full SHA-256, canonical relative path, intake timestamp and date. Distinct repeat intakes are separate events.
- `pds_core.pds2.parse_pds2_payload(text)` returns an actual typed `RouteLocator`; a successful parse alone is not authorization or proof a target exists.
- `pds_core.module_profiles.ModuleRegistry` and `build_module_registry(...)` enforce exact profile identity, versions and duplicate refusal. Installed discovery **loads executable entry-point factories**; #17's metadata-only observation does not authorize those factories.
- `pds_core.module_dispatch.RouteDispatchRequest(locator, retained_source, source_page_number)`, `dispatch_route` and `dispatch_routes` form the actual dispatch boundary. `dispatch_routes` is **sequential**, isolates documented expected per-page exceptions, and preserves request order. It does not guarantee cross-module transactionality or handler idempotency. Unexpected interruptions can leave in-flight producer effects uncertain.
- `pds_core.scan_failure_metadata.routing_failure_metadata_from_dispatch_failure`, `write_routing_failure_metadata` and `pds_core.scan_resolution_metadata.create_scan_resolution_metadata` / `write_scan_resolution_metadata` own schema-v2 immutable failure and append-only resolution persistence. A failure to write review metadata is a separate failure, not a rollback of a producer effect.

Reference: [Core PDS2 module integration](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/pds2_module_integration.md), [active scan contract](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/active_scan_contract.md), [failure and resolution v2](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/scan_failure_resolution_metadata.md).

## Producer semantics (not interchangeable)

| Producer | Observed current public route-handler behavior | Scope/qualification consequence |
| --- | --- | --- |
| ScoreForm v0.13.0 | Validates registered answer sheet and issued context, reads retained source page, can score it | Handler return cannot generically be called “grade published”; replay must not re-score blindly |
| Quillan v0.10.6 | Validates exact immutable issuance, target and retained provenance; returns a typed page dispatch result **without** itself writing response evidence | “Handler returned” is not “writing captured” |
| Concord v0.3.4 | Handles returned Artifact Page filing and may mutate Concord-owned records | Requires special replay review and installed PDFium qualification |
| Vitrine v0.4.0 | Captures immutable Reflection returned-paper evidence via its own handler | Same-interpreter paper-extra conflict with Concord remains open in [#170](https://github.com/Paper-Data-Suite/pds-concord/issues/170) |
| Meridian v0.4.2 | No qualified published routing profile | Must be unavailable for dispatch |
| Portia v0.2.0 | No qualified published global Suite routing integration | Future [Portia #67](https://github.com/Paper-Data-Suite/pds-portia/issues/67) decides its adoption; no behavior records inferred from QRs |

## Independence from Core's open work

Core [#238](https://github.com/Paper-Data-Suite/pds-core/issues/238) and its open [PR #247](https://github.com/Paper-Data-Suite/pds-core/pull/247) implement **teacher-private Notes/workspace association**, not returned-scan custody. At this audit the PR does **not** change `scan_retention.py`, `module_dispatch.py`, `module_profiles.py`, the route-registration API, or PDS2 grammar. Core #239–#240/#243 are Notes; #241–#242 are roster/classroom menu; #244 is teacher-experience qualification. This issue has no hard dependency on those incomplete services. No Core source or issue is modified by Slice 1.

The current Suite release manifest's Core 0.6.3 pin, the earlier #17 native Core 0.6.6 scanner rehearsal, and the independent Concord/Vitrine PDFium v4/v5 dependency incompatibility must be reported **separately**. Neither an old combined-suite CI pass nor a source-only contract test proves full installed paper-processing compatibility. Do not weaken Suite #49 trust policy merely to make #18 run.

## Synthetic acceptance matrix for Slice 1

1. Frozen `authorized=False`; no filesystem reads or mutations from contract construction.
2. Explicit positive one-based selected source/page coordinates; stable user order; reject duplicate/missing/extra or silently all-pages selection.
3. Exact joining of observed previews to selected absolute paths, with no fabricated route locator and no selecting sources lacking a usable advisory digest.
4. All physical pages present in a result, including unselected and blocked pages; partial outcomes do not hide successful or unresolved siblings.
5. No unapproved page can claim processing; no selected page can disappear silently.
6. A dispatch state demands a real Core locator, and Core retained state demands the real Core retained receipt (actual typed runtime checks in installed Core environment).
7. No plaintext path, QR, producer exception or arbitrary module result representation in dataclass repr/counters.

Local isolated focused tests can be run before installed-Core qualification; Windows/Core, Ruff and strict mypy are required before committing. Cross-platform CI and genuine installed two-producer retention/dispatch acceptance remain later slices' separate gates.

## Next slice decision

**Slice 2** will add a read-only plan review and **separately guarded consent check**; after validating workspace, file currentness, physical bounds and approval it will use **Core's actual retain-source writer**. It must explicitly represent retained-but-not-dispatched outcomes and never use the immutable plan as an approval credential. No module handler is invoked until Slice 4. Failure/recovery v2 persistence follows in Slice 5. The teacher-home workflow remains Suite #19.
