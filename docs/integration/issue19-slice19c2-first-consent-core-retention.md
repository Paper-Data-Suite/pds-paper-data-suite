# Suite #19 — Slice 19C2: first teacher consent and exact Core source retention

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `38c5ffe5233685f24957b8e31630e118ab11a2a3`
**Scope:** first teacher authorization of **whole-original-source retention** via
#18's existing `authorize_and_retain_sources`; no producer dispatch.

## Teacher flow and consent

Teacher Home **9 → 2. Core inbox** still requires explicit absolute workspace,
read-only inventory of at most 64 entries, 1–8 selected eligible sources, and
individual physical-page choices. After the B2 selection review:

1. Press **P** to review the existing #18 `PaperProcessingPlanV1` in plain,
   path-redacted terms. It explains that if even one page is selected for
   potential dispatch, Core custody retains **every physical page of the
   original source file**. This is nonmutating and grants no permission.
2. Only **after that successful P review** does **R — Retain whole selected
   files** become available. Pressing `R` repeats the #17 inbox snapshot and
   selected-entry status/path checks, then re-observes all chosen source files.
   The observations, including advisory SHA-256, must match the original
   physical preview. The UI then calls the existing #18
   `build_processing_plan` again to construct a **new, nonauthorizing plan**.
   A changed directory, missing source, invalid page mapping, invalid format,
   or changed QR observation refuses the attempt before any Core writer.
3. `run_teacher_first_retention` checks that the explicit workspace is **the
   currently Core-resolved active workspace** through Suite's qualified
   `workspace_setup.observe_workspace()` and is a writable existing directory.
   No saved setting is changed; no CWD/default path is substituted.
4. The UI invokes #18's `authorize_and_retain_sources(plan, approve=...)`
   **once**. #18 independently revalidates the selected source bytes and
   physical QR observations before it calls the approval callback. A stale
   input may cause `rejected` without any consent prompt or write.
5. The actual first-consent callback receives an ephemeral
   `RetentionReviewV1` containing #18's fresh `plan_digest` and `challenge`.
   The teacher sees exact selected whole-file and physical-page counts,
   unselected pages included, the irreversible nature of Core custody, and
   the restriction that no producer processing is approved. Only typing the
   exact word **RETAIN** (case-insensitive) produces
   `RetentionDecisionV1("approve", review.plan_digest, review.challenge)`.
   `CANCEL`, blank, unsupported answers, B/M/Q, EOF, interrupt, or invalid
   input produce an explicit cancellation instead. The active workspace is
   checked **again** immediately before issuing approval.
6. #18 verifies digest/challenge/approval and revalidates each original source
   at the actual writer boundary. Core owns the only
   `pds_core.scan_retention.retain_source_scan` call and the durable receipt.
   The original scanned file is not modified. This is not a replacement Core
   retention implementation or a second metadata-derived permission service.
7. The UI reports the authentic `cancelled`, `rejected`, `retained`,
   `partial`, or `uncertain` status and counts verified whole-file receipts
   and uncertain source states. The UI never prints private paths, student
   identifiers, raw QR strings, Core file IDs, handlers or exception text.

**No automatic retry.** After any `R` request the controller returns to the
parent menu rather than allowing a second call from the same selection.
`partial` means some sources already have verified durable custody; `uncertain`
means Core may have written without returning a trustworthy receipt. Both
require manual reconciliation before any new attempt. No B/M/Q navigation can
undo a completed Core custody action. If an unexpected exception escapes the
whole #18 call, the UI conservatively reports that custody **may** already
exist; it never promises rollback or a safe retry.

## Ownership and non-goals

- Teacher Home startup, item 9 entry, B2 file selection, C1 `P` review, help,
  and ordinary application launching remain entirely nonmutating. The
  new retention module is lazily imported **only when R is requested after P**.
- `ReadonlyPhysicalSelectionV1`, the inbox snapshot, preview report, and C1
  plan remain **non-authorizing**. Only #18's *fresh* digest/challenge
  confirmation can authorize this one explicit Core custody operation.
- A1/A2/A3 official-wheel/native/profile diagnostic objects are **not**
  permission to process papers. No producer profile factory, Core routing
  registry, handler, grading operation, or module-owned student-record writer
  is invoked by this slice. The #18 ordered dispatcher and its
  `qualified_modules=frozenset()` default-deny boundary are unchanged.
- Core's public qualified workspace-selection API is authoritative: the
  teacher's explicitly typed path does not silently make that workspace
  active. If Core status is unavailable or differs, C2 refuses retention.
- A selected `P` and `R` can race with external file changes. The repeated
  inbox/source observations and #18's own pre/post-consent byte comparisons
  reduce risk but do **not** create an atomic filesystem transaction.
- No live student materials are included in tests. Native Core retention
  tests use disposable, synthetic `%PDF` files in temporary workspaces.

## Scoped qualification

`tests/test_issue19_slice19c2_teacher_retention.py` covers cancellation and
B/M/Q/EOF refusal, exact fresh digest/challenge, active Core-workspace mismatch
and mid-consent change, no retention before P, current inbox/source checks
before R, one genuine Core-retain call and unchanged source, stale-source
rejection, partial/uncertain outcomes, safe-redacted renderer, no automatic
retry, and no producer dispatch. The guarded Windows runner also qualifies
C1/B2/B1, #52 Teacher Home, #17 inbox/preflight, and #18 planning/retention
regressions, followed by Ruff, strict mypy, compilation, exact staged paths,
and `git diff --cached --check` before commit/push.

## Next slice

#19D: after verified Core retention, re-read the retained bytes through
`prepare_retained_pds2_requests`, present a **second distinct** teacher review
for dispatchable/unresolved pages and freshly qualify the active installed
producer composition. A C2 Core custody result is **not** dispatcher consent,
and no fresh Core retention is implied when preparing already-retained pages.
