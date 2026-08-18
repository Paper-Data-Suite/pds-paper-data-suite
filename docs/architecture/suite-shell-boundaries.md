# Suite Shell Ownership and Integration Boundaries

**Status:** Normative architecture contract
**Applies to:** `pds-paper-data-suite` v0.1.0 and later work unless explicitly amended
**Established by:** Issue #2
**Initial audit date:** 2026-08-18

## 1. Purpose

`pds-paper-data-suite` is the suite-level orchestration layer for Paper Data
Suite. Its purpose is to make installation, diagnosis, workspace setup,
component discovery, launching, backup/recovery, and later bounded cross-module
operations easier for a teacher without moving authority out of PDS Core or the
domain modules that own it.

This document is normative. Later suite-shell implementation MUST preserve these
boundaries. If a later issue requires a conflicting design, that issue MUST
explicitly amend this contract rather than silently bypass it.

The central rule is:

```text
orchestration != ownership
```

The shell may coordinate an operation without becoming the authority for the
records, semantics, or persistence involved in that operation.

## 2. Current-state basis

This contract was initially audited against the following `main` revisions:

| Repository | Audited revision |
| --- | --- |
| `pds-paper-data-suite` | `d614de2d980af13f334a5fef6f7b54339eeeac4b` |
| `pds-core` | `6c507213618b68a6dd3ea096e1a898201ff029e6` |
| `pds-scoreform` | `047e47f60730b8a5540b5e1d92f008ffad37eede` |
| `pds-quillan` | `268fe0ab6f3d74848bf71f1aa1b939adbe242452` |
| `pds-concord` | `a742d7bb5e46f44d1fb0af3ff1bc77799427559e` |
| `pds-meridian` | `bdd652f699be303418375f71ab9c2179fefe2143` |
| `pds-vitrine` | `8e05250b04e8ed7b916e57637213a5875a55fd78` |
| `pds-portia` | `523cfd6dd75eef9cb10930e328bb7d98b8924bdf` |

These revisions establish the facts used here, but they do not freeze sibling
repositories permanently. Later work MUST re-audit any public integration
surface that materially changes.

At the time of this audit:

- Core 0.6.0 is the shared infrastructure baseline.
- ScoreForm 0.10.0, Quillan 0.9.0, and Concord 0.2.0 are executable applications
  that expose Core routing profiles.
- ScoreForm, Quillan, and Concord also expose publication-producer profiles.
- Meridian is an executable publication consumer and grading/reporting
  application, but it is not a PDS2 routing module.
- Vitrine is an executable portfolio application, but it is not a PDS2 routing
  module and does not expose a publication-producer profile.
- Portia has extensive architecture, schemas, fixtures, and validation but does
  not yet contain an executable application.

This diversity is intentional. No single plugin or package category is allowed
to stand in for "all PDS applications."

## 3. Normative terminology

The suite shell MUST use precise capability language.

### 3.1 Repository

A source repository in the Paper Data Suite organization.

Repository existence does not prove that software is installable, installed,
launchable, compatible, or supported by the active suite release.

### 3.2 Distribution

An installable Python distribution identity such as `pds-core`, `pds-concord`,
or `pds-vitrine`.

### 3.3 Installed distribution

A distribution visible through the active Python environment's installed
distribution metadata.

Presence alone does not prove compatibility.

### 3.4 Launchable application

An installed component that exposes a teacher-facing executable boundary that
the active suite release explicitly supports launching.

### 3.5 Routing-capable module

A component exposing a valid Core `paper_data_suite.modules` profile.

This is a PDS2 routing/dispatch capability. It is not a generic declaration of
application membership in the suite.

### 3.6 Publication producer

A component exposing a supported `paper_data_suite.publication_producers`
profile.

Publication production is independent of routing and application launching.

### 3.7 Publication consumer

A component that consumes Core-governed publications under explicit consumer
contracts. A publication consumer need not be a routing module or publication
producer.

### 3.8 Suite-supported component

A component and version explicitly declared supported by the active suite
compatibility data.

### 3.9 Compatible component

A suite-supported component whose installed version, Python/Core requirements,
declared entry points, external prerequisites, and other compatibility checks
satisfy the active suite release.

### 3.10 Unavailable component

