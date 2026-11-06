# Paper Data Suite Teacher Experience Design Specification

**Status:** Draft v0.2 — eight design decisions accepted by project owner; not yet an adopted, release-qualified implementation contract  
**Specification version:** 0.2  
**Date:** 2026-10-21  
**Scope:** Paper Data Suite (Suite), PDS Core, ScoreForm, Quillan, Concord, Meridian, Vitrine, Portia, and future teacher-facing modules  
**Purpose:** Establish one recognizable, teacher-first interaction experience across independently developed PDS applications while preserving their distinct domain models, authority boundaries, safety rules, and direct CLI capabilities.

## 1. Executive intent

Paper Data Suite consists of specialized applications for assessment, writing review, collaborative work, grading/reporting, portfolio curation, and student-support workflows. These applications should feel like parts of one suite, even when their records and processes legitimately differ.

A teacher should be able to recognize which application is open, capture a thought or task without leaving the current work, maintain one authoritative classroom roster, understand what an operation means, and continue a multi-step task without navigating an implementation-oriented maze of identifiers and menus.

**Design principle:** The teacher describes an educational intention; PDS manages the necessary record creation, validation, revision history, and integration mechanics. The software must not hide consequential academic judgments or authorization decisions.

This specification defines **interaction conventions and shared services**, not a universal academic data model. It does not rename existing canonical fields, transfer ownership of producer records, or authorize silent modification of academic evidence, Scores, Grades, portfolios, support records, or publications.

## 2. Requirement language and boundaries

- **MUST**: required for conformance once this specification is adopted.
- **SHOULD**: preferred default; an exception requires a documented rationale and acceptance test.
- **MAY**: optional or module-specific capability.

The requirements apply to teacher-facing interactive terminal menus and future PDS graphical frontends. Direct noninteractive CLI commands remain supported, scriptable, and explicit. A GUI is not required to conform; the same teacher-facing concepts should work in a terminal.

**In scope:** shared terminology; module identity and screen design; navigation; active context; guided actions; confirmations; feedback and recovery; a Core-owned Notes & Tasks facility; unified workspace/classroom administration; a Suite home menu; cross-module integration conventions; accessibility; and acceptance criteria.

**Out of scope for this draft:** changing any producer's domain model; merging producer databases; inventing a cross-module grading policy; automatic assessment or student-support judgments; institutional authentication or SIS integration; cloud synchronization; external messaging; and survey functionality (a separately acknowledged future goal).

## 3. Architectural ownership

| Layer | Owns | Does not own |
|---|---|---|
| **PDS Core** | Authoritative shared school years, classes, rosters, Standards, workspace contracts, shared menu primitives, and proposed Notes & Tasks records/services | Producer academic judgments or workflow-specific data |
| **PDS Suite** | Teacher home, module discovery/launch, common administration entry points, shared experience specification and integration/orchestration | A competing copy of canonical roster/Standards or producer data |
| **Producer modules** | Their domain workflows, records, review judgments, evidence, publication preparation, and context-sensitive presentation | Duplicated authoritative shared-classroom data or unrelated modules' records |

A shared interface may orchestrate module-owned public APIs. It MUST NOT bypass canonical validation or claim a multi-repository transaction where none exists. Core may supply reusable UI functions, but module-specific workflow decisions remain in the responsible module.

## 4. Common teacher vocabulary

Words shown in menus and confirmations MUST have stable, understandable meanings.

| Term | Teacher-facing meaning |
|---|---|
| **Create** | Establish a new item or definition; creation alone does not imply adoption, distribution, scoring, or publication. |
| **Set Up** | Configure how classroom work or a module process will operate. |
| **Prepare** | Produce or assemble material for a later action, without claiming that it was delivered or returned. |
| **Review** | Inspect existing information and, where appropriate, make an explicit review decision. Viewing alone is read-only. |
| **Use** | Adopt a selected configuration or plan for the stated context. |
| **Record** | Persist an observation, decision, result, or other teacher-authored record. |
| **Continue** | Resume the next relevant incomplete step from validated current state. |
| **Finish for Now** | Leave a workflow while retaining only already-confirmed durable work. |
| **Share** | Make information available to a stated authorized recipient, destination, or consumer. |
| **Export** | Produce a copy or local artifact; export does not imply external delivery or permission to disclose. |
| **History** | View earlier revisions, actions, or records without silently restoring them. |
| **Technical Details** | Deliberately inspect exact IDs, provenance, lineage, revisions, diagnostics, hashes, and recovery information. |

