# Suite #19 — Slice 19E4A: actual physical-page results in Teacher Home

**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `d52508b07377943f1ad9586f52cdc136764f7630`
**Scope:** one read-only results renderer, bridged into the existing #19E3B2 result. No producer execution or authorization changes.

## Problem and bounded design

The qualified #19E3B3 Teacher Home V/D entry reaches the existing Core execution bridge, but its E3B2 summary displays aggregates without teacher-facing one-based physical-page detail, Core review distinctions, safe failure references or next actions.

`returned_paper_teacher_results.render_core_paper_results` consumes **only** `CoreReviewResultV1`, whose `execution.report` already accounts for every physical page and whose `pages` already binds the independent review status to the same source/page/status triple. It derives a bounded summary (at most eight sources and 512 physical pages, guaranteed by #18), aggregate Core review states, Core-parsed locator grouping using the existing `count_ordered_dispatch_groups`, and a full source-number/page-number detail. `render_core_paper_page_detail` supports a one-based drill-down of that same immutable object without a second query.

The existing `render_teacher_dispatch_action` keeps all prior aggregate lines for backward compatibility and *appends* the new view when the bridge has a genuine Core result. Admission refusals and preparation failures still display no fabricated Core page outcomes.

Only safe, short identifiers from already typed Core-parsed `RouteLocator` and verified Core review IDs can appear. A missing route is printed `unknown`, not attributed to a class/work/student. Untrusted category text, raw payloads, private filenames/paths, student identifiers and opaque producer results are never rendered.

## Teacher semantics

- `handler_returned` means only the Core producer handler returned; it is **not** a ScoreForm grade, Quillan evidence receipt, publication or successful student-work capture.
- `recorded` is a separately verified Core v2 failure occurrence; it is not a resolution or a successful retry.
- `write_uncertain`, `uncertain`, `not_attempted`, `module_unqualified`, `unresolved_qr` and `not_selected` each remain distinct. Core custody is reported independently from per-page processing and review.
- The renderer is a synchronous **post-execution** snapshot. It claims neither real-time per-page events nor percent completion; no new progress callback, durable journal, retry or source scan is introduced.
- The displayed next actions are **guidance**, not clickable repair commands. Future #19F recovery needs its own separately reviewed Core resolution/deferral interaction.

## Qualification

The source-only/runner-only handoff adds the renderer, its focused tests, this document and one narrow edit to the existing bridge's result renderer. Full Windows verification runs the new tests together with the existing #19C2/D2, E3B1–B3, #18 Core dispatch/review and Teacher Home tests; Ruff, strict mypy, Python compile, Git checks and remote-head safety precede automatic commit/push.

No classroom/student data are used by these tests. Windows source qualification is distinct from the final full installed Teacher Home interaction tests required under #19G and follow-on issue #27. This slice does not broaden the exact Windows x64 Python 3.11 installed admission policy or allow missing producer partial admission.
