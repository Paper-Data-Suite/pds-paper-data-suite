# Suite #18 Slice 2 — Explicit review and Core retain-first boundary

**Status:** source candidate for qualification, not a published installed-wheel or live-classroom processing workflow.

**Base:** `e5f2209b69cb27f6b53b7408338b8776bbab242c` on `18-core-retain-first-mixed-paper-dispatch`.

## Call contract

`authorize_and_retain_sources(plan, *, approve, observe=..., retain=...)` is the first deliberate mutation seam of #18. The incoming `PaperProcessingPlanV1` is an **unauthorized** immutable selection from Slice 1, joined to #17 preview observations. Passing it never grants custody rights. An explicit `approve` callback must return `RetentionDecisionV1('approve', review.plan_digest, review.challenge)` for the *current* `RetentionReviewV1`. The review carries the explicitly selected workspace, source positions, physical page numbers, whole-file retention disclosure, digest and fresh unpredictable challenge; its `repr` hides paths. A cancel, exception, wrong digest, old challenge or nonmatching object prevents new Core writes.

The callback is a trusted **local teacher interaction seam**, **not** OS-user authentication, a persisted permission, an externally signed token, or a reusable authorization credential. Suite #19 owns the teacher's actual interactive approval screen and must show the exact workspace and whole-file retention implication. Do not make a background task or a CLI default auto-approve.

Before seeking consent, Slice 2 checks every selected source's existing workspace, path ancestry (including Windows reparse/junction), regular-file type, suffix, bounded bytes, SHA-256, and fresh physical-page observations from #17's public `observe_selected_sources`. Registration status is only a diagnostic; its absence on re-observation does not authorize or forbid a matching decoded candidate. The same checks are repeated **after approval** and **immediately before each Core writer**. No production profile or handler is loaded by this module.

After review approval, the default writer calls exactly **`pds_core.scan_retention.retain_source_scan(workspace_root, source_path)`** once for each selected **source event**, not once for each selected page. The selected external file is never intentionally modified. The returned **actual** `RetainedSourceScan` is checked for Core type, original filename, expected SHA, workspace-relative `scans/source/<date>/<file>` path and retained-byte SHA before it may be represented as verified custody. The newly retained bytes are **not yet decoded for dispatch in Slice 2**: Slice 3 owns that step.

## Status truthfulness and non-atomicity

- **`cancelled`**: no Core retain call. The plan remains unauthorized even if a callback returns a correct digest with a `cancel` decision.
- **`rejected`**: a selected source failed freshness/safety checks before any Core copy, or a newly approved source became stale before its own copy. Earlier approved retained sources, if any, remain and change the aggregate to `partial`.
- **`retained`**: every explicitly selected source event has a validated **Core receipt** and retained bytes whose SHA matches the plan's source fingerprint. Selected pages are `retained_only`; unselected physical pages are `not_selected`. No module dispatch has occurred.
- **`partial`**: earlier selected files were retained, but a later source was rejected before its copy. Preserve earlier receipts; no rollback or silent deletion.
- **`uncertain`**: Core writer or post-copy verification raised after custody may have begun, even if there is no verified receipt. Preserve any existing Core bytes for investigation and **stop**. No blind retry or promise of absence of effects.

A successful Core writer is source custody, **not** a ScoreForm grade, Quillan response, Concord returned page, Vitrine reflection or Portia fact. No v2 failure/resolution is recorded yet; Slice 5 will use Core public metadata. This slice never opens `ModuleRegistry`, calls `dispatch_routes`, creates a student link or emits a producer-owned record. The `PaperProcessingReportV1` reuses Slice 1's complete per-source/per-page status reconciliation, preserving all selected and unselected page positions.

## Remaining security and deployment qualification

Core v0.6.6's published `retain_source_scan` accepts a filesystem **path**, not a previously opened/locked source file descriptor. Reopening after a source check leaves a possible active-adversary **TOCTOU** window on filesystems that allow concurrent replacement. Digest validation detects a mismatch and stops subsequent work, but cannot make a previously executed Core copy disappear or prove that no foreign bytes were briefly written. A strict source/retained-byte/content match therefore remains a **dispatch prerequisite**, not unconditional replay permission. Do not claim malicious concurrent replacement, permission isolation, long-path native coverage or real teacher identity has been solved by this shim. Report a narrower Core intake-API handoff if live security requirements demand handle-anchored custody.

The published Suite #49 release manifest remains pinned to historical Core 0.6.3. This Slice 2 does not change manifest, package pins, authorized release trust, `pds papers preview`, inbox listing, Teacher Home, Core Notes (#238–#244) or the producer contracts. It must be qualified against the actual installed Core v0.6.6 custody writer **separately** from historical green Suite CI. Concord #170 remains the separate full Concord + Vitrine[paper] PDFium co-install blocker.

## Focused evidence and Slice 3 handoff

Synthetic tests deliberately exercise Core `retain_source_scan` with a disposable workspace, affirmative/cancelled/stale consent, original-byte preservation, retained source identity, prior/mid-review file changes, symlink rejection, partial source retention, post-copy corrupted bytes and uncertain writer effects. The `observe` injection creates deterministic #17-style page observations without optional native PDF/QR dependencies; native decoding and installed mixed-producer scope remain separately gated.

**Slice 3 receives:** the immutable plan, authorized-result status, and actual Core `RetainedSourceScan` objects only for fully verified sources. It must reopen and decode **retained bytes**, validate full Core PDS2 locators and exact page observations, and refuse dispatch on a mismatch. It may **not** rely on candidate module IDs, original external sources, a display digest, or a cached preview as Core dispatch authority.
