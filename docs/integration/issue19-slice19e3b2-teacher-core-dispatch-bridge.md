# Suite #19E3B2 — one-action retained-paper Core execution bridge

**Source parent:** `48c42fc27d5e0e3cf9277beb81ba989e6d2d5bbf`
**Scope:** explicit post-first-consent action; no Teacher Home menu binding yet.

## Implemented contract

`run_teacher_retained_paper_dispatch(retention, wheelhouse, *, input_stream,
output, show_header)` accepts a genuine, complete, approved #18 Core-retention
result. It **does not** create, alter, replace, or repeat retained source custody.
The sole production path is:

1. Execute the built-in E3B1 installed action-time admission inspection. Only
   the exact supported Windows x64 Python 3.11 Core 0.6.6 / ScoreForm 0.13.0 /
   Quillan 0.10.6 pair qualifies, including the explicit wheelhouse's pinned
   artifacts, current installed-file payload audit, `pip check`, launchers,
   native dependencies and Core routing profile discovery. A past acceptance
   log, an injected status or stored result cannot be substituted.
2. Verify that the active Core workspace matches the already retained result.
   Reprepare real typed Core requests from **retained bytes** using #18's
   `prepare_retained_pds2_requests`, and reject any difference from the first
   Core custody receipts. Unresolved physical pages remain unresolved.
3. Call **only** #18's `execute_with_core_review` with the exact fresh eligible
   pair. #18 verifies retained bytes, constructs an actual new digest/challenge
   review, and invokes the #19D2 separate `DISPATCH` teacher decision.
4. **After** a positive second consent but **before** returning approval to
   #18, repeat the E3B1 installed admission and active Core-workspace check.
   If either changed, cancel #18's pending approval, with no handlers run.
5. #18 rechecks retained bytes before registry construction and each page,
   dispatches through Core's existing registry and dispatcher **once per
   selected eligible physical page**, and records distinct Core v2 failure
   occurrences where supportable. A failure writer's uncertain result is
   never retried. This bridge does not call Core routing directly, duplicate
   Core handling, or publish a grade.

An affirmative E3B1 decision is used **inside this single action only**. The
bridge stores no admission result, eligibility token, route, payload, student
identity, or handler output. No hidden wheelhouse, reusable consent, daemon,
automatic replay, or shared synthetic fixture is used for teacher data.

## Honest teacher result

`TeacherDispatchActionResultV1` and `render_teacher_dispatch_action` provide
an aggregated, path-free physical-page report. Possible statuses:
`admission_refused`, `workspace_refused`, `preparation_refused`,
`preparation_uncertain`, `no_dispatchable_pages`, `cancelled`,
`admission_changed`, `completed`, `partial`, `blocked`, `uncertain`.

The Core execution result, if available, is authoritative for attempted page
counts and per-page states (`handler_returned`, `unresolved_qr`,
`module_unqualified`, `uncertain`, `not_attempted` etc.). A missing execution
receipt after an exception is **uncertain**, never proof of no writes. The
bridge never claims that a handler return is completed evidence capture or
that ScoreForm scoring was published as a grade. The result cannot claim
`automatic_retry_allowed` or `grades_published`.

## Remaining boundaries

This is a **callable action bridge**, not a new Teacher Home menu item or an
advertised live pilot. The current first-retention UI does not persist its
transient `AuthorizedRetentionResultV1` for later use; the next explicit UX
slice must attach the bridge **within that same first-retention action**,
provide the teacher's wheelhouse selection, and retain current `B/M/Q` UI
semantics. No Home startup, preview, or help path should inspect native
producer profiles.

The E3B1 policy remains **all-or-nothing** for ScoreForm/Quillan; independent
single-producer admission is not yet supported. Windows x64 / Python 3.11 is
intentionally the only eligible live composition. This code does not attest
loaded native DLL signatures or remove file-race risks beyond the existing
Core and Suite checks. Real teacher-owned paper, physical scanners, the full
installed Teacher Home workflow, partial-producer behavior and Linux/other
Python runtime qualification all require subsequent explicit review.

## Acceptance

The guarded E3B2 runner checks clean exact parent and source archive members,
then runs E3B2 integration tests plus prior D2, E3B1, #18 Core dispatch/review,
Teacher Home regressions, Ruff, strict mypy, Python compile, staged-file
hygiene and remote concurrency. It commits only the new action module, tests,
and this document after full success. This source qualification does **not**
process real paper or change live teacher data. Do not claim Windows
qualification or commit/push before the user's runner reports its markers.