A suite-supported component that is not installed or lacks a required public
executable/provider surface.

Absence is not corruption.

### 3.11 Incompatible component

An installed component whose exact state does not satisfy the active suite
release's support declaration.

A component MAY occupy several capability categories at once.

## 4. Dependency direction

The v0.1.0 architectural dependency direction is:

```text
paper-data-suite
    |
    v
pds-core
```

Core is the only PDS repository that SHOULD be a required architectural runtime
dependency of the base suite shell.

Sibling applications MUST NOT become unconditional dependencies merely because
the shell can discover, diagnose, or launch them.

The base package architecture MUST NOT require dependency edges such as:

```text
paper-data-suite -> scoreform
paper-data-suite -> quillan
paper-data-suite -> pds-concord
paper-data-suite -> pds-meridian
paper-data-suite -> pds-vitrine
paper-data-suite -> pds-portia
```

as mandatory PDS-package dependencies.

Supported sibling distributions are separately installed components.

The reverse edge is prohibited:

```text
pds-core -X-> paper-data-suite
```

Core MUST remain independently usable.

Sibling modules likewise MUST NOT depend on the suite shell merely to
participate in Paper Data Suite. A cross-suite contract needed by multiple
repositories belongs in Core or another deliberately shared contract layer, not
in the shell package.

Dependency cycles among Core, the shell, and sibling modules are prohibited.

## 5. Suite-shell role

The shell owns suite-level composition and teacher convenience.

The intended relationship is:

```text
teacher
  |
  v
pds suite shell
  |
  +--> Core public services
  |
  +--> supported installed component boundary
          |
          +--> component-owned application/workflow
```

The shell MAY own:

- its package and version identity;
- its CLI and suite navigation;
- suite release compatibility declarations;
- installer/bootstrap and update planning;
- health-check orchestration;
- presentation of component discovery/readiness;
- launch orchestration;
- whole-workspace backup manifests and orchestration;
- genuinely shell-owned recovery metadata;
- non-sensitive suite UX preferences;
- combined installed-suite acceptance tooling;
- shell-specific diagnostics that obey this document; and
- shell documentation.

The shell MUST NOT become a home for domain semantics merely because several
modules need coordination.

## 6. Authority and ownership matrix

| Concern | Authoritative owner | Shell authority |
| --- | --- | --- |
| Workspace resolution, initialization, saved selection | Core | Delegate to Core |
| Classes and class metadata | Core | Delegate to Core |
| Rosters and roster-qualified student identity | Core | Delegate to Core |
| Shared standards and profiles | Core | Delegate to Core |
| Academic Periods | Core | Delegate to Core |
| PDS2 routing and route registrations | Core | Diagnose/orchestrate public services only |
| Retained source scan identity/provenance | Core | Diagnose/orchestrate public services only |
| Academic Work Registration | Core | Delegate to Core |
| Publication Records and shared catalogs | Core | Delegate to Core |
| ScoreForm OMR, attempts, scoring, native results | ScoreForm | Launch/delegate only |
| Quillan submissions, review, ratings, feedback | Quillan | Launch/delegate only |
| Concord Activities, Groups, Artifacts, review, moderation, scoring | Concord | Launch/delegate only |
| Meridian evidence policy, proficiency, Grades, reporting | Meridian | Launch/delegate only |
| Vitrine portfolio identity, curation, snapshots, editions, exports | Vitrine | Launch/delegate only |
| Portia behavior/support records and semantics | Portia | Launch/delegate when executable |
| Suite compatibility declaration | Suite shell | Own |
| Suite health orchestration | Suite shell | Own presentation/orchestration only |
| Suite application launching | Suite shell | Own launch orchestration only |
| Opaque whole-workspace backup manifest/orchestration | Suite shell | Own without semantic reinterpretation |
| Safe shell UX preferences | Suite shell | Own within privacy limits |

### 6.1 Core authority

Core remains authoritative for shared infrastructure, including where
implemented:

- identifier validation;
- workspace identity, resolution, initialization, and saved workspace
  configuration;
