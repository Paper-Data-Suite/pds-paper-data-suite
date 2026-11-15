# Suite #19 — Slice 19B2: read-only Core inbox and physical-page selection

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `74e20d3decec080d50f1764c1f14ec3ffa57087f`
**Scope:** Add option 2 inside the existing Teacher Home option 9 preview controller. **No producer execution or workspace write.**

## Workflow

1. The teacher deliberately opens Teacher Home **9. Process Returned Papers — read-only preview** and selects **2. Select Core inbox entries and physical pages**. Nothing is inspected when Home starts or when option 9 is initially opened.
2. The teacher provides one explicit absolute Core workspace directory. The controller delegates inventory to #17 `list_selected_inbox`, which obtains Core's expected `<workspace>/scans_inbox`, enumerates at most **64** entries without opening file contents, and marks entries eligible, unsupported, oversize, or unsafe. The UI uses the preexisting path-free `render_selected_inbox`. No remembered/global workspace choice is used.
3. The teacher selects **1–8** eligible inventory entry numbers, in the requested order. Before any file preview, the controller **re-lists** the same inbox and requires its SHA-256 advisory snapshot to match the displayed snapshot. Stale, duplicate, oversized, unsupported, or out-of-range selections fail closed. The snapshot is *not* a custody token, OS identity credential, or processing authorization.
4. Selected paths alone enter #17 `build_readonly_preflight`, then `render_readonly_preflight`. The existing preflight reports physically numbered pages, unresolved/non-PDS2/ambiguous QR observations, and possible producer module hints without validating handler authority. No actual routing registration, producer handler, scoring engine, or student record is changed.
5. The teacher may choose a subset of **actual physical page numbers** for each successfully observed source, using `*` for all observed pages, commas for individual pages, or blank to skip a source. Page numbers are one-based and validated against that exact transient preview (max 64 per source and 512 overall). Unavailable sources are not selectable. No pages selected is explicitly reported.
6. The final read-only review reports selected physical-page count, **unverified** QR candidate count, and other/unresolved count. `ReadonlyPhysicalSelectionV1` holds only an advisory inbox snapshot, selected entry positions, and `(selected_source_position, physical_page_number)` pairs. The immutable record cannot claim `processing_performed=True` and is neither persisted nor handed to #18's plan/retention/dispatch APIs. B/M/Q navigation returns to the preview menu, Home, or quits Suite without executing anything.

## Boundaries and exceptions

- **Only the teacher's explicit option 2** imports the Core inbox picker. The original option 1 absolute local-file preview remains unchanged. Six application choices, Notes, Attention, recent applications, no-args non-TTY help, and launch/doctor boundaries remain untouched.
- Both the initial inventory and action-time re-list are #17 read-only. The preflight itself never retains a source, emits a Core custody receipt, validates a producer's registration as dispatch-ready, or creates a processing plan. If an original file changes **after** advisory preview, no execution is possible from the old state; later #19C/D must make their own fresh authorization and byte checks.
- Display no raw workspace/source paths, entry names, QR payloads, student IDs, opaque module results, traceback, or producer-provided exception messages. Exceptions, EOF, interruption, and invalid selections are safely categorized and never treated as consent.
- The final selected physical-page list is intentionally **ephemeral**. There is no persistent review receipt, cross-session selection, automatic return-paper ingestion, or producer launch. The historical #18's `qualified_modules` default-empty permission boundary is unchanged; #19A1/A2/A3 diagnostic objects still do not enable processing.
- This slice does not install optional PDFium/ZXing/Pillow packages or silently fall back to scanning. If a backend is unavailable, the existing #17 preflight reports the failure without processing.

## Acceptance and next work

`tests/test_issue19_slice19b2_teacher_inbox.py` covers explicit navigation and no eager scan, bounded/invalid workspace choices, stale snapshot re-list refusal, entry ordering, eligible-only selection, physical pages and candidate/unresolved review, cancellation/EOF/error privacy, ephemeral contract immutability, and parent Home preview routing. Scoped regression tests also cover 19B1, preexisting #17 preflight/inbox, and original #52 Teacher Home.

The guarded Windows runner requires the exact clean branch HEAD and Git blob for `returned_paper_teacher_preview.py`, verifies source ZIP and member hashes, applies only three precise string replacements in that file, tests targeted regressions, Ruff, strict mypy, compilation, and staged `git diff --check`; commits and pushes exactly four paths only on success. No full CI/running native pipeline claim is made from an isolated local test harness.

**Next:** connect a review of selected physical pages to a *new* teacher-authorized #18 `build_processing_plan`/Core retention flow under #19C. Before any producer dispatch, finish the separately reviewed live action-time installed composition/admission gate, fresh second dispatch consent, and #19G native installed acceptance. No UI selection created here is authority to skip those checks.