**Rules:**

1. The same verb MUST NOT alternately mean *preview*, *save*, *apply*, and *publish* across modules.
2. A **Preview** MUST be clearly described as read-only unless it deliberately creates a separate named, durable review record; if so, the write must be disclosed before it occurs.
3. A **Score** is not automatically a **Grade**. Scoring, proficiency judgments, grading policy, and reporting remain distinct in their appropriate modules.
4. **Prepared**, **distributed**, **returned**, **retained**, **assembled**, **reviewed**, and **published** describe different evidence states; menus MUST NOT conflate them.
5. Teacher-facing labels SHOULD use recognizable terms such as *rubric*, *student*, *group*, *class*, *assessment*, and *returned work*. Exact domain labels (e.g., Criterion Set, ArtifactInstance, GroupPlan, Snapshot Edition) MAY remain in Technical Details and advanced tools where precision matters.
6. A module MUST distinguish suggestions and optional next actions from mandatory prerequisites.

## 5. Persistent visual identity and screen header

Every PDS-owned interactive screen MUST identify its active application. The identity MUST be **green** when terminal color is supported, including in nested menus, normal workflow screens, result summaries, errors, and recoverable interruptions. The module title is a stable visual anchor rather than a transient startup banner.

Standard header structure (three fields, no placeholder values):

```text
[GREEN]Quillan[/GREEN]
Review Student Work
English 12 · Period 2 · Personal Narrative Revision
```

1. **Application name** — persistent green module identity.
2. **Current task/screen title** — plain, specific teacher-facing language.
3. **Context line (only when valid and relevant)** — class and work item; a student label may be displayed by the owning module when appropriately authorized, but must not be automatically exported as shared Notes & Tasks context.

The optional third line MUST be omitted when no appropriate context exists; the application name MUST remain visible at the beginning of each PDS-controlled screen render. Outside PDS-owned screens, such as an external PDF viewer or operating-system file dialog, PDS cannot impose a header.

Core SHOULD provide one reusable default header renderer with configurable application name, section title, and optional context line. The renderer MUST safely detect ANSI/terminal support (including on Windows), respect `NO_COLOR`, and provide a readable plain-text fallback for non-ANSI terminals, redirected output, and captured test output. User-facing code SHOULD NOT embed inconsistent standalone ANSI escape sequences. **No separate optional compact-mode preference is required for the initial implementation.** A single compact, legible default is the standard; revisit display variants only with evidenced need.

The suite-level application name is **Paper Data Suite**. The module names are **PDS Core**, **ScoreForm**, **Quillan**, **Concord**, **Meridian**, **Vitrine**, and **Portia**, subject to an approved display-name registry. Consistent color and position matter more than identical screen contents.

## 6. Navigation and active context

### 6.1 Common navigation

The existing shared `B. Back`, `M. Main Menu`, and `Q. Quit` semantics remain normative. `H. Help` SHOULD be available in routine menus. They MUST not conflict with data-entry prompts in ways that cause accidental writes.

A **Notes & Tasks** entry MUST be available consistently across every module's routine teacher-facing menus. The **reserved global command is `:notes`**, shown consistently in the navigation area. Do **not** globally bind `N`: Quillan already uses `N` for **Next Student**, and `W` for **Next Student Needing Review**. Existing local single-letter shortcuts MUST retain their meanings.

The `:notes` dispatcher MUST recognize an exact, case-insensitive command only at interactive **menu-choice prompts**. It MUST NOT intercept writing, filename/path entry, search text, timestamps, free-text notes, or any other field input. Other colon-prefixed commands are not implicitly authorized. A pre-adoption audit MUST check every relevant module screen for collisions and parsing edge cases; where a screen cannot safely support the shared command, provide a plainly labeled **Notes & Tasks** menu choice at an accessible boundary and document the exception. Never silently override an existing action. Numeric positions MAY differ by module.

