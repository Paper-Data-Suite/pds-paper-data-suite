# Suite #19G4 — Consent-gated processing of explicitly selected local files

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)

**Reviewed parent:** `7599a4522ec2053649a83e06273bbd71897aebcb`

**Scope:** Close the remaining issue #19 input-path discrepancy without changing
Core custody or producer authority. The existing Teacher Home 9 → 1 local-file
preview remains *strictly read-only*. The newly distinct **9 → 3 Process
explicitly selected local files** choice accepts 1–8 manually entered absolute
PDF/PNG/JPEG source files, independently selects one **active Core workspace**,
and shows one-based physical-page observations without retaining or dispatching.

The new `returned_paper_teacher_local.py` controller consumes the existing
read-only preflight, inbox-compatible bounded physical-page parser, and #18
`build_processing_plan` and rendering APIs. It never implements a new decoder,
Core writer, route resolver, producer handler, gradebook or durable queue.
It rejects any source within the selected workspace's `scans/` custody tree;
Core's existing subsequent `_no_links` and byte-reverification checks remain
responsible for further source safety. Malicious same-account symlink races are
**not** claimed to be eliminated by the lexical guard.

## Teacher interaction

1. **9 → 1** is unchanged: explicitly selected local files may be observed,
   but not retained, routed or scored. The preview itself never becomes a
   processing authorization.
2. **9 → 3** separately requests source count and exact absolute filenames,
   then an **explicitly named active Core workspace**. An unavailable/mismatched
   active workspace refuses before file observation. No source is discovered,
   imported or written merely on entry.
3. #17 presents the same private-path-free physical-page statuses. Only
   **explicitly chosen** physical page numbers are selected; blank means skip,
   `*` is an affirmative all-pages choice, and the existing bounds remain
   eight sources, 64 pages/source and 512 selected pages.
4. **P** makes a fresh source observation and workspace check, then displays
   the *read-only* #18 plan and whole-file custody disclosure. **R** is refused
   without P; after P, it independently rechecks source and workspace again,
   and only then builds an immutable unauthorized #18 plan.
5. The controller hands that plan to the **existing**
   `run_teacher_first_retention`, with an independent **RETAIN** consent and
   Core-owned whole-source custody. Subsequent optional **D** uses the existing
   action-time official installed subset admission and fresh **DISPATCH**
   consent. Cancellation, uncertainty, manual-only routing and Core v2 deferral
   retain their existing fail-closed / no-replay semantics.

The preflight and plan renderers never print full private paths, raw PDS2
payloads, untrusted exceptions, student details or opaque producer state.
The Core-backed outcome may say `handler_returned`, which does **not** establish
successful student evidence, scoring, grades or publication.

## Qualification boundaries

- Source-contract tests cover exact page choice, plan freshness, workspace
  changes at P/R, invalid/blank page selections, protected custody refusal,
  option 1 nonmutating behavior, option 3 routing, and explicit handoff only
  after plan review. The regression runner must pass Ruff, strict mypy,
  affected tests, staged whitespace and exact file-scope/HEAD guards.
- Real installed positive/negative **local** acceptance must run against a
  **new Suite wheel built from committed G4 source**, with the same published
  Core 0.6.6 / ScoreForm 0.13.0 / Quillan 0.10.6 and native PDFium/ZXing/Poppler
  gate as G1. The opt-in E3A switch `-IncludeLocalFiles` drives four fresh
  *outside-scans_inbox* two-page synthetic Home journeys: cancel first,
  retain-only, cancel second, and approved two-producer dispatch. It checks
  original-byte preservation, Core-retained-source cardinality, page counts,
  privacy and absence of false academic publication.
- New opt-in source scope does not turn local metadata, unverified producers,
  unsupported OS/native combinations, an old Suite wheel, cached consent or
  `qualified_modules` into a live dispatch credential. Default E3A behavior
  remains unchanged without the new switch.
- **Do not mark G4 installed complete from local mock tests alone.** The
  source qualification, newly built installed wheel acceptance and full PR
  #61 CI must all pass. Keep #61 draft/unmerged while reviewing.
- Physical scanners, real student samples, Windows ARM64, hostile concurrent
  filesystem races, other producer modules and broad classroom certification
  remain outside #19 and belong to later explicit acceptance such as #27.
