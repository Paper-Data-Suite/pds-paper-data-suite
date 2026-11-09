# Suite #17 — Slice 2: bounded, read-only physical-page QR observations

**Parent:** [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)
**Base issue branch:** `17-mixed-paper-read-only-intake-preview` at `cc72cea2acc5f5b47d3eb0955c25734f8278cf07`
**Companion contract:** `paper_data_suite.returned_paper_preview_contract` (Slice 1)
**Integration owner:** Suite only. Core retains PDS2 parsing/registrations, custody and dispatch. Producer modules retain their document/response interpretation.

## Purpose and boundaries

Slice 2 implements the **page-observation preflight**, not a user-facing standalone application. The eventual teacher interaction is one workflow: select sources, review candidate destinations and unresolved pages, explicitly authorize processing, review outcomes. Suite #18 performs Core retain-first custody and dispatch; #19 owns the complete Teacher Home experience. `Process Returned Papers` stays unavailable for actual processing until that integration qualifies.

The implemented `observe_selected_sources()` accepts an explicit tuple of source paths, **reads selected original bytes only**, and produces immutable Slice 1 `SourcePreview`/`PagePreview` observations. It never calls Core `retain_source_scan`, `dispatch_route(s)`, producer scan intake/route handlers, or workspace and private-data services. The caller must not persist previews as custody/authorization receipts.

The source SHA-256 is only an **advisory observation**; a later authorized #18 processing request must reopen, reauthorize, independently retain/hash bytes through Core, and revalidate registration/ownership. Even a decoded candidate is **not dispatch-qualified**.

## Interface and status mapping

Public entry point: `paper_data_suite.returned_paper_readonly_decode.observe_selected_sources(sources, *, limits=..., decoder=..., parse_payload=...)`.

- Sources must be expressly selected. No inbox walking, package loading, startup scanning, storage writes, temporary files, or path/QR dump.
- `DecodeLimits` defaults: at most 8 sources, 24 MiB per source, 64 PDF pages, 12 million pixels per page, 5000 pixels per dimension, 8 QR results per page, 512 characters per decoded candidate, and PDF raster scale 2.0. Limits are configurable **only downward or within audited ceilings** (16 sources, 32 MiB, 100 pages, 16 million pixels, 6000 dimension, 12 QR codes, 512 characters; PDF scale 0.5–3.0). These are memory/work bounds, **not** a native-code execution sandbox or a guaranteed timeout.
- File opening rejects a symlink source or symlinked parent, nonregular files, disappearing/switching file identities and changed size/mtime while read. It bounds source bytes, verifies `pdf`/`png`/`jpeg` extensions **and** file signatures, and hashes read bytes only in memory. Do not infer that this proves safe concurrent mutation or authorization.
- The default optional backend uses Pillow, QR-only `zxing-cpp`, and `pypdfium2.PdfDocument(bytes)` for PDFs. PDF pages are iterated in physical order, rendered with per-page pixel bounds, and PDFium page/bitmap/document plus PIL image resources are closed. Backends are lazy; no dependency is newly imposed by importing Suite.
- When the QR decoder reads no code, the status is `missing_qr`. This **does not assert** that a visually damaged QR is absent: distinguishing truly blank from **unreadable** needs a later separately qualified image-quality heuristic; Slice 2 does not fabricate `unreadable_qr`.
- A single distinct decoded string is validated by actual `pds_core.pds2.parse_pds2_payload` at runtime; no Suite PDS2 grammar. An exact duplicate string on a page is deduplicated. Conflicting, malformed-plus-valid or over-limit QR observations are **ambiguous** and never arbitrarily routed. Invalid or foreign schema is `invalid_or_foreign_qr`. Page-local rendering/QR failures are `page_decode_failed`.
- Backend import failures produce `backend_unavailable`. Oversized source/page/candidate inventories produce `resource_limit`; missing or unsafe selected sources produce `source_unavailable`; wrong signatures, corrupt decodes, invalid decoder executions and other source-read errors do not become successful observations. Only opaque bounded statuses are returned; no raw native error text or paths.
- `DecodedPage` is a **transient private seam** with no decoded text in its `repr`. Its payloads never enter `PagePreview`, `SourcePreview`, teacher-visible diagnostics or persisted settings. This module does not inspect provider profiles; Slice 3 owns Core's metadata-only routing inventory and optional explicit registration checks.

## Dependency and qualification caveats

- An installed Core v0.6.x provides the actual PDS2 parser. Its presence is independently checked by the Slice 1 Core-vector tests and Slice 2 injected/default-parser tests. A test parser may be injected for **synthetic unit tests only**, never to claim Core qualification.
- `zxing-cpp`, Pillow and `pypdfium2` are **optional** to Suite's general launcher. Missing native dependencies are visible as `backend_unavailable`, not an excuse to auto-install or downgrade a producer.
- Concord v0.3.4 pins `pypdfium2>=4.30,<5`; Vitrine's optional paper workflow uses `pypdfium2>=5.13,<6`. The incompatibility and candidate Concord v5 migration are owned by [Concord #170](https://github.com/Paper-Data-Suite/pds-concord/issues/170). Do not claim simultaneous, installed, full paper-workflow qualification before that ticket passes. The adapter makes only page-level `PdfDocument`/`PdfPage.render` calls and must itself be tested against whichever exact PDFium version the supported composition selects.
- Current published routing profiles are ScoreForm v0.13.0, Quillan v0.10.6, Concord v0.3.4 and Vitrine v0.4.0. Portia's future public integration remains [Portia #67](https://github.com/Paper-Data-Suite/pds-portia/issues/67); Meridian is not an installed public paper-routing provider. Slice 2 does not import any producer for decoding.
- Native PDF/QR libraries are not sandboxed. Operational deployment with hostile/untrusted PDFs should use an OS-isolated, timeout-controlled decoder boundary or separately qualify a threat model and execution limits; Slice 2 does **not** claim that protection.

## Slice 2 acceptance

1. Synthetic/injected page tests demonstrate all page/source classifications, original source and one-based page order, exact-duplicate handling and fail-closed ambiguity.
2. The original selected source bytes and filesystem inventories are unmodified; no Core retention/dispatch or module route handler is imported or invoked.
3. Missing file/symlink/unsupported format/mismatched magic/oversized file or pages/native backend failure produce bounded statuses with no raw private content.
4. Optional generated **synthetic** QR PNG and two-page PDF smoke runs when `zxingcpp`, `pypdfium2`, `qrcode` and `reportlab` are installed; absence is an explicit skip, **not** a physical acceptance pass.
5. Windows runner verifies exact parent commit, clean worktree, source SHA-256 and paths; runs Slice 1 and 2 focused tests, Ruff, mypy, whitespace check and commit/push only after success.
6. Broader CI, physical Windows scanner images, PDFium-version composition and no-timeout risk remain separately tracked; **no installed integrated intake pipeline is claimed** by a source-only slice.

**Next slice:** Core-backed routing provider metadata + optional read-only registration validation, then a compact preview presentation. Preview is still a stage of #17–#19, never independently authorized processing.