Entering and returning from Notes & Tasks MUST preserve the current module workflow and validated active context. Modules SHOULD make it easy to return to the exact originating screen where technically feasible, without reconstructing uncommitted canonical changes. A module MUST NOT discard confirmed work merely because the teacher opened a shared utility. Unconfirmed or partly entered content MUST be treated honestly: either retain it safely in memory or explicitly warn that returning will not preserve it.

### 6.2 Context handling

- A module SHOULD remember the active **workspace → class → current work item** (e.g., assignment, Activity, Portfolio) for the duration of the session where safe.
- Remembered context is navigational convenience, not canonical evidence, teacher identity, or authorization.
- Switching workspace MUST invalidate subordinate class/work selections; switching class MUST invalidate incompatible work selections.
- Context MUST be canonically revalidated before any consequential use.
- Exact internal identifiers remain available to direct CLI and technical inspection but SHOULD NOT be typed or repeatedly selected in routine menus when a validated choice already exists.
- The module MUST NOT guess a target when multiple eligible classes, students, assignments, or publication destinations remain genuinely ambiguous.

## 7. Guided workflow interaction contract

Every substantial teacher task SHOULD provide these stages as needed; a module MAY omit stages that do not apply:

1. **Orient:** show the current module, class, work item, task, and confirmed state.
2. **Choose:** ask only the educational decisions not yet established.
3. **Prepare:** resolve dependencies, select reusable definitions, and validate required inputs.
4. **Review:** show a concise human-readable summary of the intended consequential action.
5. **Confirm:** obtain a meaningful teacher authorization for that action.
6. **Commit:** invoke the responsible module's guarded service(s), preserving exact authority and revision checks.
7. **Report:** distinguish full success, no-op, canceled, partial success, and blocked/conflicted states with a truthful durable receipt.
8. **Continue:** offer the next relevant action, **Finish for Now**, and navigation back; do not force a return to a deep parent menu.

**No redundant confirmations:** If internal `draft → previewed → approved → applied` transitions implement one teacher decision, the menu SHOULD ordinarily present one meaningful **Use this plan** decision while the underlying service executes the required guarded operations. Distinct authorization or safety boundaries MUST remain explicit. Cross-store operations MUST report partial commits rather than pretending to be atomic.

**No hidden attachment step:** When a workflow says **Create and use this assessment**, a successful operation MUST both create the definition and associate the appropriate instance/revision with its selected work item, or truthfully explain the partial state and offer recovery. If **Create only** is supported, label it distinctly.

**No mandatory developer vocabulary:** Generated IDs, digests, revision tokens, schema names, and serialized JSON MUST NOT be required as ordinary teacher inputs unless the task genuinely requires that technical choice. Use typed, numbered, labeled selections and sensible defaults.

**No invented state:** Generating a packet cannot imply that students received it; routing a scan cannot prove authorship; a group Score cannot be silently assigned as an individual's proficiency; a saved note cannot trigger scoring or grading.

### 7.1 Errors and recovery

A recoverable failure MUST explain **what happened**, **whether anything was saved**, and **what action the teacher can take next**. Stale state SHOULD offer refresh/review/retry, subject to exact consistency checks. Canceling before authorization SHOULD produce no new canonical work. After partial durable changes, continuation MUST be based on current authoritative state and support safe, idempotent restart where feasible.

### 7.2 Accessibility and density

Routine screens SHOULD use concise headings, compact context, meaningful labels, paginated selections, and progressive disclosure. Critical information MUST NOT be communicated by color alone. Choices MUST remain keyboard-operable, readable without ANSI, and usable in a 47-minute classroom workflow under time pressure.

## 8. Shared Notes & Tasks (proposed Core service)

### 8.1 Intent

A teacher can capture and retrieve informal work notes from any PDS application without leaving the task in progress. This facility is **not** a replacement for Quillan's student-specific review notes, Portia's formal student-support records, Concord's reviews, ScoreForm's scoring records, Meridian's Grades, or Vitrine's evidence annotations.

