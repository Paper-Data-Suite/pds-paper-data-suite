# Suite #19 — 19D2: second teacher consent callback (staged, non-executing)

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `b3cfa39f3ea1fb5dad26da998ac997895ffbb52a`
**Scope:** One new, inert-until-invoked consent callback for #18's existing
`DispatchReviewV1` / `DispatchDecisionV1` seam. **No Home menu wiring and no
Core/producer dispatch in 19D2.**

## Why the callback is staged rather than offered in Home now

The first teacher approval in #19C2 allows **whole-original-file Core custody**.
#19D1 optionally reopens retained bytes and creates typed candidate Core route
requests. Neither a `retained` custody status nor a `ready` prepared batch
establishes current installed-producer qualification. #19A1–A3 are deliberately
non-authorizing diagnostics. A teacher must not see an apparently actionable
second `DISPATCH` button before #19E's independent, action-time admission is
ready to supply an actual constrained eligible module set.

This slice implements and regression-tests the user interaction that **will**
be passed as the `approve` callback to the existing #18
`execute_prepared_paper_batch(...)` *only in a later separately qualified
execution slice*. `make_teacher_dispatch_approver(...)` constructs an inert
callable. No code in the 19D2 slice invokes it from Teacher Home, imports a
producer profile, dispatches a Core route, changes grades, or writes a durable
consent token.

## Action-time contract

`ask_teacher_second_dispatch_consent(review, ...)` consumes an actual #18
`DispatchReviewV1`. It validates bounded selected physical-page coordinates,
nonempty typed Core module counts, digest (64 lowercase SHA-256 hex), challenge
(32 lowercase hex), absolute nontraversing Core workspace, mandatory warnings
that producers may write and Core-retained files already exist, and an eligible
producer subset limited to precisely `scoreform` and `quillan` (the exact
published #18 candidate set). The callback is not a validator of provenance:
these inputs are **claims from its future trusted #18 caller**, not proof.

When no eligible module intersects the actual prepared candidates, the
callback **immediately cancels without prompting**. Otherwise, a fresh
qualified Core active-workspace guard must accept before showing the screen.
The path-free UI reports selected physical pages, candidate route count,
action-time eligible candidate count, unqualified candidate count, and
unrouted selected pages. It discloses that producer-owned writes may occur and
that a successful handler response is not academic publication. It displays
only approved producer IDs and counts, not class/work/student identities,
original paths, source filenames, raw QR payloads or Core route IDs.

The sole affirmative command is a deliberate, bounded `DISPATCH` answer.
Blank, `yes`, `RETAIN`, `B/M/Q`, EOF, interrupts, non-text control characters,
and all other values **cancel**. The active Core workspace is checked **again
immediately after an affirmative response**. If its current status differs,
consent cancels. When valid, the returned
`DispatchDecisionV1("approve", review.plan_digest, review.challenge)` simply
hands the teacher's fresh choice back to #18. It is **not** a reusable
capability, independently generated permission, dispatch receipt, installation
attestation, or pre-granted default. No callback instance or decision is saved.

The future #19E caller must use the actual #18-generated `DispatchReviewV1`,
verify the exact installed producer subset immediately before invocation,
pass that subset as `qualified_modules`, and preserve #18's post-approval
retained-byte reread, per-request pre-call checks, ordered dispatcher and
partial/uncertain result boundaries. No caller may forge a review, reuse a
challenge, supply a blanket eligible set, infer qualification from this
callback's output, or invoke it at Home startup. #19G additionally requires
native installed-wheel end-to-end acceptance and supported dependencies.

## Acceptance

`tests/test_issue19_slice19d2_second_consent.py` exercises 47 focused
parameterized cases: explicit second consent, unique challenge binding,
B/M/Q/EOF and other cancellation, zero eligible producers, only the eligible
subset reported, invalid review/digest/challenge/coordinates/repeated counts,
private metadata redaction, initial and action-time Core workspace refusal,
input exceptions, inert factory construction, and no files or producer imports.

The guarded Windows runner runs this test file and relevant preexisting D1,
C2, #18 producer/retention/dispatch, #52 Teacher Home tests, followed by Ruff,
strict mypy, Python compile, clean-tree/exact-source SHA checks, Git diff-check,
and push-after-qualification only. Local contract-level tests are **not** a
substitute for that Windows repository gate.

## Next: #19E admission + live action seam

A separately reviewed #19E slice must wire the approved current installed
composition into #18's action-time execution boundary and then connect this
callback to the **same** actual dispatch call. Until then, Home still offers
Core retention and a read-only `V` request review, and **no producer handler
is enabled** by this slice.
