# Suite teacher-experience v0.2 — public contract and dependency matrix

**Source observations, 2026-11-06:** Suite `main` `eeffc74ec2c20152c3d6cf8c46b1ad6d640a654a`; Core `main` `a0d5e1a50580bbe025f0cad23c7e8524203a52ec`. Revalidate at adoption. These are **source references**, not installed-wheel digests or qualification evidence.

**Critical release distinction:** Core #236/#237 are merged, but **latest published Core v0.6.6 predates `pds_core.teacher_experience`, `teacher_ui`, and `teacher_commands`**. These exact public symbols exist on Core source `main`; their first published, installed qualifying Core version is **NOT YET QUALIFIED**. Suite #49's manual-wheel launcher and doctor/setup were merged with PR #55, with CI acceptance, but that does not certify the new Core UI symbols. Historical Suite manifest pins remain immutable evidence, not current-version gates.

## One authoritative dependency matrix

| Teacher operation | Owner and exact public contract | Current source versus installed evidence | Safe absent / failed behavior | Owning follow-up |
| --- | --- | --- | --- | --- |
| Green header, screen title, validated optional context | Core `pds_core.teacher_ui.TeacherScreenHeader`, `render_teacher_header`, `print_teacher_header`; token `terminal.header.v1` | Core #237 **source implemented**; installed D2 **NOT YET QUALIFIED** | If pre-contract, preserve legible plain/default output; broken claimed API = explicit incompatibility; no arbitrary ANSI or student display context | [Suite #52](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/52) |
| Prompt-scoped `:notes` recognition | Core `pds_core.teacher_commands.PromptKind`, `SharedTeacherCommand`, `parse_shared_teacher_command`; token `terminal.notes_command.v1` | Core #237 source only; not a Notes service; D2 **NOT YET QUALIFIED** | Only exact interactive opted-in `MENU_CHOICE`, not data, confirmation, pause or unattended CLI; retain Quillan `N/W`, existing `B/M/Q`, local `H` | [Core #240](https://github.com/Paper-Data-Suite/pds-core/issues/240), [Suite #54](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/54), each producer |
| Back/main/quit, help and context | Existing Core `pds_core.menu_navigation.parse_navigation_choice`, `NavigationChoice`, `ReturnToMainMenu`, `QuitPDS`; future Core `pds_core.teacher_context` | Existing navigation available; new shared return/context contract **NOT YET QUALIFIED** | Preserve exception semantics and caller-owned return; invalidate stale workspace/class/work hints; no invented nested subprocess resume | [Suite #52](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/52), [#53](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/53) |
| Canonical workspace, year, class, roster, Standards and bulk roster import | Existing Core `pds_core.workspace`, `school_years`, `classes`, `rosters`, `standards`, `roster_imports`; Suite `workspace_setup`, `workspace_cli`, `classroom_setup_cli` | Core existing services; Suite #49 current-Core setup/doctor path; qualify exact installed combination separately | No Suite source of truth; no hidden workspace mutation; guarded canonical selection/currentness and teacher confirmation | [Suite #53](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/53) |
| Individual roster change and callable classroom menu | Planned `classroom.roster_edits.v1`, `classroom.menu.v1`, `pds_core.teacher_menus.run_workspace_classroom_menu` | [Core #241](https://github.com/Paper-Data-Suite/pds-core/issues/241)/[#242](https://github.com/Paper-Data-Suite/pds-core/issues/242) open; **NOT YET QUALIFIED** | Clearly unavailable; retain Core's existing standalone supported commands, not a duplicate Suite roster editor | [Suite #53](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/53) |
| Private Idea/Task/Reflection records and menu | Planned `notes.records.v1`, `notes.menu.v1`, `notes.cli.v1`, `pds_core.teacher_menus.run_notes_tasks_menu` | [Core #238](https://github.com/Paper-Data-Suite/pds-core/issues/238)–[#240](https://github.com/Paper-Data-Suite/pds-core/issues/240) open; **NOT YET QUALIFIED** | No fake Note/editor/record, student association, or dispatch merely from the parser token | [Suite #54](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/54) |
| Private Notes backup/transfer/recovery | Planned Core `notes.portability.v1` | [Core #243](https://github.com/Paper-Data-Suite/pds-core/issues/243) open; **NOT YET QUALIFIED** | Disclose that regular Suite workspace backup **excludes** private OS-user Notes storage; no invented portability guarantee | [Suite #54](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/54) |
| Approved installed module list and foreground launch | Suite `evergreen_local_registry.APPROVED_COMPONENTS`, `evergreen_local_application_inventory.collect_local_launch_inventory`, `cli._run_modules`, `cli._run_launch`, `application_launching` | Suite #49 / merged PR #55; current-source local metadata assessment, with dedicated installed/manual-wheel evidence; exact released artifacts separately identified | Missing/incompatible module does not disable healthy peers; local compatibility **is not official wheel provenance** or cross-module integration qualification; Core is not an application `pds launch` target | [Suite #52](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/52) |
| Producer readiness and attention | Core `pds_core.module_operations` v1, installed entry-point family `paper_data_suite.module_operations`, typed request/profile/readiness/attention reports | Core v1 exists; six producers declare entry points in `main`; installed callbacks and capability mix **NOT QUALIFIED HERE** | Provider missing, incompatible, failed, unavailable and successfully empty attention are distinct; never expose private producer data or execute inert owner-action references | [Suite #16](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/16), [#20](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/20)–[#23](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/23) |
| Mixed returned paper intake and routing | Core PDS2 retain-first custody and published routing contract; module-owned interpretation, evidence and results | Existing Core PDS2 interfaces; exact mixed installed composition **NOT QUALIFIED HERE** | Read-only preview first; no invented authorship, grades, scoring, behavior/support fact, or cross-repo atomicity | [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)–[#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19) |
| Recent application, safe continuation and diagnostics | Suite `settings`, `settings_cli`, `evergreen_local_doctor`, `cli` plus **separate** module-specific public continuation contracts, if any | Suite top-level recent-component state and `pds doctor` exist; nested work-item continuity unqualified | Do not store student identifiers/Notes/scans; stale/deleted/unsupported nested work falls back to approved module entry, not a fabricated deep link | [Suite #24](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/24), [#25](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/25) |

## Producer metadata-only entry point census

All six producer repositories' current `pyproject.toml` declare the **same** `paper_data_suite.module_operations` family. A declaration does not certify a usable installed provider, supported readiness/attention callbacks, trust/provenance, or any owner action. Runtime assessment belongs to [Suite #16](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/16).

| Component | Declared name and public target |
| --- | --- |
| ScoreForm | `scoreform = scoreform.pds_operations:get_module_operations_profile` |
| Quillan | `quillan = quillan.pds_operations:get_module_operations_profile` |
| Concord | `concord = concord.pds_operations:get_module_operations_profile` |
| Meridian | `meridian = meridian.pds_operations:get_module_operations_profile` |
| Vitrine | `vitrine = vitrine.pds_operations:get_module_operations_profile` |
| Portia | `portia = portia.pds_operations:get_module_operations_profile` |

## Qualification / follow-up

- D0: [Suite design v0.2](../design/teacher-experience-design-specification.md) and [Core teacher contract v1](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/teacher_experience_contract_v1.md) specify shapes and ownership, not installed behavior.
- D1: Core #237 source implements only the header and pure command recognizer; [adoption note](teacher-experience-adoption.md) and `tests/test_issue51_teacher_experience_contracts.py` assert safe negative states and public shapes.
- D2: Actual *published* Core wheel containing those #237 symbols is **pending**. The installed-Core tests skip when the installed historical Core wheel lacks them; do not call skips a passed D2 gate.
- D3: Exact installed Suite teacher home and producer menu/collision adoption remain **pending #52/#54 and owner acceptance**.
- D4: Mixed-wheel and physical/synthetic teacher-journey acceptance remain **pending #27/#28**.

Do not substitute source SHA for an installed distribution hash. Keep #49 local-launch eligibility, Core provider readiness, authenticated release identity, and exact cross-module qualification independent. If a feature's public capability is missing, show its actual unavailable state and continue with qualified independent workflows.

### Suite #16 — provider discovery/diagnosis evidence after Slice 3

The [module-operations provider qualification record](module-operations-provider-qualification.md) is the authoritative #16 companion to this matrix. Suite provides `collect_module_operations_metadata()` (Core metadata-only discovery, six approved rows, no imports) and the **separately explicit** `collect_module_operations_profile_diagnosis(metadata_inventory=...)` (Core profile validation; possible installed code execution). Neither returns operational evaluation results or confers launcher/provenance privileges. The bounded [exact official wheel witness](../../scripts/issue16_official_wheel_acceptance.py) uses a dated GitHub-release SHA-256 manifest and requires a **real explicit wheelhouse run** before claiming installed acceptance; static/synthetic test results are not release qualification. Continue to mark readiness, attention, and owner-action execution **NOT QUALIFIED** until the owning #20–#23 integrations pass. Suite #52 must consume metadata-only availability by default.

### Suite #52 — teacher-home D1 source journey and two-track Core evidence (2026-11-07)

[Suite #52 source acceptance and handoff](issue52-teacher-home-source-acceptance.md) records the real interactive-home controller, exact six-app menu and guarded foreground delegation from feature branch `52-interactive-teacher-home` (Slice 3 parent `6d4b19f0104794a65ed0bebae4bf49534192eca5`). Slice 4's Windows test and synthetic journey evidence qualify only the **source-level teacher-home consumer**; the fixture launches no real producer, provider callback or record store. The accepted #49 launcher remains the launch authority.

The teacher's completed Slice 3 Windows witness verified Core source `a0d5e1a50580bbe025f0cad23c7e8524203a52ec` as a **developer-only build** with wheel SHA-256 `62a62f4f3da06e6926832ec22d2b071449f5424aa58566ee1f1ca32120bef2ef`, exercised `terminal.header.v1` and pure `terminal.notes_command.v1`, and **separately** verified the official published Core v0.6.6 wheel SHA-256 `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` for pre-contract plain-text fallback. **The official Core v1 header wheel D2/D3 acceptance is still NOT YET QUALIFIED.** Source evidence and a 0.6.6 version string are not publisher provenance; the existing matrix's installed-artifact qualification limits remain in force.

Handoff is capability-gated: #53 owns `classroom.menu.v1`; #54 owns real `notes.records.v1`/`notes.menu.v1`; #17–#23 own paper intake and evaluated attention; #24 owns deeper recent work; #25/#26 own extended diagnostic behavior. None of these is implemented by #52's disabled menu labels. Real supported interactive-console/ANSI behavior and the official newer-Core wheel gate remain pending, and the #52 merge/deferral decision must state that explicitly.

### Suite #20 — attention projection/renderer source handoff and D2 gate (2026-11-21)

The first three #20 slices establish a **source-level, pure** Suite attention
consumer with no automatic producer execution. The approved six-owner
`paper_data_suite.module_attention_projection.project_module_attention` view
consumes explicitly supplied #16 metadata/profile observations and Core v1
`ModuleOperationsInvocationResult`, checking owner/class boundaries and
keeping unavailable, failed, unevaluated, evaluated-empty and reported-item
states separate. `module_attention_rendering.filter_attention_projection`
and `format_attention_display` provide bounded exact filters, stable order,
privacy-safe generic labels, incomplete-coverage disclosure and inert actions.
`module_attention_label_policy` contains **no** producer category approvals
until #21/#22 qualify them from exact installed source and privacy review.

Source status: **Slices A–C committed** on the #20 development branch, with
Ruff, strict mypy and their focused regressions qualified on Windows; not
merged and not a published new Suite wheel. [Slice D evidence and consumer
handoff](issue20-attention-installed-handoff.md) adds a separately executable
clean installed Core **v0.6.6** + newly built Suite **0.1.0** synthetic contract
smoke. Actual installed outcome remains **PENDING until run and recorded**.
No real ScoreForm, Quillan, Concord, Meridian, Vitrine or Portia attention
callback evaluation is qualified by #20; those are **#21/#22**. Interactive
Attention Needed, live owner actions and Notes separation require **#23**;
physical/classroom release acceptance remains **#27/#28**. This note updates
the older #16/#52 source observations without changing their historical
published-release evidence or asserting a consolidated Core Notes/UI release.

### Suite #21 — Slice A tagged-provider audit and per-owner admission block (2026-11-21)

[Slice A release/category/authority audit](issue21-slice-a-released-attention-audit.md) inventories the exact **8 ScoreForm v0.13.0**, **17 Quillan v0.10.6**, and **20 Concord v0.3.4** published attention codes, literal source labels, inert action IDs and count/scope semantics. This is source/release-metadata evidence, **not downloaded-wheel, publisher-signing, installed callback, label-privacy or teacher dashboard qualification**. The #20 label allowlist remains empty; generic labels and six-owner unevaluated states remain unchanged.

A public Core v0.6.6 contract gap blocks safe targeted evaluation: `inspect_core_provider_entry_points` is metadata-only, while `diagnose_core_providers(provider_kind="module_operations")` loads **all** candidates rather than only the explicitly admitted named owner. Suite will not invoke this broad diagnostic or introduce a parallel/private loader. Targeted Core-owned candidate selection, separately checked installed provenance, explicit workspace authorization and real synthetic read-only provider callbacks remain **PENDING** in #21 Slices B–E. #49 launch and #52 home are unaffected; #22 and #23 are downstream, not silently activated.

### Suite #21 — Slice B0 explicit read-only scope preflight (2026-11-21)

[Slice B0 contract and focused synthetic gate](issue21-slice-b0-scope-preflight.md) adds `prepare_selected_attention_scope` with exact selected root/current Core root agreement, open school year, class existence, approved named owners and symlink/redirect refusals. It creates only an in-memory `ModuleOperationsRequest`, never a provider profile or attention result, and does not change startup, launch or Teacher Home. The caller's authorization, Core #249 targeted profile acquisition, SHA-qualified installed official producers and native read-only callbacks remain **PENDING**. Do not promote this preflight into a live evaluation or approved category label without the later release and privacy gates. Its source tests are committed but **not yet executed**.

### Suite #21 — Slice B1.0 offline ScoreForm release-evidence gate (2026-11-21)

[Slice B1.0 contract and focused synthetic tests](issue21-slice-b1-offline-scoreform.md) reuse Suite #16's exact Core 0.6.6 / ScoreForm 0.13.0 official wheel SHA-256 and metadata inspection, then require matching installed **metadata** for version and one exact ScoreForm operations entry-point. This is a deliberately invoked **script**, never a provider loader or ordinary startup/home path. Its strongest state is explicitly `metadata_consistent_not_admitted`: separate evidence of actual installed wheel bytes, provider profile validation, fresh user authorization, read-only callback behavior and the Core #249 new published API remain **PENDING**. Synthetic test source is committed; local B1 tests are **not yet executed**. B0 qualification passed 30 tests/Ruff/mypy with 3 Windows symlink skips.

### Suite #21 — C0/D0 offline Quillan and Concord release evidence (2026-11-21)

[Shared Core-plus-owner offline release inspector and new focused synthetic matrix](issue21-slice-c0d0-offline-producers.md) use the **same** #16 exact published-wheel hash/entry-point metadata contract for `quillan v0.10.6` and `pds-concord v0.3.4`, without a new Python provider loader. The B1 ScoreForm function/CLI remains preserved. The explicit C0/D0 CLI allows one named owner at a time and refuses unknown, foreign and duplicate candidates before provider import. Strongest result `metadata_consistent_not_admitted` is **not** installed wheel provenance or callback authority. **New C0/D0 source tests, Ruff and mypy pending local execution**; Core #249 blocks live attention invocation. B1.0 source gate qualified **55 passed, 4 Windows symlink skips, Ruff and mypy passed**.