**Accepted teacher-facing name:** **Notes & Tasks**. **Accepted initial entry categories:**

- **Idea** — possible future activity, improvement, investigation, or resource.
- **Task** — action requiring attention, with optional due date and completion state.
- **Reflection** — teacher observation or insight for later consideration.

The categories are teacher-facing classifications, not separate databases. Reclassification SHOULD preserve history.

### 8.2 Minimum viable teacher functions

1. **Quick Capture:** enter type and free-text content; no mandatory tags, technical IDs, or due date.
2. **Browse:** view recent entries and incomplete Tasks; sort and filter by type/status/date.
3. **Search:** find text without exposing unrelated student data.
4. **Update:** edit content, categories, dates, and task status with preserved revision/audit information appropriate to the local teacher tool.
5. **Complete / Reopen / Archive:** manage the personal work queue without deleting historical context by default.
6. **Return:** restore the prior application screen and valid context after use.

Optional later capabilities include pinned entries, tags, related entries, reminders, owner-validated deep links, and suite attention integration. Automatic cross-module execution is **not** part of the MVP.

### 8.3 Candidate record contract (design sketch, not final schema)

```text
entry_id                 generated internal identity
kind                     idea | task | reflection
text                     teacher-entered body
status                   type-appropriate lifecycle state
created_at / updated_at  explicit offset-aware timestamps
origin_module            informational, e.g., quillan
origin_context           optional validated class/work reference
actor_reference          attribution, not authentication
owner_scope              explicit authorized teacher-local visibility scope
due_on                   optional local date for Tasks
revision                 for guarded update and conflict detection
```

Only the type and text should need teacher entry for Quick Capture. Generated identity, timestamp, owner scope, and required provenance are system-established; other context is populated automatically or omitted safely. The final schema MUST be established by Core design review, not inferred from this sketch. For the initial release, `origin_context` may contain a validated module, class, and non-student work-item reference only; it MUST NOT embed a structured student identifier.

### 8.4 Accepted storage and teacher-local ownership decision

- Core MUST own **one logical Notes & Tasks record collection per PDS workspace**, partitioned by teacher-local ownership, with public Core services for storage, validation, query/update, and lifecycle. Producer modules MUST use those services; they MUST NOT create parallel notes stores.
- For the initial single-user pilot, private note bodies SHOULD reside under an **OS-user-protected local application-data area**, not in a generally shared classroom-workspace folder. Records MUST include a stable workspace association and explicit owner scope. Core design review MUST resolve workspace identity across renamed/moved workspaces without accidentally merging unrelated collections.
- Owner scope MUST be derived from qualified local execution/OS-user context; a caller-supplied `actor_reference` is **attribution only**, not proof of authentication. The pilot MUST NOT claim secure multi-user separation, especially where multiple teachers share one OS login or where filesystem protections are unavailable. Such usage requires additional authentication/access-control design and qualification.
- The location creates a **backup and portability distinction**: whole-workspace backups do not automatically include teacher-private application-data notes. Suite/Core MUST explicitly disclose that fact and provide a qualified private-data export/backup/restore plan before representing the feature as safely backed up or portable. No automatic cross-device synchronization is included in the MVP.

### 8.5 Data boundaries and protection

- A Notes & Tasks entry MUST NOT alter any producer-owned record or automatically publish/share a result.
- The initial release MUST NOT persist **structured student identifiers**, student selectors, or automatically generated student-record links. Automatically attached context is restricted to minimal validated module/class/non-student work-item references; no student work, grades, support records, or review text may be copied into metadata. Free text **can** still contain identifying information and MUST be protected as private data.
- Private notes MUST NOT appear in class-wide dashboards, exports, student/guardian views, other users' views, or external logs by default.
- A clear threat model and demonstrable local isolation, direct API access tests, log/privacy tests, and backup-behavior tests are required before any real sensitive content is qualified. Student-linking and genuinely shared/multi-user notes are later, separately reviewed capabilities.
- Persistent writes MUST be atomic or safely recoverable and protected against lost updates or concurrent write conflicts.
- A due date is not a reminder. The application MUST NOT claim notification delivery unless a separate reminder feature actually exists.

