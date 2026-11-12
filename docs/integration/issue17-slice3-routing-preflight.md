# Suite #17 — Slice 3: Core routing metadata and optional read-only registration checks

**Issue:** [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)
**Feature branch:** `17-mixed-paper-read-only-intake-preview`
**Starting branch commit:** `5482743145964b27844ab11d328ef51bf21a7b8b`
**Published Core contract:** `pds-core` v0.6.6, PDS2 routing contract `1`
**Status:** Source implementation pending teacher Windows/CI qualification. **Not a dispatch, teacher authorization, official wheel, or native scanning qualification.**

## Why this slice exists

Slice 1 established immutable, privacy-minimized preview statuses. Slice 2 added bounded PDF/JPEG/PNG page observation. Slice 3 connects those observations to **Core's existing routing-provider metadata** and, *only on explicit request with route-specific authorization*, an exact **Core read-only route-registration lookup**. It does not combine Core routing metadata with launch eligibility, operations-provider readiness, or software provenance.

One eventual workflow: **Select source → Review proposed page destinations and problems → Authorize processing → See owner-specific outcomes.** This slice implements the middle preflight, not an independent teacher application. Suite #18 owns Core retention and dispatch; #19 owns complete Teacher Home activation.

## Source changes and public surfaces

- `paper_data_suite.returned_paper_routing_preflight.collect_routing_metadata(inspect=...)`: default invokes `pds_core.provider_diagnostics.inspect_core_provider_entry_points(provider_kind="routing_module")` without loading providers. Returns six `ModuleRoutingPreview` rows, fixed approved Suite registry order, plus an unapproved metadata count and inspection-available flag. Missing, duplicate, invalid, foreign-owner and inspection-failed cases are distinct.
- `evaluate_routing_profiles(inventory, diagnose=...)`: **separate opt-in executable** zero-argument routing-provider diagnosis through Core. A validated profile must have the approved distribution and module ID, routing contract `1`, PDS2, registration schema `1` and `active` dispatch status. This checks **profile shape and public compatibility, not producer execution**. It does not construct a runtime registry or infer permission to dispatch.
- `make_core_registration_check(workspace_root, authorize_route=...)`: explicitly opt-in callback taking `(source_number, physical_page_number, transient_Core_RouteLocator)` and returning only a bounded `RegistrationStatus`. It requires an existing absolute workspace and the caller's **route-specific authorization**. It calls Core's public `route_registration_path` and `load_route_registration`, refuses symlinked/reparse-point route ancestors or paths escaping the workspace, and returns only `workspace_unavailable`, `registration_not_found`, `registration_invalid`, `registration_inactive` or `structurally_consistent`. No route contents, Core `RouteLocator`, fallback text, student data or path leaks into the preview model.
- The existing `observe_selected_sources(..., registration_check=None)` decoder gains **one optional callback parameter**. Default remains unchanged: no route lookups or providers. A valid parsed PDS2 locator is passed transiently to the callback during observation; `PagePreview` still holds only module ID and bounded status. Invalid/ambiguous/missing QR pages never invoke registration checks. Callback failure does not demote a syntactically valid QR into an unsupported source or reveal its error.

**Critical distinction:** `candidate_unverified` + `structurally_consistent` means only that the syntactically valid PDS2 locator has a present, active, Core-valid persisted registration. It does **not** verify that a student is the author, that a producer target exists, that producer validators/handlers can run, that work has not changed, or that this is an authorized paper-processing command. A profile can be `profile_valid` and the route still be unqualified.

## Security and fault boundaries

1. Opening the normal preview does **not** import routing-provider factories or inspect Core route files. Metadata-only reading is independent of scan source decoding.
2. Explicit profile diagnosis **does** execute installed provider factory code. It is not sandboxed merely because it uses Core's public diagnostics and must be a deliberate trusted or isolated operation. Do not call automatically from Teacher Home or during default preview.
3. Explicit registration lookup requires a trusted caller-supplied `authorize_route(root, locator)` decision. This slice **does not implement or invent a teacher authorization system**. A selected workspace alone never authorizes class/route lookup. Without a callable authorizer, the result is `workspace_unavailable`.
4. The read-only path reuses Core's exact validator/reader and performs an additional best-effort path containment and link/junction check. This is **not an atomic anti-TOCTOU guarantee** against a concurrently hostile filesystem. #18 must reauthorize, verify immutable source bytes via Core retention, and revalidate before dispatch. Do not claim this preliminary check is equivalent to a secure custody transaction.
5. Explicit Core `load_route_registration` may report missing, invalid or inactive registrations, but only the bounded status reaches a user view. Core's human fallback, private module target, root path and raw QR text do not.
6. Provider metadata name/distribution normalization uses ordinary PEP 503-style identity comparison; it is **not signed-wheel provenance or a guarantee that installed code is trusted**. A valid diagnostic is not a ready-to-dispatch `ModuleRegistry`. Conflicts must remain visible and runtime discovery continues to fail closed.
7. Portia v0.2.0 and Meridian v0.4.2 lack published `paper_data_suite.modules` entry points; don't fabricate routing participants. Source Portia work belongs to [Portia #67](https://github.com/Paper-Data-Suite/pds-portia/issues/67). The [Concord #170](https://github.com/Paper-Data-Suite/pds-concord/issues/170) PDFium v4/v5 conflict remains a separate combined installed-paper qualification gate.

## Qualification and expected next steps

Focused synthetic checks cover all six approved identities, approved/foreign/duplicate/invalid metadata, metadata enumeration failure, explicit profile validation and conflict handling, no profile elevation from bad metadata, absent/denied route-specific authorization, candidate-only callback invocation, no scan/source modification, missing/inactive/invalid Core registration, and symlink ancestry refusal. A dedicated test uses **real Core v0.6.6** `write_route_registration` / `load_route_registration` in a **disposable synthetic workspace** and verifies that the preview did not modify its bytes. No live teacher workspace or authentic student material enters tests.

Local container: 26 new/existing targeted tests passed, 3 skipped (actual Core parser/registration and native ZXing unavailable); the user Windows/CI run must exercise official Core and report genuine skips separately. Ruff, strict mypy, Git whitespace and full regression are to be checked on the actual Windows development environment before commit.

**Next:** Slice 4 integrates one compact opt-in preview presentation/CLI path without enabling the incomplete Teacher Home processing entry. After that, Slice 5 validates exact installed Core/producer/native-decoder compositions and prepares #18's retain-first dispatch handoff. No automatic installation of `zxingcpp` or `pypdfium2` is part of this source slice.
