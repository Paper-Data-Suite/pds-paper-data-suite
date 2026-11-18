# Suite #19F1 — In-session Core failure review and third-consent deferral

**Parent:** `33c69ea3ae68a74cc3dc47761e68a59327d0225b`

## Scope

After a completed #19E4B Core processing result exists, Teacher Home may display a **read-only in-session follow-up view**. The view reconciles one-based source/page positions and separately identifies dispatch status and Core v2 review state. It never creates an unresolved-only queue or writes a new failure ID.

The sole write operation offered is **F — Defer one verified Core failure**. It is available only for a `CoreReviewResultV1` page whose review state is `recorded` with a bounded Core failure ID. A third, fresh `DEFER` approval is passed through the *existing* `append_deferred_core_resolution(workspace, failure_id, approve=...)`. Core owns loading the canonical failure, verification after consent, append-only creation and receipt verification. A successful `appended` event **does not resolve the failure**. `write_uncertain` or an escaped exception may mean a durable event already exists; the UI stops and explicitly forbids automatic retry.

Read-only manual-review items include unresolved QR, unsupported producer, routing failure, no handler attempt, handler uncertainty and `write_uncertain` failure metadata. No verified failure ID means **no deferral**, regardless of whether a physical page requires manual review. The user can return B, Home M or Quit Q; Help H is available. Core custody is not undone by navigation.

No Suite-owned producer handlers, new Core writer, extra source retention, grading, route resolution, automatic recovery, shell launch or producer deep-link is introduced. Identifiers come only from verified Core review rows; raw QR, student data, file paths and arbitrary exception messages are not printed.

## Deliberate limits

This slice requires a `CoreReviewResultV1` from an attempted Core operation. An **all-unresolved** batch produces `no_dispatchable_pages` and no Core failure result, so it cannot use this deferral path. #19F2 must provide its own nonauthorizing in-session all-unresolved presentation without inventing failure metadata. This slice also does not implement producer module-home fallback. Current action-time admission is exact Win-x64/Python-3.11 ScoreForm+Quillan only; standalone installed Home E2E remains #19G. The app is not certified for real classroom scans.

## Verification

One new Core-recovery module, one focused test module, this document, and a narrowly patched existing `returned_paper_teacher_dispatch_menu.py`. The patch builder is a packaging aid only and is not staged in the repository. The Windows guarded runner gates affected #19/#18 tests, Ruff, strict mypy, Python compilation, exact git index paths and remote-head freshness before commit/push. The bridge remains single-action and default deny.