### 8.6 Personal Tasks and module attention

The Notes & Tasks MVP maintains its own **personal work queue** (including optional due dates and completion). It MUST NOT put teacher-authored Tasks into canonical producer attention feeds, infer that a module operation failed, or change a student or assessment state. Later, Suite MAY display these alongside module-provided attention, but MUST use visibly separate headings such as **My Tasks** and **Module Attention**, separate provenance, and no implicit conversions or auto-execution. An overdue personal reminder is not a module workflow warning.

## 9. Workspace & Classroom Management

**One authoritative home:** Core owns canonical workspace, school-year, class, roster, and Standards operations. **Core MUST provide a supported in-process shared administration menu API**, as well as its own standalone menu and deterministic CLI capability. Suite MUST expose this same administration capability as the primary teacher-facing entry point. Producers MAY invoke the public shared Core menu in-process, but SHOULD otherwise limit themselves to relevant selection/context and a clear hand-off to shared administration; they MUST NOT maintain separate authoritative roster editors.

Returning from shared administration MUST restore the originating module's navigation state when supported, re-resolve the workspace, and canonically revalidate class and work-item context before consequential actions. Workspace/class changes MUST invalidate incompatible selections; no stale student or assignment may remain implicitly selected. Do not require an unnecessary separate process, Suite restart, or module relaunch for a normal shared-administration operation.

The shared **Workspace & Classroom Management** menu SHOULD cover:

- current workspace inspection, selection, validation, and preference management;
- school year and class browsing/setup;
- roster viewing, adding a student, updating a student, safely removing a student, CSV import/reconciliation, and bounded export as authorized;
- Standards library and profile entry points;
- clearly explained impact warnings when roster changes may affect existing prepared materials, without silently regenerating or rewriting producer records.

**Rosters:** Existing Core guarded roster-import preview/commit services SHOULD be reused. A roster change review MUST distinguish adds, edits, removals, and unchanged records, require explicit confirmation for consequential changes, and reject stale revisions. Single-student operations SHOULD receive equivalent consistency and audit protections.

**Migration:** Quillan's and ScoreForm's existing roster menus may remain temporarily as compatibility entry points, but SHOULD ultimately delegate to the supported shared Core administration interface rather than maintain divergent teacher-facing administration flows. Removing old entry points requires discoverable navigation, release notes, tests, and an orderly compatibility plan.

## 10. Paper Data Suite teacher home

Running `pds` without subcommands in an interactive terminal SHOULD open a persistent **Paper Data Suite** home menu. `pds --help` and all existing explicit noninteractive subcommands MUST retain their established CLI semantics. If no interactive terminal is available, the command SHOULD display usage/help instead of waiting for input.

The home menu SHOULD include:

1. **My Applications:** list installed, suite-qualified modules by readable name and purpose; launch using the existing verified public boundaries; show unavailable/incompatible modules accurately.
2. **Notes & Tasks:** Core-backed quick capture and work queue.
3. **Workspace & Classroom Management:** the same supported in-process Core administration interface used by Core and participating producers.
4. **Recent Work & Attention:** bounded, privacy-conscious context and owner-routed next actions where module providers support them; any later personal Task summary MUST remain distinct from module-owned attention.
5. **Backups & System Health:** existing verified backup, restore, compatibility, and diagnostic operations.
6. **Help / Exit:** common navigation and usage guidance.

The home menu MUST NOT silently claim an installed module is ready merely because an executable exists. It MUST NOT scrape producer-private data or become an alternative authority for records owned by a module.

## 11. Common integration and migration contract

All modules SHOULD consume shared interfaces for header rendering, navigation, and Notes & Tasks where suitable. The experience contract MUST avoid requiring a producer to import another producer directly or bypass Core's public APIs.

Prioritize integration by **teacher journeys**, not by counting menu handlers. Reuse already established effective patterns:

