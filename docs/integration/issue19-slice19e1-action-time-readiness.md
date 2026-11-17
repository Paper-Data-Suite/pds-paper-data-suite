# Suite #19 — Slice 19E1: current-environment readiness, never admission

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `f8daa55786b92aae47c59de705bd693850270d5e`
**Scope:** A standalone, explicitly invoked diagnostic in a disposable isolated
installed-wheel environment. No existing modules, menus, or dispatch handlers
are modified. **No live producer write is enabled by this slice.**

## Contract

`inspect_paper_action_time_readiness(absolute_wheelhouse)` returns a frozen
`PaperActionTimeReadinessV1`. It cannot contain an authorized producer or a
nonempty `qualified_modules`. It is not a transferable credential, attestation,
or live authorization decision. It is **not called** by Teacher Home on startup,
Help, Core retention, or existing read-only previews.

The diagnostic operates only when deliberately invoked in an isolated
qualification environment and checks, in order:

1. Existing #19A1 `inspect_paper_admission` over #49 current-package metadata.
   It requires the exact Core 0.6.6 / ScoreForm 0.13.0 / Quillan 0.10.6
   candidates on supported Windows/Linux Python 3.11. Every mismatch stops.
2. Existing #49 `collect_local_launch_inventory`, requiring exactly one
   currently resolved, eligible ScoreForm and Quillan launcher. A launchable
   menu is *not* a verified paper processing integration.
3. `sys.executable -m pip check` for the **same active interpreter**. This is
   read-only, offline, bounded to 30 seconds, and suppresses raw output; it
   does not install or repair anything, and failures stop subsequent probing.
4. Existing #19A3 `inspect_installed_paper_runtime(wheelhouse)`, which owns the
   already scoped #19A2 pinned wheel/installed-payload audit, known native
   dependency version/API checks and explicit Core module-profile observation.
   As with A3, source/wheel byte matches cannot attest executed native bytes.

A result is one of:

| Result | Meaning |
| --- | --- |
| `candidate_unqualified` | Exact platform/version/metadata candidates unavailable |
| `launcher_unqualified` | One or both #49 launcher checks failed |
| `dependencies_unqualified` | Offline `pip check` failed or was unavailable |
| `runtime_unqualified` | A3 evidence was incomplete, incompatible, or unavailable |
| `diagnostic_match_not_admitted` | All diagnostic prerequisites matched; **still no permission** |

Every result, including a complete diagnostic match, has
`producer_dispatch_authorized=False`, `qualified_modules=frozenset()`, and
`processing_status="preview_only"`. Every per-producer row explicitly denies
`dispatch_eligible`. The path-free renderer shows only approved producer IDs,
readiness states, and the limitations. It does not print wheelhouse paths,
native exceptions, pip output, student identities, QR/route strings, or handler
results.

## Important limitations

- The wheelhouse must come from independently authenticated **official**
  release assets. The exact wheel SHA-256 and controlled install procedure are
  separate acceptance evidence, not supplied by this read-only model.
- Source and on-disk wheel comparisons do not prove loaded native-code provenance
  or freedom from an actively racing filesystem adversary. Producer profile
  imports are restricted to #19A3's explicit isolated diagnostic, never a
  Teacher Home startup side effect.
- `pip check` tests installed metadata/dependencies, not native functionality or
  correctness of producer effects. A3 symbol imports do not replace actual
  two-page installed acceptance. No arbitrary injected callback, metadata
  result, or typed diagnostic object can elevate this module into permission.
- This slice does **not** call #18 `execute_with_core_review`, invent a
  `qualified_modules` set, touch Core custody, launch a producer, score a form,
  grade a student, save an approval, or create a Suite processing journal.
- Do not re-label `diagnostic_match_not_admitted` as eligible. Without a
  separately reviewed live admission policy and installed synthetic acceptance,
  the teacher workflow remains **retention + read-only preview only**.

## Qualification and next work

New `tests/test_issue19_slice19e1_action_time_readiness.py` verifies all five
states, early gates/no later imports, exact Core/producer subset, duplicate or
unusable launchers, false/exceptional `pip check`, A3 diagnostic rejection,
privacy and immutable default deny. The guarded Windows runner runs this test
file with A1/A2/A3, D2/D1/C2, #18 and #52 relevant regression tests, Ruff,
strict mypy, Python compilation, and exact-file Git staging before committing.

**Next 19E2:** Define the separately reviewed **installed acceptance evidence
and execution policy** with precise control of authentic official artifacts,
actual installed Suite wheel, native two-page synthetic producer effects, current
runtime identity and time-of-action revalidation. Only when this strong evidence
is complete may a later slice safely pass a nonempty independently qualified
producer subset to existing #18's ordered Core dispatcher, with the distinct
D2 teacher consent callback and no replay on uncertainty. **No fallback to
metadata-only permission is acceptable.**
