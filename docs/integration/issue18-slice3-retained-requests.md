# Suite #18 Slice 3 — Retained-byte PDS2 request preparation

**Issue:** [Suite #18](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/18)
**Branch:** `18-core-retain-first-mixed-paper-dispatch`
**Starting commit:** `f3ad9bcadbef6cda80b53e4728bc7339d28db189`
**Core dependency:** public `pds-core` 0.6.6 PDS2 and `RouteDispatchRequest` contracts

## What this slice does

`prepare_retained_pds2_requests(authorized_retention, *, decode, limits)` accepts
an approved, **completely retained** Slice 2 result, checks the exact Core
retained-source receipt, reopens the retained file and decodes physical pages
using the **existing Suite #17 bounded reader**. It parses exact decoded PDS2
strings using the **real Core parser**, creates **actual Core**
`RouteDispatchRequest` values for only explicitly selected, uniquely identified
pages, and returns a transient `PreparedDispatchBatchV1`.

The service never imports or discovers producer profiles, calls
`dispatch_route(s)`, invokes handlers, writes a Core review failure/resolution
or changes any file. It does **not** use an original file or a `PagePreview`
module ID to manufacture a route locator. Existing registration observations
in the preview are not processing authority. The caller must not persist or
serialize these in-memory request objects as independent authorization tokens.

## Step-by-step safety contract

1. Require a typed `AuthorizedRetentionResultV1` with `approved=True`,
   `status="retained"`, all selected pages `retained_only`, and a genuine Core
   `RetainedSourceScan` receipt for each selected source. A cancelled, partial,
   rejected or uncertain batch is **not** automatically advanced. Recovery for
   partially retained sources is an explicit later #18/#19 workflow.
2. Verify each receipt's source name, expected SHA-256, canonical
   `scans/source/YYYY-MM-DD` workspace-relative path, unchanged actual bytes,
   and safe link-free path before decoding. Reuse the existing bounded Suite
   reader and source format/magic check; do not reimplement PDF or QR decoding.
3. Compare the **entire physical-page sequence** from retained bytes against
   #17's originally observed statuses and module IDs, including unselected
   pages. Retained bytes/hash, count or QR observation changes fail the
   **whole prepared batch closed**. No requests are returned on partial
   validation. The original preview never held raw route IDs, so a stale
   preview alone cannot establish unchanged route IDs; the fresh PDS2 locator
   is parsed only from bytes checked against the original source SHA-256.
4. Each selected page with one unique valid PDS2 code becomes a typed Core
   `RouteDispatchRequest(locator, retained_source, source_page_number)` with
   its one-based physical page. Multiple distinct codes, QR corruption,
   missing codes, invalid, oversized and foreign payloads remain
   `unresolved_qr`, never a guessed module route. Repeated **identical** QR
   observations on one page are treated as one candidate, consistent with #17.
5. Preserve original source and physical-page ordering, regardless of the
   input selection order; do not reorder or suppress unselected and unresolved
   page receipts in the Suite report. `prepared.candidates` contains only
   selected valid routes and is never a module authorization decision.
6. Report `ready`, `no_dispatchable_pages`, `blocked` or `uncertain` as distinct
   transient conditions. `blocked` covers unavailable/broken native decoders;
   `uncertain` conservatively describes broken custody or observation drift.
   Errors and `repr` must not reveal original paths, raw QR strings,
   producer exception bodies or student identifiers.

## Core and ownership boundaries

The only newly invoked Core runtime APIs are
`pds_core.pds2.parse_pds2_payload` and the constructor for
`pds_core.module_dispatch.RouteDispatchRequest`. All retained bytes were
written by Core `retain_source_scan` during Slice 2, not by Slice 3. Core
route registration and profile validation, dispatch success/failure and
producer handler behavior remain **Slice 4**. Core v2 failure/resolution
persistence and explicit retry/recovery remain **Slice 5**. Teacher Home UX
and teacher next actions belong to **Suite #19**.

The adapter calls Suite #17's existing internal bounded `_read_source` and
`_source_format` functions; these are *Suite-local* helpers, not new Core or
producer contracts. They remain side-effect-free and refuse unsupported
source signatures/unsafe reads. The injected `decode` callback is only a
qualification seam and is untrusted executable code; production selects
`decode_with_optional_backends`, not an arbitrary provider.

A Core request only identifies a route candidate; it is **not** proof that a
published profile is installed or compatible, and is not a student/assignment
identity or any final grade, evidence, publication, Concord review or Portia
behavior record. No Suite #49 release manifest or Core Notes private-storage
file is modified. Concord #170's PDFium version conflict remains separately
unqualified for a combined Concord + Vitrine[paper] interpreter.

## Acceptance evidence and next gate

- Synthetic isolated test matrix: selected/unselected pages, mixed modules,
  QR ambiguity and foreign/legacy payloads, real Core-typed request shapes
  (shimmed only for local authoring, **not shipped**), exact custody reuse,
  retained-file deletion/tampering, lost decoder, changed physical-page count,
  later-source drift and no-writes proof.
- Required teacher Windows gate: installed Core 0.6.6, focused #18/#17 pytest,
  Ruff, strict mypy, exact SHA and staged-path checks; commit and push only
  after success. The optional native decoder tests may legitimately skip if
  PDFium/ZXing is not installed in this specific Suite venv.
- No installed multi-producer dispatch, native/scanner acceptance, or fresh
  GitHub Actions cross-platform result is claimed by the source-only package.
- Next: Slice 4 consumes only valid `PreparedDispatchBatchV1` instances,
  revalidates retained-source freshness at the moment of dispatch, enforces
  Core's **strict** module registry, then dispatches individual pages in order.
  It must never treat preparatory request objects as safe replay tokens or
  silently retry an uncertain handler outcome.