- ScoreForm's continuous retained-scan → results → review path;
- Quillan's validated active class/assignment context;
- Portia's automatically generated opaque IDs and technical-details disclosure;
- Vitrine's bounded contextual next-action and review transitions;
- Core's `B / M / Q` navigation and authoritative shared-data contracts.

No single module must implement an identical six-step menu. Its teacher-facing verbs, confirmations, headers, recovery, and hand-offs must conform while its academic semantics remain distinct.

## 12. Acceptance criteria and qualification scenarios

Conformance MUST be demonstrated with realistic **interactive menu tests**, not just service-level unit tests. Tests use synthetic teachers, classes, and students; no production student data in repositories or CI fixtures.

| ID | Scenario | Required result |
|---|---|---|
| **UX-01** | Navigate main and three nested screens in every module | Green module name and current screen title on every controlled interactive screen, optional validated context, readable non-color fallback; no separate compact preference required. |
| **UX-02** | Open `:notes` from an active Quillan review | Capture a Task, return with validated context and no lost confirmed work; view it from ScoreForm or Suite. `N` still means Next Student and `W` Next Student Needing Review; free-text prompts do not intercept `:notes`. |
| **UX-03** | Capture an Idea from Concord and a Reflection from Portia | Both appear in the same Core-owned collection, with correct origin and authorized visibility, without mutating producer records. |
| **UX-04** | Create and use a Concord assessment | Teacher makes educational choices once; compatible existing Scale offered; Criterion Set is correctly created and selected without a hidden follow-up menu. |
| **UX-05** | Prepare groups and packets | One meaningful Use/confirm action per decision, technical identifiers hidden by default, true prepared/returned status, safe guarded commit/recovery. |
| **UX-06** | Update a roster through Suite, Core, or an invoking producer | All route to supported Core authority with identical validation/guard semantics; changes previewed and confirmed; returning to ScoreForm/Quillan revalidates remembered class/work context. |
| **UX-07** | Launch from `pds` | Interactive home on a TTY; only compatible modules presented as launchable; direct `pds <command>` and `pds --help` remain script-safe. |
| **UX-08** | Cancel, restart, or encounter a stale write | No unauthorized mutation; clear full/partial/no-write receipts; recovery from canonical state without duplicate records. |
| **UX-09** | Open a technical-details screen | Exact IDs, revisions, and permitted provenance are discoverable without dumping private unrelated data in the routine workflow. |
| **UX-10** | Try accessing Notes & Tasks across OS users, actor labels, workspaces, and shared logins | Qualified local isolation succeeds where supported; actor-label switching alone grants no access; shared-login multi-user security is explicitly unsupported until qualified. No structured student IDs are persisted. |
| **UX-11** | Review ScoreForm evidence, Quillan writing, Meridian Grades, and Portia support work | Terminology and screen patterns remain consistent while Score / Grade / evidence / support authority boundaries are preserved. |
| **UX-12** | Inspect a teacher-local workspace backup and personal Task summaries | The backup/export scope truthfully states whether private notes are included; personal tasks are visually and semantically distinct from producer attention; no automatic publication or grading occurs. |

Release acceptance SHOULD include physical classroom/terminal trials on supported Windows hardware, including relevant ARM64 configurations, plus automated tests on supported platforms and installed distributions. A test passing against development source alone is not evidence that the released composition is qualified.

## 13. Accepted issue placement and dependency order

**Stage A — Suite-owned specification and gap audit.** Maintain this cross-module design contract in the `pds-paper-data-suite` repository; audit teacher menus, the entire single-letter/colon-command namespace, headers, and existing Core service boundaries. Record module exceptions and tests. Acceptance of design decisions is not the same as qualification of their implementations.

**Stage B — Core shared UI foundation.** Implement the common three-field green header, safe ANSI fallback, menu-choice-only `:notes` dispatch convention, and public in-process shared-menu interfaces. Migrate callers in bounded slices; do not change direct noninteractive CLI parsing.