- classes and class metadata;
- rosters and roster-qualified student identity;
- standards;
- Academic Periods;
- module-qualified work references;
- PDS2 routing;
- route registrations and resolution;
- retained scan source identity and provenance;
- shared scan-review infrastructure;
- Academic Work Registration;
- Publication Records;
- shared publication catalogs;
- registry audit and recovery surfaces; and
- neutral cross-module contracts deliberately assigned to Core.

The shell MAY invoke Core public services that mutate Core-owned records. It
MUST NOT reproduce Core validation/storage rules and write equivalent files
itself.

### 6.2 ScoreForm authority

ScoreForm retains authority for ScoreForm-native concepts and workflows,
including assessment configuration, answer-sheet issuance/page meaning, OMR
interpretation, attempts, selected-response scoring, native results, result
manifests, and ScoreForm teacher workflows.

The shell MUST NOT score an answer sheet, choose an official attempt, or
construct ScoreForm-native result records.

### 6.3 Quillan authority

Quillan retains authority for writing assignments, response-page meaning,
submissions, review units, teacher judgments, Focus Standard ratings, feedback,
Quillan reports, result manifests, and Quillan teacher workflows.

The shell MUST NOT review writing, assign ratings, compose feedback, or
construct Quillan-native canonical records.

### 6.4 Concord authority

Concord retains authority for Activities, Sessions, Groups, Group Memberships,
Roles, Responsibilities, Artifact meaning, authorship and subject relationships,
Review, Moderation, Criterion Sets, Scales, Scores, result manifests, GroupPlan
semantics when implemented, and collaboration policy.

The shell MUST NOT form groups, interpret grouping bands, approve a GroupPlan,
infer Group Membership, or turn a planning signal into a canonical Concord
record.

### 6.5 Meridian authority

Meridian retains authority for academic evidence eligibility and selection
policy, attempt/reassessment policy, Grade-item membership, standards
proficiency, Grade policy, Academic Period aggregation, overrides, reporting
policy, and Meridian-native projection/report state.

The shell MUST NOT calculate proficiency, calculate Grades, choose official
attempts, or reinterpret producer evidence academically.

### 6.6 Vitrine authority

Vitrine retains authority for Portfolio and Portfolio Subject identity,
profiles, Candidate evaluation, Selection, Placement, curation, Composition,
Snapshot planning/materialization, Editions, exports, and portfolio-specific
audience/curation semantics.

The shell MUST NOT decide portfolio eligibility, selection, audience treatment,
or snapshot contents.

### 6.7 Portia authority

When executable Portia workflows exist, Portia remains authoritative for
behavior/support domain records and semantics, including Events, Accounts,
Observations, Reviews, Classifications, Hypotheses, Determinations, Responses,
Communications, Support Processes, Supports, Interventions, Implementation,
Fidelity, Follow-Up, Outcome, Reentry, Repair, and Portia privacy/retention
semantics.

The shell MUST NOT reinterpret Portia state as academic state, grading evidence,
a permanent learner label, or a shell-owned student dossier.

## 7. Direct canonical writes are prohibited

The shell MUST NOT directly write Core-owned or module-owned canonical records.

A prohibited direct write includes any operation in which shell code:

- constructs another component's canonical JSON record;
- duplicates another component's serializer or validation logic;
- infers another component's canonical path and persists into it;
- edits files under another component's canonical work tree as a substitute for
  a public owner service;
- writes directly to Core canonical registries;
- writes directly to derived Core or module catalogs;
- repairs another component's record itself; or
- falls back to filesystem mutation after the owner rejects an operation.

Visible paths do not grant ownership.

For example, these are not suite-shell write surfaces:

```text
classes/<class_id>/modules/scoreform/...
classes/<class_id>/modules/quillan/...
classes/<class_id>/modules/concord/...
```

The permitted pattern is:

```text
shell
  -> public owner service
      -> owner validation
      -> owner persistence
```

A failed owner operation remains failed. The shell MUST NOT "help" by recreating
the intended write itself.

Read access likewise MUST be bounded by the public contract needed for the
operation. Visibility of files on disk is not permission for the shell to parse
sensitive native records opportunistically.

## 8. Backup and restore are an opaque-custody exception

Whole-workspace backup is an intentional suite responsibility. It does not
transfer semantic ownership.

The architecture distinguishes:

```text
opaque byte custody
```

from:

```text
semantic record ownership
```

