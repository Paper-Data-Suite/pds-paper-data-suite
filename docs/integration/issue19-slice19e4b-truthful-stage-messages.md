# Suite #19E4B — Truthful synchronous processing-stage messages

**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `916d5f8560983f3ee249940f9e505de938bee18e`

## Scope

This slice adds **non-authorizing text only** to the existing E3B2 action invoked by the Teacher Home V/D menu. The first teacher consent and Core whole-source retention are already complete when the action begins. The second consent remains a distinct, fresh Core challenge. Nothing new handles, retains, records, retries or publishes student work.

The UI reports verified checkpoints, in order: first-retention receipt reported; installed-producer eligibility and active workspace checked; Core-retained requests actually prepared; second teacher approval pending; upon a positive teacher response and a successful *repeat* installed-admission/workspace check, the batch is being handed to synchronous Core processing; finally, an available Core result is rendered. Each earlier refusal exits before later-stage claims.

## Honest limitation

A handoff message is **not** a claim that a handler started or finished. Core rechecks retained bytes after the callback and before each page attempt. The existing synchronous `execute_with_core_review` contract has no live per-page observer: the UI says so rather than fabricating percent progress, an ETA, cancellation during execution, or rollback. The final immutable `CoreReviewResultV1` and E4A renderer remain the only page-level outcome evidence. After an escaped exception, effects may already have occurred: no automatic replay is permitted. The first-retained originals are never retained again by this action.

## Tests and qualification

`tests/test_issue19_slice19e4b_stage_messages.py` exercises real synthetic Core-retained batches with the existing E3B2 fixture: affirmative and cancelled second consent, unsupported admission, no routable pages, admission change during second consent, preparation exception, and uncertain Core escape. The Windows runner additionally executes earlier Core, Teacher Home and results regressions, Ruff, strict mypy, Python compilation and exact Git checks.

Do not treat a passing source test as an installed Windows/Linux Teacher Home end-to-end qualification. Issue #19F recovery and #19G installed journeys remain outstanding.