**Stage C — Core Notes & Tasks.** Design and qualify stable workspace association, local teacher-private storage/ownership, supported OS-user isolation, guarded persistence, backup/portability disclosures, CLI, and the shared teacher menu. Only after these qualify should modules expose Quick Capture with safe return. Structured student references and multi-user/shared-login security are explicitly deferred.

**Stage D — Core classroom administration.** Close the teacher-menu roster-editing gap over existing guarded Core roster facilities; provide a supported in-process shared administration menu with context revalidation and parity with direct CLI. Then adapt producer entry points by delegation, preserving backward-compatible navigation where necessary.

**Stage E — Suite teacher home.** Add the interactive `pds` home and route qualified application launching, Notes & Tasks, shared classroom administration, recent work, and diagnostics through supported public contracts. Preserve noninteractive commands.

**Stage F — Bounded per-producer adoption and teacher journey acceptance.** Add repository-local adoption issues for ScoreForm, Quillan, Concord, Meridian, Vitrine, and Portia. Preserve existing module-domain shortcuts such as Quillan `N`/`W`. Reuse Concord [#139](https://github.com/Paper-Data-Suite/pds-concord/issues/139) for already scoped functionality, and refine [#153](https://github.com/Paper-Data-Suite/pds-concord/issues/153) for shared navigation/header integration rather than duplicating its work. Test installed compositions and continuous teacher journeys.

Core/Suite implementation milestones or umbrella issues SHOULD be opened separately and ordered by the above dependencies; the specification is not itself authorization to change existing issue scopes without triage. **Release-blocking correctness repairs across modules may proceed in parallel** and MUST NOT be stalled by future UI cross-repository dependencies.

## 14. Accepted design decisions and implementation qualification gates

The project owner accepted the following decisions on **2026-10-21**. They are **design resolutions**, not claims that the code exists or that privacy, compatibility, or release qualification has passed.

| ID | Accepted decision |
|---|---|
| **D-01** | Use **Notes & Tasks**, initially categorized **Idea / Task / Reflection**. |
| **D-02** | Core owns a workspace-associated logical collection; initial private bytes are teacher-local, protected by the OS-user boundary, with explicit owner scope and an honest single-user security limit. |
| **D-03** | Reserve exact `:notes` at menu-choice prompts; preserve Quillan `N`/`W` and every other established local shortcut. |
| **D-04** | Standardize green module name, screen/task title, and optional validated context; no MVP compact-mode preference. |
| **D-05** | Use one supported **in-process Core administration menu**; Suite is the primary entry and producer callers revalidate context on return. |
| **D-06** | No structured student IDs or auto-linked student records in the first Notes & Tasks release. |
| **D-07** | Personal Tasks remain separate from canonical producer attention; later combined views show distinct sections and provenance. |
| **D-08** | Suite owns the design contract and home; Core owns shared primitives, Notes & Tasks, and roster administration; producers adopt incrementally, with no duplicate Concord #139 work. |

### Qualification gates still to resolve

1. Complete the **menu-command collision audit**, including colon-prefixed inputs and safe return from nested menus; no `N` reassignment.
2. Approve a concrete **Core teacher-local storage and workspace-association scheme** and threat model. Demonstrate OS-user protections; never claim multi-user or shared-login isolation based only on actor labels.
3. Define **private Notes & Tasks backup/export/restore** behavior. Existing workspace backups cannot be presumed to include OS-user-local files.
4. Qualify the shared Core administrative menu's **in-process integration, revalidation, and direct-CLI parity**, including workspace switching and roster editing.
5. Link actual implementation issues/milestones by repository, then demonstrate end-to-end installed teacher journeys and privacy regressions.

## 15. Adoption and change control

The eight design decisions in Section 14 are accepted; **this draft is not yet a release-qualified implementation contract and has no automatic effect on published artifacts**. Formal adoption SHOULD produce a versioned approved specification, an owner/consumer matrix, a repository-by-repository gap audit, linked implementation issues, and end-to-end acceptance tests. Any module-specific exception should state the legitimate educational or technical reason rather than simply preserve historical inconsistency.

**Success criterion:** A teacher experiences Paper Data Suite as one recognizable environment with specialized tools—not as unrelated command-line programs exposing their internal record machinery.