For backup purposes, the shell MAY enumerate and copy workspace files as opaque
bytes and MAY create a deterministic shell-owned backup manifest.

Backup logic MUST NOT:

- reinterpret canonical module records;
- normalize or rewrite module JSON;
- rebuild domain records;
- change canonical paths;
- infer semantic equivalence among records; or
- omit canonical files based on domain interpretation.

Restore likewise operates on opaque workspace bytes into an explicit safe
destination.

The shell MUST NOT:

- semantically merge backup JSON;
- rewrite module records during restore;
- invent selective domain restore semantics;
- overwrite the active workspace in place by default; or
- automatically select a restored workspace after restoration.

Exact containment, hashing, free-space, overwrite, exclusion, and recovery
mechanics belong to the dedicated backup/restore issues.

## 9. Core is the sole workspace authority

Core's workspace contract is authoritative.

The shell MUST use Core public workspace services for:

- resolving the current workspace;
- inspecting workspace status;
- validating or initializing a workspace;
- saving the selected workspace; and
- applying Core path and marker rules.

The shell MUST NOT create an independent canonical "selected workspace"
mechanism.

If shell settings later retain workspace-related convenience context, that
context MUST either delegate to Core's saved workspace configuration or be
explicitly nonauthoritative metadata that cannot override Core resolution.

Two competing canonical workspace selections are prohibited.

## 10. Existing entry-point semantics

### 10.1 `paper_data_suite.modules`

Core owns the entry-point group:

```text
paper_data_suite.modules
```

Its current contract is a routing/dispatch `ModuleProfile`.

It describes properties such as:

- module identity;
- display name;
- supported Core routing contract;
- supported QR schema;
- supported route-registration schema;
- dispatchable route statuses;
- route handler; and
- optional registration validator.

The suite shell MUST NOT redefine this group as a generic application registry.

A valid routing profile does not by itself prove:

- that a supported teacher menu exists;
- which console command should be launched;
- publication support;
- active suite-release compatibility;
- complete application readiness; or
- support for arbitrary suite operations.

Routing discovery MAY be used when the shell explicitly needs routing health or
routing compatibility.

### 10.2 `paper_data_suite.publication_producers`

The entry-point group:

```text
paper_data_suite.publication_producers
```

is a distinct publication-producer integration surface.

Publication-producer status does not imply routing capability, launchability,
consumer status, or suite compatibility.

### 10.3 No single entry-point group defines the suite

ScoreForm, Quillan, and Concord currently expose routing profiles. Meridian and
Vitrine are executable applications without routing profiles. Portia is not yet
executable.

The shell therefore MUST model PDS component capabilities independently rather
than treating membership in one entry-point group as membership in the suite.

### 10.4 Future shared providers

This issue does not define a new provider API.

A provider contract intended for several PDS repositories SHOULD be defined in
Core or another deliberately neutral shared layer. Sibling modules MUST NOT
need a runtime dependency on `paper-data-suite` merely to expose shared
capabilities.

Later provider/inventory work MUST preserve this dependency direction.

## 11. Application discovery and launch boundary

Future suite launching MUST use explicit suite compatibility metadata plus
installed distribution/public executable metadata.

Launchability MUST NOT be inferred from:

- repository name;
- import-package name;
- routing-profile existence;
- filesystem directory scanning;
- private sibling imports; or
- an executable that merely has an expected-looking name.

The future compatibility declaration SHOULD identify at least:

- distribution identity;
- exact supported version;
- expected teacher-facing executable or console entry point;
- optional routing-profile expectation;
- optional publication-producer expectation;
- Python range;
- Core compatibility;
- external prerequisites; and
- support/compatibility status.

Supported sibling applications SHOULD be launched out of process through the
declared public executable boundary.

Conceptually:

```text
pds
  -> declared supported executable
      -> child application process
```

The shell MUST NOT make private imports such as these part of its integration
contract:

```python
from quillan.cli import main
from scoreform.cli import main
```

Out-of-process launching preserves application ownership, module-global-state
isolation, `SystemExit` isolation, and clearer failure handling.

Exact process mechanics belong to the application-launch issue.

## 12. Failure isolation

The shell MUST remain useful in partial and partially broken installations.

