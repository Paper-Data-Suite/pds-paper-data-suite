# Suite #19F2 — Manual-only unresolved pages after Core retention

**Scope:** Read-only teacher-facing handling of an approved, entirely unroutable
selection. No additional Core custody, failure/resolution writes, producer
handler, new qualification authority, automatic replay, or persistent queue.

The established #18 `prepare_retained_pds2_requests` returns a typed
`PreparedDispatchBatchV1(status="no_dispatchable_pages",
reason="no_valid_selected_routes")` when no selected physical page produces a
Core `RouteDispatchRequest`. Its report already accounts for selected
`unresolved_qr` pages and unselected `not_selected` pages. The F1 Core deferral
menu cannot be used: there has been no `CoreReviewResultV1`, no verified v2
routing failure receipt and no failure ID on which a third consent could act.

## Teacher path

- **V** in post-retention Teacher Home: read-only preparation on fresh
  Core-retained bytes; shows one-based source/page positions requiring manual
  inspection, plus count of unselected physical pages. It does not require a
  qualified wheelhouse or dispatch admission.
- **D** with a separately admitted runtime: the unchanged admission/workspace
  guards and source preparation run. If no requests exist, the bridge does not
  invoke `execute_with_core_review`, show a second consent, manufacture a Core
  review result or ask for `DEFER`. It displays the same manual-only physical
  page explanation and returns `no_dispatchable_pages`.
- Teacher may inspect the original page/QR and, only after independent
  ownership verification, use the qualified producer's **normal** review
  interface. No inferred student identity, class/work binding, module link,
  provider success, score, evidence capture or grade publication is implied.
  Core-retained whole-file custody from first consent remains.

## Boundary and rejection checks

The new `render_manual_only_followup` accepts only typed preparation with
`no_dispatchable_pages`, empty candidate set and matching reason. Each selected
page must belong to a Core-retained source, have `unresolved_qr` status and no
Core locator/failure category/failure ID. Every unselected page remains
`not_selected`; any contradiction fails closed rather than inventing a
failure record. Outputs contain bounded counts and one-based positions only,
not raw QR payloads, private paths, student data or opaque exceptions.

**Qualification needed:** Windows repository pytest (F2 and F1/E4/E3/D1/#18
regressions), Ruff, strict mypy, compilation, staged Git whitespace/path checks,
then remote HEAD race gate. These are run by the guarded user-side script; the
synthetic source preparation in this slice is not physical-scanner acceptance.
