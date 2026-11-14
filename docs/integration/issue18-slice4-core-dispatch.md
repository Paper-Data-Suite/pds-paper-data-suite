# Suite #18 Slice 4 — Fresh, Ordered Core Dispatch (source-contract gate)

**Branch:** `18-core-retain-first-mixed-paper-dispatch`
**Base:** `c9be7933387a1550f688267979dc637fab620adc`
**Core runtime API:** published `pds-core==0.6.6`; do not reinterpret the
historical Suite #49 `release_compatibility_v1.json` (still Core 0.6.3) as
qualification of these newer APIs or of producer co-installation.

## Scope and authority

New additive module `paper_data_suite.returned_paper_ordered_dispatch` provides
`execute_prepared_paper_batch(...)`, typed transient review/decision/report
records and `count_ordered_dispatch_groups(...)`.

1. Accept **only** a completed Slice 3 `PreparedDispatchBatchV1`, produced from
   previously teacher-approved and Core-retained source bytes. Never construct
   route locators from #17 `PagePreview` candidate module IDs.
2. Reinspect every selected **Core-retained file**, all its physical pages,
   original QR-observation class, full PDS2 locator and Core provenance before
   the execution review, again after the teacher confirms, and immediately
   before **each** handler invocation. A changed retained file or page refuses
   the next handler; completed prior effects remain independent.
3. Present an ephemeral `DispatchReviewV1` with explicit workspace, all
   selected source/page positions, requested module counts, admitted modules,
   a digest and random challenge. Require a **fresh** matching
   `DispatchDecisionV1("approve", digest, challenge)` prior to registry loading
   or producer execution. Callback is a trusted in-process teacher interaction
   seam, **not verified OS identity, a persisted authorization record or a
   replay-safe capability**.
4. Build an actual strict Core `ModuleRegistry` (the default uses
   `build_module_registry(discover_installed=True)`). Never construct profiles
   from QR strings, choose duplicate entry points, skip registration validation,
   bypass Core dispatch, or treat metadata diagnostics as trusted providers.
   Injected factory and dispatcher are intended for synthetic tests only.
5. Invoke public Core `dispatch_routes(workspace, registry, (one_request,))`
   individually in physical source/page order. Single-page calls preserve
   precise in-flight accounting if a module raises unexpectedly, while Core
   still owns strict profile, route-registration, contract and handler checks.
   The Core request source is always the approved `RetainedSourceScan`.
6. Never persist/serialize `RouteDispatchSuccess.module_result`, raw QR,
   exception strings, registration `human_fallback`, student IDs, or module
   details. `handler_returned` means **only** that the producer handler
   returned; it is not a generic scoring, review, or publication receipt.

## Explicit qualification policy

- `qualified_modules` defaults to **empty**. Consequently even an installed
  Core profile **cannot execute** without an explicit trusted in-process
  admission **and** a matching fresh teacher approval.
- Slice 4 restricts candidate admission to `scoreform` and `quillan` for
  *synthetic Core-contract qualification only*. Passing a list of names is
  **not** proof of installed wheel identity, correct producer release, runtime
  co-installation, classroom authorization or live paper capability.
- `concord`, `vitrine`, `portia`, `meridian`, unrecognized module IDs and any
  arbitrary names cannot be admitted by this source gate. They produce the
  bounded `module_unqualified` outcome without handler execution. Source
  processing may still be deliberately retained and unresolved.
- Slice 6 must establish authenticated official-wheel/runtime/version evidence
  before binding a trusted caller to a real eligible subset. Concord/Vitrine
  full paper composition remains blocked on Concord #170; Portia #67 and
  future Meridian integrations are independent producer responsibilities.

## Outcome and interruption rules

| Condition | Page result | Batch result / behavior |
| --- | --- | --- |
| Teacher cancels/invalid approval | `not_attempted` | `cancelled`; zero registry/handler calls |
| Retained data/QR drift before execution | `not_attempted` | `blocked`; no handler call |
| Core installed provider discovery/registry failure | `not_attempted` | `blocked`; no handler call |
| Module not explicitly admitted in qualified subset | `module_unqualified` | Other eligible pages continue; not dispatched |
| Missing/invalid registration or expected Core dispatch error | `dispatch_failed` | Other pages continue; Core's safe category is retained |
| Handler raises `ModuleRouteHandlingError` | `uncertain` | Other pages may continue; **no replay of this page** |
| Handler returns Core `RouteDispatchSuccess` | `handler_returned` | No generic grade/evidence/publication claim |
| Dispatcher escapes unexpectedly or violates Core result identity | `uncertain` | Stop batch, remaining eligible pages `not_attempted` |
| Retained data changes after an earlier handler returned | Prior outcomes preserved; remaining `not_attempted` | Batch `uncertain`; no hidden replay |
| Valid selected page has unreadable/missing/ambiguous QR | `unresolved_qr` | Never dispatched; counted in group reconciliation |

Source-level Core retention status/receipt remains Core-owned and intact;
physical page outcomes are a transient Suite projection. They are **not** a
transaction, durable success journal or replacement for immutable Core v2
failure/resolution records. Slice 5 owns review persistence, explicit
reconciliation/retry policy and #19 handoff references. A crash, `SystemExit`,
process termination or a handler that writes then raises may leave effects
without a Suite receipt. **No exactly-once or safe blind rerun guarantee.**

## Limits and threats

- Bounded by Slice 1–3 limits: maximum 8 source files, 64 physical pages each,
  512 selected pages, 24 MiB per file, and the existing native decoder bounds.
- Refuse symlink/reparse paths using existing validated Core-retained path
  checks; detect changed SHA/payload/page count before the next handler.
- Path/hash checks are not handle-anchored concurrency protection. A malicious
  same-account process can race between a check and Core's handler file open.
  This slice is **not** qualified for hostile/shared filesystem security.
- The execution service has no new menu command, background task, automatic
  provider admission, Core source writer, failure writer or database.
- All synthetic fixture data must remain invented, with no real student
  information in logs, repository fixtures, artifacts or screenshots.

## Qualification classification and handoff

Local synthetic tests exercise `ModuleProfile`, `ModuleRegistry`, strict Core
request/outcome shapes, a Core route-registration writer/dispatcher path, and
failure isolation through test-only Core-compatible interfaces. This is
**source-contract evidence**, not native official-wheel or producer-handler
acceptance. The guarded Windows runner must qualify against actual installed
`pds-core==0.6.6` with focused pytest, Ruff and strict mypy. End-to-end
ScoreForm/Quillan **official-wheel** execution with verified runtime versions,
consequences, and isolated test data belongs to Slice 6. Core #238–#244,
private Notes, roster management, Suite #49 trust machinery and the legacy
`pds papers preview` / `pds papers inbox` commands remain untouched.