Failures MUST be classified using the narrowest accurate scope.

### 12.1 Shell-fatal failure

A failure that prevents the shell itself from performing even dependency-light
operations such as help/version or basic environment inspection.

This category SHOULD be rare.

### 12.2 Core/workspace-blocking failure

A Core or workspace problem that prevents operations requiring valid Core
state.

It MUST NOT automatically prevent operations that do not require a workspace.

### 12.3 Component-local failure

A missing, incompatible, malformed, or broken optional component.

It MUST NOT disable unrelated healthy components or unrelated shell functions.

### 12.4 Operation-local failure

A failure limited to one requested operation, such as a module launch returning
a nonzero status.

Control SHOULD return to the shell with safe, actionable reporting.

### 12.5 Warning/degraded state

A condition that reduces functionality without invalidating the requested
operation.

The shell MUST NOT silently convert errors into success.

Examples:

- Quillan being absent must not block workspace diagnostics.
- Vitrine being incompatible must not cause ScoreForm to be reported unhealthy.
- A malformed optional entry point must be reported as a problem with that
  component/integration, not as an unconditional shell crash.
- A failed owner write must not trigger shell-side fallback persistence.
- A corrupt workspace may block workspace-dependent workflows while
  environment/version diagnostics remain available where possible.

## 13. Cross-owner workflows are not fake transactions

The shell MUST NOT claim that unrelated component writes form one atomic
transaction unless an explicit shared contract actually provides that
guarantee.

For an orchestration spanning owners, the shell MAY:

- preview;
- sequence;
- invoke;
- collect owner-produced results;
- stop safely after failure; and
- provide recovery guidance.

It MUST NOT claim rollback of another component's successful write unless that
owner exposes and successfully performs a supported rollback, correction, or
supersession operation.

This rule applies to setup, scan processing, planning, maintenance, and future
cross-module workflows.

## 14. Compatibility and version-support policy

### 14.1 Python baseline

The current suite baseline is Python 3.11 or newer.

The package-foundation issue will define exact distribution metadata. A later
audited issue MAY deliberately raise this floor, but implementation MUST NOT do
so accidentally.

### 14.2 Core compatibility line

The current executable PDS components are aligned to:

```text
pds-core>=0.6,<0.7
```

Phase 1 planning intentionally keeps additive shared infrastructure on the Core
0.6.x line where feasible.

The shell MUST NOT force an unnecessary Core 0.7 transition.

### 14.3 Package metadata compatibility is not suite qualification

A broad dependency range does not mean every version combination inside that
range is suite-qualified.

The distinction is:

```text
package metadata compatibility
!=
suite-qualified release combination
```

Each suite release MUST identify exact tested/supported component combinations
through its machine-readable compatibility declaration.

### 14.4 Pre-1.0 compatibility is explicit

Because PDS components are pre-1.0, the shell MUST NOT infer compatibility from:

- same major version;
- newest installed version;
- nearest minor version;
- package-name match; or
- successful pip dependency resolution.

Compatibility MUST be explicit and fail closed.

### 14.5 Unsupported versions

An installed but undeclared version MUST be represented honestly as unsupported
or incompatible.

The shell MUST NOT:

- silently upgrade it;
- silently downgrade it;
- launch it as though it were supported;
- select a "closest" supported version; or
- substitute one version for another.

Later bootstrap/update tooling MAY propose explicit corrective actions.

### 14.6 Partial installation is first-class

A supported component being absent is a normal representable state:

```text
supported but not installed
```

It is not automatically a shell-fatal error.

### 14.7 Independent release identities

The suite shell, Core, and sibling modules retain independent versions.

A suite release declares a tested composition. It does not replace component
version identity.

## 15. Group-planning boundary

The program architecture establishes:

```text
Meridian
   -> Core grouping-signal interchange
       <- Concord
```

This is a concrete example of why the shell is not a domain-policy owner.

When the relevant contracts exist:

- Core owns the neutral grouping-signal interchange;
- Meridian owns academic derivation and interpretation;
- Concord owns planning strategies, approval, and canonical Group and Group
  Membership records;
- the shell MAY expose health, discovery, and guided navigation.

The shell MUST NOT:

