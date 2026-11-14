# Suite #18 — Slice 5: Core v2 failure and deferral handoff

**Status:** source candidate, pending exact Windows Core 0.6.6 and CI qualification.

## Boundary

Slice 1 provides nonauthorizing source/page contracts, Slice 2 performs fresh
teacher-approved Core retention, Slice 3 reopens retained bytes and prepares
actual Core `RouteDispatchRequest` objects, and Slice 4 runs guarded page-by-page
Core dispatch with producer execution disabled by default.

This slice adds a **small wrapper**, `execute_with_core_review`, which calls
`execute_prepared_paper_batch` **once**. The injected one-page dispatch seam
captures actual `RouteDispatchFailure` values transiently. It neither imports
unapproved producer modules nor alters the existing Slice 4 report, routes,
handler semantics, approval sequence or default-deny module gate.

Only after the Slice 4 execution has fresh approval does the wrapper create
Core **v2 immutable failure occurrences** for (a) actual typed Core failures,
(b) an attempted page whose handler escaped unexpectedly and whose effects are
uncertain, or (c) an unresolved selected QR page in an otherwise approved
batch. Core's helper supplies the category/stage mapping of actual
`RouteDispatchFailure` values. Suite reconstructs the Core v2 record with
**generic, single-line safe messages** rather than persisting `str(error)`,
which might contain a producer's sensitive exception text.

### Provenance, persistence and truthful receipt

Core owns `RoutingFailureMetadata`, `routing_failure_metadata_from_dispatch_failure`,
`routing_failure_metadata_path`, `write_routing_failure_metadata`, and
`load_routing_failure_metadata`. Suite retains exact Core `source_scan_id`,
source SHA-256, workspace-relative retained path, one-based physical page
number, and **only an actual typed** PDS2 locator where one exists. For
unresolved QR, the locator, target and raw decoded payload remain `null`.

After a successful Core writer return, Suite verifies both the canonical
writer path and a strict Core loader round-trip **before** reporting `recorded`
and exposing `failure_id`. If a write, readback or receipt verification
fails, it reports `write_uncertain` and **does not** retry the writer. Existing
Core review ancestors are checked for symlinks/reparse redirection before
write/readback, but this is not a handle-anchored guarantee against races. A Core
exclusive write might already be durable despite an exception. The execution
report remains unchanged; it is **not** overwritten by a review-write status.

Review output is one immutable `ReviewPageV1` per physical page, preserving
source/page order and the original `PageProcessingStatus`, plus the optional
verified failure ID, category, and always-false `automatic_retry_allowed`.
`CoreReviewResultV1` guarantees complete reconciliation to the original
`OrderedDispatchResultV1`. Default `qualified_modules=frozenset()` continues
to **disable every producer**.

### Append-only deferred resolution

`append_deferred_core_resolution(workspace, failure_id, approve=...)` reads the
**canonical** Core v2 failure, asks for a fresh explicit challenge-bound
`DeferDecisionV1`, re-reads the same failure, then calls
`create_scan_resolution_metadata(..., resolution_status="deferred",
resolution_action="deferred")` and `write_scan_resolution_metadata`.
The result is verified through `load_scan_resolution_metadata`. A cancellation
makes no new record; ambiguous post-write outcomes are `write_uncertain`, not
a second append. This narrow method does **not** mark evidence filed, invent a
corrected route, resolve a producer-specific problem, or authorize rescan,
regrading or replay. Core v2 retains the original immutable failure and any
previous resolution events.

## Essential refusals and limitations

- No automatically generated Core v2 review events on cancelled/unapproved
  processing, stale/blocked retained input, unselected pages or module names
  denied by the policy gate without an actual Core attempt.
- If **every** selected page is unresolved, Slice 4 has no dispatchable
  requests and does not ask for approval; therefore this wrapper also makes
  **no review writes**. #19's explicitly authorized unresolved-only review
  workflow remains necessary before claiming complete teacher-day coverage.
- The original Core failure message from an actual exception is **never**
  persisted by Suite. Original opaque `module_result`, raw QR text,
  `module_details`, grade bodies and teacher-facing absolute paths are not
  copied to Suite durable data or review results.
- The Core v2 writer is exclusive and append-only; this slice does not add
  a mutable “latest” resolution marker, exactly-once journal, safe repeated
  dispatch authorization, global rollback, an automatic failure retry queue or
  a generic producer success receipt. A repeated explicit call can re-enter a
  producer; **do not** wire a retry button or automatically call it on old
  retained requests. #19 and producer-owned idempotency/reconciliation must
  resolve that workflow before live processing is advertised.
- A running actor with filesystem mutation rights and a concurrent attacker
  replacing source paths is not made safe by the hash-bound checks. Do not
  claim handle-level sandboxing or live classroom security from this slice.
- Core #238–#244 private Notes/storage/roster work and Suite #49's historical
  release compatibility and trust manifest are **untouched**. Current Core
  0.6.6 source qualification is distinct from Suite's pinned 0.6.3 CI image.
- Fully co-installed Concord + Vitrine paper remains gated by [Concord #170]
  (https://github.com/Paper-Data-Suite/pds-concord/issues/170). Portia #67
  and Meridian have no newly claimed installed routing capability.

## Qualification matrix / future handoff

1. Synthetic Core 0.6.6 v2 failure records: route not found, missing QR,
   unsupported actual profile, module handler failure and unexpected handler
   interruption; successful pages are not reported as failures.
2. Success–failure–success preserves all page outcomes and original Core
   custody. Verify copied source identity and strict v2 readback.
3. Core writer failure before write, after an actual durable write, duplicate
   failure ID collision, wrong returned path or readback error: report
   `write_uncertain` without retriggering a producer or overwriting prior
   records.
4. Cancellation, default producer deny, stale retained bytes, selected vs.
   unselected pages: no unauthorized review mutations.
5. Explicit deferred review: canonical linked v2 failure, fresh approval,
   append-only event, cancelled/no-write, malformed ID and failure to append.
6. Windows Core 0.6.6 installed-wheel focused pytest, Ruff, strict mypy and
   source-only Git integrity. Broad CI and exact official producer wheel
   acceptance remain final Slice 6 gates, not claims of this source slice.

**Next:** qualify genuine co-installable ScoreForm + Quillan producer wheels and
complete the #19 handoff/retained-source operational review; do not silently
update the #49 manifest or relax Concord's PDFium constraints.
