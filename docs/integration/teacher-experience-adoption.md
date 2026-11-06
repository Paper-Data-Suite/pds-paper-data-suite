# Suite teacher-experience v0.2 — adoption and qualification

**Owner:** Suite #51, child of [#15](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/15). **Status:** The [accepted draft v0.2 design](../design/teacher-experience-design-specification.md) is adopted as Suite's **implementation target**, not as proof of implemented, installed, or released capabilities. Consult the [dependency matrix](teacher-experience-contract-matrix.md) before consuming any interface.

## Normative decisions for Suite consumers

1. **Authority remains with Core and the producers.** Core owns canonical workspace, years, classes, rosters, Standards, shared navigation and future private Notes. Each producer owns its academic, grading, evidence, portfolio or student-support records. Suite coordinates without copying private stores or manufacturing records.
2. **The teacher home is a future #52 deliverable.** Interactive `pds` will identify **Paper Data Suite** in green on a capable terminal, show an intelligible current task, and include only caller-validated display context. `NO_COLOR`, `TERM=dumb`, redirected streams, or unsupported Windows ANSI/VT require legible plain text. Color is never the sole status indicator. Existing explicit commands, `pds --help`, redirected input and exit codes retain their behavior.
3. **Safe prompt separation.** Core's `:notes` recognizer may be enabled only at an audited, explicitly opted-in, interactive `PromptKind.MENU_CHOICE`. No automatic interception of answers, free text, paths, timestamps, exact confirmations, pauses, or command-line arguments. `B/M/Q` remain navigation, local `H` remains help where offered, and Quillan `N`/`W` remain next-student actions. No global `input()` monkeypatch.
4. **Recognizing `:notes` does not open Notes.** `terminal.notes_command.v1` is a pure parser. Real Notes needs independently qualified `notes.records.v1` and `notes.menu.v1`, owner/workspace eligibility, and an actual Core public menu. Without them, the future home must say **unavailable**; it must not pretend to save a Note or open a dummy editor.
5. **Revalidate canonical context.** Remembered workspace/class/work references and display labels are navigational hints, never authorization or evidence. A workspace change invalidates subordinate context, and an incompatible class change invalidates work context. A foreground subprocess launch cannot promise arbitrary nested-screen return or recovery of unsaved input.
6. **Private Notes are outside normal workspace backups.** Core #243 owns any separately qualified transfer/export/recovery contract for OS-user-protected Notes. Neither Suite settings, attention nor diagnostics may include raw Notes, roster rows, scores, grades, support records or scan payloads. Personal Tasks are not canonical producer attention.
7. **Keep qualification dimensions separate.** Merged #49's approved current-environment launcher is *locally compatible*, not authenticated official provenance or cross-module integration attestation. Core's `paper_data_suite.module_operations` contract is distinct from module install/launch; a provider declaration is not evaluated readiness, attention, or authority to execute an owner action. Actual provider consumption belongs to #16/#20–#23.
8. **No global deadlock.** The future home may expose a truthful unavailable Core Notes or classroom menu when its dependency is absent. This must not block qualified independent launch/doctor/CLI flows. Core #238–#243 and Suite #53/#54 can complete separately.

## Evidence gates (never collapse them)

| Level | What is established | Not established |
| --- | --- | --- |
| D0 design | Suite v0.2 and Core teacher interface v1 agreed | Existence of importable symbols |
| D1 source | Core #237 merged header and pure prompt parser | Published Core wheel or Notes storage |
| D2 installed Core | Exact published Core wheel with tested callable symbols and behavior | Suite/producer adoption or official provenance for arbitrary modules |
| D3 consumer | Exact installed Suite/producer, prompt/collision and handoff tests | Unrelated modules or arbitrary cross-process return |
| D4 composition | Exact mixed-wheel and teacher-journey/Windows/ARM64 acceptance | Future versions and unimplemented capabilities |

**Baseline, 2026-11-06:** Core `main` contains the #237 primitives, but the latest published Core **v0.6.6 predates them**. Do not claim a minimum published release for `terminal.header.v1` or `terminal.notes_command.v1` yet: **D2 NOT YET QUALIFIED**. CI may intentionally use historical Core 0.6.3. The merged #49 launcher tests qualify their own paths, not these new UI symbols.

## Minimal consumer seam (no service dispatch)

`paper_data_suite.teacher_experience_contracts.observe_core_teacher_contract()` is an **explicit**, read-only probe for future #52. On a *pre-contract Core* wheel it reports absence. On a v1 claim it validates the declared immutable capabilities and checks only the advertised header and pure shared-command **public shapes**. A broken advertised symbol, nested missing dependency, or incompatible contract version raises a bounded `CoreTeacherContractError` instead of being disguised as ordinary absence. It does not import Notes/admin menus, call provider callbacks, access the workspace, grant trusted launch, or enable Notes persistence. Source-level tests are not installed release acceptance.

## Handoff

- [x] Design adopted as future Suite target; ownership, privacy, accessibility and prompt contracts clarified.
- [x] Core #237 source versus published Core difference and safe pre-contract fallback documented.
- [x] Exact Core header/recognizer and Suite #49 launch boundary mapped, with negative read-only tests.
- [ ] D2 first released Core wheel carrying these functions — **pending official qualification**.
- [ ] D3 actual home, Notes/admin handoff, producer adoption — **Suite #52–#54 and each owner**.
- [ ] D4 complete installed teacher journeys — **Suite #27/#28**.

**Next:** [Suite #16 provider audit](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/16), then [Suite #52 teacher home](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/52). Do not revive #49's deferred native installer, publisher signing or catalog machinery in #51.