- derive academic bands;
- decide what a band means;
- create a grouping strategy;
- approve a GroupPlan;
- turn a signal into Group Membership; or
- copy signal values into shell settings, ordinary logs, or attention
  summaries.

No grouping functionality is implemented by this architecture issue.

## 16. Suite settings boundary

Suite settings MAY retain safe, non-domain UX state such as:

- recent application choice;
- display/navigation preferences;
- other explicitly noncanonical convenience state.

Suite settings MUST NOT store:

- rosters;
- student names or identifiers;
- scores;
- answers;
- standards ratings;
- feedback;
- raw scans;
- writing evidence;
- portfolio contents;
- behavior/support details;
- publication manifests;
- grouping-signal values; or
- shadow copies of Core/module records.

Workspace selection remains Core-authoritative.

## 17. Privacy and diagnostics boundary

The shell operates over workspaces that may contain sensitive educational
records.

Implementations MUST preserve these defaults:

- repository examples and fixtures are synthetic;
- no telemetry is enabled by default;
- no remote account is required;
- the shell does not implement cloud synchronization;
- health checks read only what is necessary;
- ordinary logs do not reproduce student data;
- full QR payloads are not logged by default;
- raw evidence, feedback, scores, behavior/support bodies, and portfolio bodies
  are not copied into ordinary diagnostics;
- sensitive data is not copied outside the canonical workspace merely for
  convenience.

Errors SHOULD identify component, operation, safe path context where useful,
and remediation without dumping sensitive record contents.

A later troubleshooting-bundle design MUST remain consistent with these
defaults.

## 18. Direct component interfaces remain first-class

The suite shell is an additional entry point, not a replacement for component
CLIs.

Existing owner-provided direct interfaces remain available according to their
own distributions, including current commands such as:

```text
pds-core
core
scoreform
quillan
concord
meridian
vitrine
```

The shell MUST NOT require advanced, diagnostic, scripted, or recovery
operations to pass through `pds`.

The guiding principle is:

```text
guided composition over exact owner services
```

not:

```text
removal of exact owner interfaces
```

## 19. Rules for future shared contracts

A future capability SHOULD be assigned using this decision sequence:

1. Is it authoritative domain meaning for one module?
   - Keep it in that module.
2. Is it shared identity, workspace infrastructure, routing, publication
   governance, or another neutral cross-module contract?
   - Prefer Core.
3. Is it only suite-level composition, compatibility, health presentation,
   launching, backup orchestration, or safe UX state?
   - It may belong in the shell.
4. Would implementing it in the shell require sibling modules to depend on the
   shell or require the shell to parse/write sibling-native records?
   - The design is presumptively wrong and MUST be reconsidered.

The shell MUST NOT become a convenient dumping ground for contracts whose true
owner has not been decided.

## 20. Implementation checklist for later suite issues

Before adding a suite-shell capability, verify all of the following:

- [ ] The authoritative owner is named.
- [ ] The shell needs only a public owner contract.
- [ ] No sibling private implementation import is required.
- [ ] No direct canonical Core/module write is required.
- [ ] Workspace behavior delegates to Core.
- [ ] Routing and publication capabilities are not conflated.
- [ ] Application launchability is declared separately from routing.
- [ ] Optional component absence can be represented without global failure.
- [ ] Exact compatibility is declared rather than inferred.
- [ ] Cross-owner failure/rollback claims are truthful.
- [ ] Shell persistence contains no sensitive domain shadow copy.
- [ ] Backup behavior, if involved, treats module bytes opaquely.
- [ ] Direct component CLIs remain usable.
- [ ] New shared provider contracts do not create a dependency on the shell.

If any item cannot be satisfied, implementation MUST stop and the architecture
must be revisited explicitly.

## 21. Non-goals of this contract

This document does not itself define or implement:

- the `paper-data-suite` package metadata;
- the `pds` runtime;
- a new generic component-provider API;
- the compatibility-manifest wire format;
- installation/update scripts;
- `pds doctor`;
- application-launch process mechanics;
- workspace setup UX;
- backup-manifest wire format;
- restore mechanics;
- suite-settings storage format;
- grouping-signal contracts;
- shared Core provider/inventory APIs; or
- module-specific business logic.

Those concerns belong to their dedicated issues, subject to the boundaries in
this document.
