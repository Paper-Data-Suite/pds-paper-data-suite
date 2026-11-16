# Suite #19 — Slice 19D1: inspect verified Core-retained page requests

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `e3339fbf851db29dcb6c7a6111321c24cca6e36d`
**Scope:** post-retention read-only request preparation, never second consent or a handler.

## Journey and ownership

After the teacher uses Home 9 > Core inbox > a fresh `P` processing-plan
review > `R` and explicitly types `RETAIN`, #19C2 delegates whole-original
custody to the existing **#18** `authorize_and_retain_sources`. 19D1 adds a
post-result **V. View prepared Core-retained page requests (READ ONLY)** choice
*only* when the #18 result is completely approved and `retained`.

The teacher can then deliberately select `V`. It lazy-imports
`returned_paper_teacher_preparation.review_core_retained_requests` and calls
the sole existing #18 request-preparation function
`prepare_retained_pds2_requests(retention)` on the just-returned Core receipt.
The original source preview strings and advisory B2 inbox snapshot are **not**
request construction authority. The #18 function checks actual Core-retained
bytes and source digests, re-decodes physical pages, checks the expected source
observations, and uses Core's PDS2 parser to produce typed requests. No Core
retention is repeated; no dispatcher, registry, or producer handler is called.

The path-free terminal view reports the exact preparation state:
`ready | no_dispatchable_pages | blocked | uncertain`, the bounded original
reason, verified Core custody receipt count, selected physical-page count,
prepared request count, unresolved selected pages, and *module IDs only* as
possible route destinations. It does not print paths, filenames, raw QR,
student IDs, class IDs, work IDs, route IDs, exception messages, or any
producer-owned result. Modules mentioned are explicitly **unqualified**.

A teacher can press `B`/`M`/`Q` instead of `V`. Blank/invalid/EOF or interrupted
post-retention input simply returns without decoding; these are never
approval. A cancellation, rejected retention, partial retention, or uncertain
Core custody result **never** opens the `V` choice. If preparation throws,
the UI displays a bounded refusal and asks for Core custody reconciliation;
it does not imply rollback or retry custody. This is only one optional view
for the just-completed retention event, not a saved processing session.

## Authority boundaries

- **First teacher consent** permits *Core source custody only*. It cannot
  permit eventual producer processing. Retention is durable; cancellation
  after successful custody does not undo it.
- **Prepared requests** are transient, not permission. The set may contain
  provider IDs not currently installed or supported. A `ready` value does
  **not** authorize any `qualified_modules` or producer import.
- **19D2** must build an independently reviewed second teacher consent
  (`DispatchReviewV1`/`DispatchDecisionV1`) tied to fresh Core-retained bytes,
  real action-time installed composition, compatible Core profile registry
  and no default-declared handler eligibility.
- **19E/19G** must qualify any actual dispatch on exact installed official
  wheels and native dependencies before allowing execution, with separate
  synthetic and installed end-to-end acceptance. The 19A3 isolated diagnostic
  is not a reusable admission token.
- No physical original is re-opened or retained by the D1 renderer itself;
  no teacher setting, activity log, grade, score, or dispatch record is written.

## Scoped qualification

New `tests/test_issue19_slice19d1_retained_preparation.py` checks synthetic
real Core custody receipts, explicit page selection, valid/unresolved/decode-
blocked/changed retained evidence, incomplete custody refusal, safe output,
strictly opt-in `V` behavior, and no dispatcher path. The guarded Windows
runner additionally reruns #18 actual Core retention and request-preparation,
19C2/C1/B2/B1, #17, and #52 teacher-home regressions, Ruff, strict mypy,
Python compilation and exact staged Git diff checks. It does **not** claim
actual installed-wheel/native consumer qualification or handler success.
