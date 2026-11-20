# Suite #19 — Slice 19C1: explicit teacher processing-plan review (no writes)

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `f1da458059edb12aa29c88a0ca7e9c5a94525b1e`
**Scope:** one new pure review module and a bounded change to the #19B2 Core
inbox page-review screen. This is the first **review-only** half of #19C; it
does **not** authorize retention or dispatch.

## Teacher journey

After opening Home item **9**, selecting the read-only **Core inbox** option,
explicitly choosing up to eight eligible source positions and their physical
pages, the review screen now offers:

> **P. Review processing plan (read-only; NO retention)**

Pressing `P` invokes a deliberately new, **nonmutating** review. The previously
shown inbox snapshot was *advisory*: the UI first re-lists the exact same
workspace via #17 `list_selected_inbox`, checks the snapshot and all selected
entry paths, then re-observes the selected source paths using #17
`build_readonly_preflight`. The new observation must exactly match the prior
source observations, including advisory SHA-256 digests and physical page
positions. If either check fails, the review is refused and the teacher
returns to the preview menu without creating a plan or a custody record.

Only after those fresh read-only checks does the UI call
`review_readonly_processing_plan(root, paths, preview, physical_pages)`.
This function invokes the existing **#18 `build_processing_plan`**, never a
replacement plan constructor or inferred QR destination. The #18 contract
requires 1–8 explicit sources, 1–64 physical pages per source, a valid
observed-source digest, bounded selected coordinates, no duplicate pages,
and `PaperProcessingPlanV1.authorized=False`.

The renderer displays bounded path-free counts, selected *physical* page
numbers by one-based source position, unverified QR-candidate versus unresolved
counts and a plain **whole-file custody disclosure**:

- Later Core retention would preserve the **entire original scanned file** for
  each selected source, **including unselected pages**. One selected page does
  not authorize a page-only extraction or partial-file custody.
- Original source files would remain unchanged. Core custody, once committed,
  is durable and cannot be undone simply by navigating Back.
- Separate teacher consent would be required before Core retention; an
  additional fresh review is required before producer dispatch.

The review ends with B/M/Q, never an **approve**, **yes**, **retain**, or
**process** action. `P` may be selected again; **each press** repeats fresh
inbox and source observations. EOF, invalid input and interrupted review never
count as consent. No state is saved across menu navigation.

## Security and repository boundaries

- UI startup, Help, and the B2 physical selection do **not** invoke #18's
  plan builder. Only an explicit `P` choice opens the lazy review module.
- The UI performs **no** Core source retention, producer module discovery,
  handler call, issue #18 dispatch, notes/grades write, software installation,
  or source mutation. The temporary plan is not emitted or persisted as a
  credential. Its `authorized` field is always `False`.
- Source paths, workspace paths, file names, QR strings, student IDs,
  exceptions and raw module-owned results are not printed in the review.
- B2 snapshot rechecking and source-observation equality remain advisory;
  they are **not** atomic source locking or a trust claim. #18's subsequent
  retention action must independently revalidate actual bytes and present a
  fresh `RetentionReviewV1` digest/challenge decision.
- **19A1–A3** exact wheel/native/profile checks remain nonauthorizing and are
  not invoked. The original #17 inbox, #18 retention/dispatch and #49
  application/doctor/launch implementations are not modified.
- A source-only patch helper modifies only the final `B/M/Q` review loop in
  `returned_paper_teacher_inbox.py`; it is **not** staged into the repository.

## Scoped acceptance

`tests/test_issue19_slice19c1_teacher_plan.py` verifies exact #18 plan
formation and whole-file count disclosure, selection order, advisory-digest
refusal, invalid source/page/digest rejection, redaction, no writes, `P`
requires fresh inbox and source observation, changed snapshot/source fail
closed, no plan without `P`, safe B/M/Q/EOF behavior, and no custody/dispatch
imports. B2, B1, #52 Teacher Home and #17 inbox/preview regressions remain in
the guarded Windows test matrix, along with Ruff, strict mypy, Python compile
and Git exact-file/whitespace checks.

## Next slice: 19C2

Implement the actual **first explicit teacher consent and Core retention**
using the existing #18 `authorize_and_retain_sources` with a fresh transient
`RetentionReviewV1` and digest/challenge-bound `RetentionDecisionV1`. Refuse
stale/missing sources and any invalid, canceled, EOF or interrupted response
before **any** Core writer is called. Treat an uncertain Core receipt as
possible durable custody, never auto-retry it. Surface `cancelled`, `rejected`,
`retained`, `partial`, and `uncertain` honestly. **No producer dispatch** until
separately qualified action-time admission and second authorization.
