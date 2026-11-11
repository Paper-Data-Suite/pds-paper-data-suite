# Suite #17 — Slice 4: compact teacher preflight presentation

**Parent:** [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)
**Starting issue branch:** `17-mixed-paper-read-only-intake-preview` at `9dd71806c7bf9018d61209035c30a5fa43727ae9`
**Status:** Source-layer implementation and Windows runner; live/native scanning and installed-composition qualification still pending.

## One workflow, not a new classroom application

The final teacher journey is **select source → review candidate destinations and problems → explicitly authorize processing → review module-specific results**. This slice supplies the first two *observation-only* steps as a deliberately invoked CLI preflight. It **does not** enable Teacher Home's `Process Returned Papers` menu choice: Core retain-first custody and dispatch belong to #18, and the integrated Teacher Home action and outcomes belong to #19.

Example, after the native decoder prerequisites have been independently installed/qualified in the relevant environment:

```powershell
pds papers preview --source 'C:\Scans\returned-stack.pdf'
```

Multiple explicit files are supported by repeating `--source`; no default inbox scan or user file discovery occurs. An unreadable/missing file, unsupported format or missing backend is reported by position, **not** by the source's filename or path. This command makes no filesystem write, workspace selection, provider call or route lookup.

## Implementation boundaries

- `paper_data_suite.returned_paper_preflight.build_readonly_preflight` composes Slice 2's `observe_selected_sources()` (physical pages, real Core PDS2 parser) and Slice 3's **metadata-only** `collect_routing_metadata()`. Both are independently injectable in tests.
- `render_readonly_preflight()` consumes only Slice 1's immutable `IntakePreview` contract and renders bounded source/page information, candidate module counts, and exactly the approved routing declaration rows supplied by Core metadata. It never displays raw QR content, Core locators, registration target data, student identifiers, private paths or exception traces.
- Candidate modules are **unverified**, even where a published routing entry point was observed. The command **does not opt into** Slice 3's executable `evaluate_routing_profiles()` or optional route-authorized `make_core_registration_check()`; those are distinct, higher-trust diagnostics. The default `registration_not_checked` is truthful.
- First show unresolved/error pages (up to 12 per selected source); fill remaining visible slots with pages in physical order (up to 16 details per source). The full page/candidate/unresolved counts remain correct even where detailed rows are omitted. This is a textual preflight, not a page-image viewer or owner review UI.
- Exit status `0` means an observational preview completed, **not** every page is routable or a teacher action was authorized. Exit `1` indicates a selected source was not decoded or provider metadata was unavailable. `pds papers preview` without `--source` uses normal argparse error `2`.
- The ordinary `pds` no-argument interactive Teacher Home behavior, `pds --help`, and existing subcommands are preserved. `pds papers` alone prints only the nested help and does not scan anything.
- Explicit safety boundary: **no Core `retain_source_scan`, no Core `dispatch_routes`, no producer-owned scan-intake helpers, no ScoreForm/Quillan/Concord/Vitrine/Portia domain mutation**, no workspace notes, no cached receipt and no grade creation. Preview advisory hashes are not durable custody tokens.

## Tests and acceptance

Focused tests cover deterministic source/page summaries, physical order, omitted detail bounds, unknown/Portia routing candidates, missing QR, ambiguous QR, missing PDF backend, untrusted exception redaction, metadata failure, read-only service injection, actual CLI parser and explicit CLI dispatcher behavior, and parent help without scanning. All existing Slice 1–3 focused tests and critical #52 CLI/Teacher Home regressions should be rerun on the exact issue branch.

The Windows runner requires a clean `17-mixed-paper-read-only-intake-preview` branch at exactly `9dd71806c7bf9018d61209035c30a5fa43727ae9`. It checks new file digests, the Git-tracked original `cli.py` blob, applies a uniquely anchored CLI extension, compiles, tests against installed Core, executes Ruff and strict mypy, checks `git diff --cached --check` and staged path identity, then commits and pushes **only after passing all gates**. This package is not a new Suite wheel or a published release.

## Remaining gates and follow-on tasks

- **Slice 5:** exact official Core and producer wheel inventory, bounded native PDF/image+QR decoding (on Windows and supported platforms), mixed 4-module synthetic scanner acceptance, and actual source immutability/custody-negative evidence. Distinguish native-dependency skips from passing hardware/reader acceptance.
- **[Concord #170](https://github.com/Paper-Data-Suite/pds-concord/issues/170):** `pypdfium2>=4.30,<5` conflicts with Vitrine's `paper` extra's `>=5.13,<6`; a v5 update is plausible but must be qualified on scanned PDFs and co-installed wheels. Do not mask this in Suite with an unqualified direct dependency override.
- **[Suite #18](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/18):** deliberate teacher authorization, source re-open/revalidation, Core retain-first custody and dispatch. Never interpret a Slice 4 source number/hash as a custody receipt or dispatch permission.
- **[Suite #19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19):** one integrated Teacher Home processing workflow and owner-specific processing results; the standalone diagnostic CLI is not a substitute.

**Qualification labels:** Source tests / Windows source tests / native scanner smoke / installed-wheel compatibility / teacher-authorized processing **must remain distinct**.
