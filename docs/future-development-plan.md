# Paper Data Suite — Post-Current-Plan Future Development Roadmap

**Planning horizon:** after completion of the current Paper Data Suite development plan  
**Earliest likely implementation window:** winter break 2026–2027, except for work explicitly classified below as safe, non-canonical pre-work  
**Assumption:** the existing development plan is complete before this roadmap begins. Features already in that plan are not repeated here as future work.  
**Primary design constraint:** no future convenience feature is worth risking an active school-year workspace, silently changing an existing schema, weakening authority boundaries, or creating an upgrade path that cannot be independently verified.

---

## 1. Purpose

This document defines the next likely development program for Paper Data Suite after the current pilot-readiness, teacher-workflow, interoperability, Meridian, Portia, Vitrine, Concord, ScoreForm, Quillan, Core, and suite-shell plans are complete.

The emphasis changes at that point. The current plan is primarily about making the suite usable, safe, interoperable, and operational for daily teaching. The next program should focus on **instructional leverage, longitudinal usefulness, and reduced recurring teacher workload**.

The central future loop should become:

```text
plan instruction
    ↓
create learning activity / assessment
    ↓
collect evidence
    ↓
review and interpret evidence
    ↓
respond to student needs
    ↓
curate meaningful work
    ↓
adjust future instruction
    ↓
archive / retain appropriately
```

The existing suite already covers most of the middle of that loop. The major missing domains are:

1. **instructional and curriculum planning** — proposed new module `pds-atlas`;
2. **student-owned goals, check-ins, and conference cycles** — proposed new module `pds-compass`;
3. deeper **instructional analytics** in existing modules;
4. stronger **operational resilience** around backups, multi-device use, and school-year rollover; and
5. eventually **archival/retention lifecycle** through the already-contemplated `pds-sunset`, intentionally deferred until near the end of the school year.

---

# 2. Non-negotiable compatibility and workspace-safety policy

Future work should be classified before implementation according to the risk it poses to the live workspace.

## 2.1 Risk Class A — safe pre-work during the school year

This work may be done before winter break because it should not mutate a real workspace or alter existing canonical data contracts.

Examples:

- architecture documents;
- ADRs;
- research and requirements analysis;
- milestone and issue planning;
- new repository/package scaffolding whose imports perform no I/O;
- synthetic fixtures;
- standalone JSON Schemas that are not yet wired into production storage;
- immutable Python models tested only against synthetic fixtures;
- pure calculation functions;
- read-only analysis prototypes over exported synthetic snapshots;
- UI/menu mockups;
- documentation-only capability catalogs;
- tests against temporary directories;
- release compatibility planning;
- new-module proof-of-concept storage under test-only temporary roots;
- benchmark and performance experiments using synthetic data.

**Rule:** Risk Class A work must not write to the active PDS workspace, change an existing current pointer, migrate data, alter a released wire format, or require an unreleased Core behavior in order for currently released modules to continue working.

## 2.2 Risk Class B — additive runtime work requiring explicit qualification

This work may be backward compatible, but it writes new runtime state or changes operational behavior. It should normally wait for a dedicated milestone and installed-suite qualification.

Examples:

- a new module writing under a new module-owned workspace root;
- new optional records that do not alter existing schemas;
- new suite settings;
- advisory session/lease markers;
- new read-only indexes or caches;
- backup-retention metadata;
- optional analytics snapshots;
- new entry points or module capabilities;
- new versioned schemas that coexist with prior versions;
- new Core contracts that are strictly additive.

Risk Class B work requires:

1. exact ownership documentation;
2. explicit no-migration or migration behavior;
3. source and installed-wheel tests;
4. fresh-workspace tests;
5. pre-existing-workspace tests;
6. rollback/recovery analysis;
7. path-safety tests;
8. cross-platform qualification where relevant; and
9. confirmation that older modules remain operable when the new component is absent.

## 2.3 Risk Class C — schema, path, migration, or destructive behavior

This class should not be introduced casually during the school year.

Examples:

- changing the meaning of an existing field;
- removing or renaming canonical fields;
- changing canonical directory layout;
- rewriting existing records in place;
- automatic migration of active workspaces;
- changing a current-pointer contract incompatibly;
- deleting historical data;
- automatic pruning of canonical records;
- changing publication or identity semantics;
- changing a Core contract in a way that forces synchronized upgrades;
- making a new module authoritative for records previously owned elsewhere.

Risk Class C work requires a separate migration milestone, versioned source/target schemas, dry-run preview, backup prerequisite, immutable migration record, recovery plan, and exact installed-suite acceptance.

**Default policy:** if a future feature can be implemented as a new versioned record or read-only projection, prefer that over modifying an existing wire shape.

---

# 3. Program-level design principles

## 3.1 Preserve current repository authority

Future functionality should extend the existing ownership model rather than collapse it.

| Repository | Continues to own |
| --- | --- |
| `pds-core` | shared workspace authority, classes/rosters, standards, Academic Periods, PDS2 routing, shared identities/contracts, registrations/publications, neutral interchange |
| `pds-paper-data-suite` | suite orchestration, installation/compatibility, health, backup/restore, cross-module navigation and operational presentation |
| `pds-scoreform` | selected-response/OMR assessment evidence and instrument-specific scoring state |
| `pds-quillan` | writing assignments, submissions, review, feedback, writing-specific observations/ratings |
| `pds-concord` | collaborative activities, plans, groups, artifacts, collaboration evidence, review/moderation/scoring |
| `pds-meridian` | academic evidence interpretation, standards proficiency, Grade policy/previews, reporting snapshots, academic analysis |
| `pds-vitrine` | portfolio curation, selections, compositions, snapshots/editions/exports |
| `pds-portia` | behavior/support events, observations, responses, communications, supports, implementation/fidelity, follow-up/outcomes |
| `pds-atlas` (proposed) | curriculum and instructional planning intent |
| `pds-compass` (proposed) | student goal/check-in/conference cycles |
| `pds-sunset` (future) | archival/retention/end-of-year lifecycle when eventually implemented |

## 3.2 Prefer references over duplicated records

Future modules should reference existing authorities using stable IDs and digests where appropriate. They should not copy another module's canonical record merely for convenience.

Examples:

```text
Atlas PlannedEvidence -> references intended assessment/work type
Atlas ActualWorkLink -> references Core Academic Work identity
Compass EvidenceReference -> references authorized producer/Meridian/Vitrine evidence
Vitrine Selection -> references source publication/evidence
Meridian interpretation -> references producer evidence without rewriting it
```

## 3.3 Read-only analytics should be easier to add than new canonical judgment

A useful future bias:

```text
read-only derived analysis
    < lower risk
new canonical teacher-authored record
    < moderate risk
new automated educational judgment
    < high risk and usually undesirable
```

Paper Data Suite should continue to support teacher judgment rather than silently making consequential decisions.

---

# 4. Future enhancements to existing repositories

## 4.1 Suite shell — Operational Resilience and Workspace Safety

### Proposed future milestone

**`pds-paper-data-suite v0.3.0 — Operational Resilience, Backup Policy, and Multi-Device Safety`**

### Why this matters

Once the suite is being used daily, failures are more likely to come from ordinary operational hazards than from missing domain features:

- forgetting to make a backup;
- allowing backups to accumulate until storage is full;
- opening the same cloud-synchronized workspace on two computers;
- starting work before cloud sync has completed;
- not knowing whether the latest backup verified successfully;
- restoring a backup but forgetting to re-run health checks.

### Proposed features

#### A. Named backup policies

Add suite-owned configuration for backup policy without changing the backup archive format.

Example conceptual policy:

```yaml
policy_id: teacher_daily
retention:
  daily: 7
  weekly: 4
  monthly: 6
destinations:
  - portable_ssd
  - google_drive_backup
verification: required
```

The policy should describe orchestration only. Existing backup creation/verification remains authoritative for the actual backup contents.

#### B. Backup inventory and status

Teacher-facing view:

```text
Portable SSD
Last backup: 2026-10-18 16:42
Verified: Yes
Age: 1 day
Retained generations: 8
Oldest retained: 2026-09-01

Google Drive backup folder
Last backup: 2026-10-18 16:49
Verified locally before sync: Yes
Age: 1 day
```

Do not claim remote cloud upload completion unless the provider exposes a reliable supported status that PDS explicitly checks.

#### C. Guarded pruning

Pruning should operate only on completed, independently verified PDS backup directories recognized by exact manifest identity.

Required behavior:

- preview before deletion;
- never prune the only verified backup;
- never prune an unrecognized folder;
- never prune a backup that failed verification merely to satisfy retention count;
- preserve pinned backups;
- record what was removed without logging student data;
- support `--dry-run`;
- require explicit confirmation for destructive pruning unless a pre-approved policy explicitly authorizes it.

#### D. Advisory multi-device workspace session marker

Purpose: warn, not pretend to provide distributed locking.

A small suite/Core-coordinated marker could record:

- machine identifier or safe machine label;
- suite version;
- session start;
- last activity timestamp;
- clean-close timestamp if known.

On another computer:

```text
This workspace may still be active on SCHOOL-PC.
Last recorded activity: 14 minutes ago.

Before continuing:
1. confirm PDS is closed on the other computer;
2. confirm OneDrive/other sync reports current state;
3. confirm this computer has received the latest files.
```

Invariant:

```text
session marker != distributed lock
stale marker != proof another session is active
absence of marker != proof another session is inactive
```

#### E. Cloud-sync safety diagnostics

Where Windows exposes reliable filesystem state, diagnose:

- offline/placeholding files inside a workspace expected to be fully local;
- inaccessible/hydration-failing files;
- obvious sync-conflict filenames;
- backup destination nested inside workspace;
- workspace nested inside backup destination;
- unexpected duplicate copies of canonical-looking files.

No automated conflict resolution.

### Risk classification

- policy/UX design: **A**;
- backup inventory read-only tooling: **A/B** depending on implementation;
- named settings and session markers: **B**;
- automatic destructive pruning: **B with strong safeguards**, never C-style canonical deletion.

---

## 4.2 Core — School-Year Rollover and Structural Reuse

### Proposed future milestone

**`pds-core v0.7.x or later additive line — School-Year Rollover Planning`**

Whether this belongs on Core 0.6 or a later compatibility line should be decided only after the current plan is released. Do not force a Core major/minor compatibility break merely to add rollover.

### Goal

Allow the teacher to reuse **structure** from the prior school year without carrying forward student history or pretending the new year is a continuation of the old roster.

### Proposed workflow

```text
Select source school year: 2026–2027
Create target school year: 2027–2028

Propose carry-forward:
[x] course/class configuration templates
[x] standards profiles
[x] Academic Period structure templates
[x] non-student settings
[ ] roster membership
[ ] student identifiers
[ ] Academic Work
[ ] publications
[ ] module records
```

The teacher then maps prior class structures to new class identities.

### Required invariants

```text
new school year != revision of old school year
new class != renamed old class
new roster != copied prior roster
structural reuse != student-history migration
```

### Data-safety design

Prefer a pure planning service first:

```text
source configuration
-> rollover proposal
-> explicit teacher edits
-> preview
-> fresh create-only writes
```

Never mutate the source year.

### Risk classification

- rollover planning model/tests: **A**;
- fresh create-only target-year writes: **B**;
- any attempt to rewrite existing years/classes: **C and not recommended**.

---

## 4.3 ScoreForm — Assessment Instrument Analytics

### Proposed future milestone

**`pds-scoreform v0.12.0 — Item Analytics and Alternate Assessment Forms`**

### Ownership rationale

These analytics describe the **assessment instrument and response distribution**, not overall standards proficiency or Grade policy. They therefore belong in ScoreForm, while Meridian remains the consumer for broader academic interpretation.

### Feature set

#### A. Item difficulty / success rate

For each question:

- count eligible attempts under an explicitly selected analysis population;
- number correct;
- percentage correct;
- omissions;
- invalid/multiple-mark states;
- response-option distribution.

Do not silently choose which student attempt is official. The teacher must select the analysis population/policy or use an explicitly documented view such as "all scored attempts."

#### B. Distractor analysis

Example:

```text
Question 14 — 26 eligible responses
A: 2 (7.7%)
B*: 8 (30.8%)
C: 14 (53.8%)
D: 2 (7.7%)
Omitted: 0

Observation:
Distractor C attracted substantially more responses than the keyed answer.
```

ScoreForm should report the distribution, not automatically declare the item defective.

#### C. Small-sample warnings

Statistical displays should expose sample size and avoid false precision.

Example states:

```text
N < 10: descriptive only; do not show discrimination estimate
N 10–19: caution
N >= 20: standard descriptive analytics available
```

Exact thresholds should be documented and reviewable rather than implied as universal research rules.

#### D. Optional discrimination/reliability measures

Only if methodologically appropriate and well documented:

- point-biserial/item-total relationships;
- KR-20 or similar reliability for suitable dichotomous instruments;
- form-level descriptive statistics.

These should be explicitly optional and accompanied by assumptions/limitations.

#### E. Alternate forms

Add a stable assessment family with fresh form identities:

```text
Assessment Family: Macbeth Act I Quiz
  Form A
  Form B
  Form C
```

Each form may have:

- its own answer key;
- its own question order;
- optional item-equivalence mapping;
- fresh issuance/page/route identities.

Do not infer equivalence merely because forms share a family.

### Risk classification

- pure read-only analytics over existing records: **A** if no cache/write is created;
- optional derived analytics cache: **B**;
- alternate-form records: **B** using new versioned records;
- modifying existing assignment wire shapes in place: **C; avoid**.

---

## 4.4 Quillan — Writing Revision Cycles and Reusable Feedback

### Proposed future milestone

**`pds-quillan v0.11.0 — Revision Lineage, Feedback Library, and Growth-Oriented Writing Workflows`**

### A. Explicit revision lineage

Quillan should distinguish revisions rather than treating a later submission as a silent replacement.

Conceptual model:

```text
Writing Assignment
  └─ Student Submission Series
       ├─ Draft 1
       │   └─ Review / feedback
       ├─ Draft 2
       │   └─ Review / feedback
       └─ Final
```

Suggested new concepts:

- `SubmissionSeries` or equivalent student-assignment revision context;
- immutable `SubmissionRevision` identity;
- explicit `revises_submission_id` relationship;
- teacher-defined revision purpose (`draft`, `revision`, `final`, custom label);
- revision reflection;
- optional teacher request for revision;
- exact lineage in manifests where publication policy permits.

Required distinctions:

```text
later revision != automatically better
revision != replacement of history
teacher feedback != proof student acted on feedback
changed text != demonstrated growth
final != necessarily highest-rated evidence
```

### B. Revision comparison

Read-only comparison could show:

- added/removed text regions for digital/plain-text sources where deterministic comparison is possible;
- changed teacher ratings;
- changed basic-requirement states;
- changed standards observations;
- feedback carried forward or resolved;
- student reflection on revisions.

Avoid automatic qualitative claims such as "improved argument" unless the teacher records that judgment.

### C. Teacher feedback snippet library

Teacher-owned reusable text, separated from student-specific feedback history.

Possible structure:

```text
Feedback Library
  Evidence
    - Integrate quotation into your own sentence.
    - Explain how the evidence supports the claim.
  Organization
    - Make the paragraph's controlling idea explicit.
  Revision
    - Re-read the final two sentences for redundancy.
```

Features:

- categories/tags;
- teacher-authored snippets;
- immutable or revisioned snippet history;
- quick insert during review;
- edit after insertion before committing student feedback;
- no automatic selection based on student text;
- no AI-generated judgment required.

### D. Assignment-level revision policy

Teacher can configure:

- whether multiple revisions are expected;
- revision labels;
- due windows;
- whether old feedback remains visible in the review workflow;
- whether a later publication includes one revision or a bounded revision series.

### Risk classification

- feedback library in an isolated new teacher-owned root: **B**;
- read-only revision-comparison prototype over synthetic records: **A**;
- canonical revision-series records: **B** with new versioned contracts;
- changing old submission meaning in place: **C; do not do**.

---

## 4.5 Concord — Repeated Grouping Constraints and Rotation History

### Proposed future milestone

**`pds-concord v0.4.0 — Teacher Constraints, Collaboration Rotation, and Group-History Diagnostics`**

### Why later, not in the current plan

The current GroupPlan work deliberately stays bounded: manual, imported, random, and neutral signal-based planning. More elaborate group-history rules should wait until those workflows are stable in real classroom use.

### Proposed capability

Teacher-controlled constraints, not opaque optimization.

Examples:

```text
avoid exact group repeated from last Activity
avoid same pair more than 2 times in last 5 Activities
keep Student A and Student B together for this plan
keep Student C and Student D separate for this plan
place Student E manually before automatic distribution
rotate facilitator role where possible
```

### Explicit exclusions

Do not infer or optimize on:

- race/ethnicity;
- disability;
- IEP/504 status;
- gender;
- language status;
- socioeconomic status;
- personality type;
- inferred friendship/social relationships;
- behavior-risk scores;
- permanent academic-ability labels.

If a teacher needs a sensitive placement decision, it should be an explicit teacher placement, not an algorithmic inferred feature.

### Group-history diagnostics

Read-only view:

```text
Student pair: A / B
Together in last 10 collaborative Activities: 4
Most recent: Activity 2026-10-11

Student A roles in last 8 Sessions:
Facilitator: 3
Recorder: 2
Reporter: 1
No assigned role: 2
```

### Planner semantics

The algorithm can solve deterministic constraints, but must describe failures honestly:

```text
No arrangement satisfies all requested constraints at group size 4.
Conflicting constraints:
- keep A/B together
- keep B/C together
- keep A/C separate
```

No claim of "optimal group" unless an explicit mathematical objective is defined, bounded, and transparently reported.

### Risk classification

- history diagnostics: **A** if pure read-only;
- draft constraint models in fixtures: **A**;
- canonical teacher constraint records / GroupPlan extensions: **B** using new versions;
- changing existing applied GroupMembership records: **C; not needed**.

---

## 4.6 Meridian — Instructional Analytics and Policy Sandbox

### Proposed future milestone

**`pds-meridian v0.4.0 — Standards Coverage, Longitudinal Analysis, and Policy Simulation`**

This is likely the highest-impact post-plan enhancement to an existing module.

### A. Standards evidence coverage

Meridian should answer not just "what is the current calculated proficiency?" but:

> What standards have actually accumulated usable evidence, for which students, and how recently?

Per-standard fields could include:

- durable standard ID;
- standard text/short label resolved through Core;
- number of Grade Items intentionally associated;
- number of students with operative evidence;
- number with pending/unmapped evidence;
- number with no evidence;
- most recent operative evidence date;
- diversity of evidence producers (ScoreForm/Quillan/Concord);
- evidence-count distribution;
- optional teacher-defined coverage expectation.

Example:

```text
RL.CR.9–10.1
Students with operative evidence: 26/27
Grade Items contributing: 7
Most recent evidence: 4 days ago
Producer mix: ScoreForm + Quillan + Concord
Coverage state: Broad

W.RW.9–10.7
Students with operative evidence: 11/27
Grade Items contributing: 1
Most recent evidence: 49 days ago
Coverage state: Thin
```

Coverage labels should be teacher-configurable or rule-explicit, not universal claims.

### B. Planned-versus-observed coverage hook for future Atlas

Meridian should expose a neutral read-only coverage result that Atlas can reference later.

```text
Atlas planned standard emphasis
!= Meridian observed evidence coverage
```

Atlas should not become the owner of proficiency, and Meridian should not become the owner of curriculum intent.

### C. Longitudinal proficiency/result trends

Support bounded comparisons only when the relevant policy/scale context is compatible or when the difference is explicitly explained.

Possible views:

- student-by-standard over time;
- class distribution over time;
- Grade Item sequence;
- evidence recency;
- changed calculation after reassessment;
- period-to-period comparison.

Required language:

```text
increased calculated proficiency != proven learning growth
correlation with instructional event != causation
changed policy != changed student performance
```

### D. Policy sandbox / what-if analysis

Allow teacher to simulate without activating:

- different Grade category weights;
- different reassessment replacement rules;
- different attempt-selection policies;
- different proficiency aggregation settings;
- different missing-work treatment;
- alternate Grade conversions.

Sandbox invariants:

```text
simulation != active policy
simulation != stored Grade snapshot
simulation != official school grade
```

A simulation should be explicitly marked, disposable by default, and reproducible from an exact input/policy snapshot if saved.

### E. Instructional planning diagnostics

Possible teacher questions Meridian should eventually answer:

- Which standards have the thinnest evidence this Academic Period?
- Which standards have not been assessed recently?
- Which standards rely almost entirely on one producer or one Grade Item?
- Which students have insufficient evidence rather than low proficiency?
- Which Grade Items contribute unusually broad or unusually narrow standards evidence?
- Where did a recent reassessment materially change the interpretation?

This is advisory analysis only.

### Risk classification

- pure coverage/trend calculations: **A**;
- saved derived analytics snapshots: **B**;
- sandbox save/share: **B**;
- modifying active policy during simulation: **C-like behavior and prohibited**.

---

## 4.7 Vitrine — Portfolio Edition Comparison and Growth Narrative Support

### Proposed future milestone

**`pds-vitrine v0.4.0 — Edition Comparison and Curator Growth Views`**

### Capability

Compare two immutable portfolio Editions without mutating either.

Show:

- selections added;
- selections removed;
- selections replaced;
- section movement;
- changed annotations;
- changed student reflections;
- changed composition requirements;
- source-publication revision/supersession state;
- build omissions;
- audience-context changes;
- profile revision changes;
- snapshot verification state.

Example:

```text
Improvement Portfolio
Edition 2 -> Edition 5

Added:
- Literary Analysis Revision 2
- Seminar Reflection

Replaced:
- Argument Draft 1 -> Argument Final

Student reflection changed: Yes
Audience context changed: No
Profile revision: 3 -> 4
```

### Growth narrative support

Vitrine may help assemble evidence for a teacher/student-authored growth narrative, but must not infer growth automatically.

```text
later Edition != better Edition
replacement != improvement
more items != stronger portfolio
```

### Risk classification

Mostly **A** if implemented as pure read-only comparison over immutable records. Optional saved comparison notes would be **B**.

---

## 4.8 Portia — Descriptive Support and Outcome Review

### Proposed future milestone

**`pds-portia v0.4.0 — Descriptive Support Review and Follow-Up Analysis`**

### Purpose

Help the teacher review what was planned, what was actually implemented, what fidelity was recorded, and what outcomes/follow-up were documented—without causal or punitive inference.

Possible views:

```text
Support: Beginning-of-class check-in
Planned implementations: 15
Recorded implementations: 12

Fidelity records:
Consistent: 8
Partial: 3
Unknown: 1

Follow-up outcome records:
Improved: 6
Mixed: 2
Unchanged: 4
```

### Useful questions

- Are planned supports actually being implemented?
- Is fidelity consistently unknown, indicating a documentation problem?
- Are follow-ups overdue?
- Are outcomes mixed enough that the teacher should review the support plan?
- Is one support process accumulating many responses but few implementation records?

### Non-negotiable semantics

```text
association != causation
implementation != fidelity
fidelity != effectiveness
outcome record != proof support caused outcome
frequency != culpability
more Event records != worse student
```

### Risk classification

Read-only descriptive analysis can largely be **A**. Any saved analytic judgment should be a new explicit teacher-authored record (**B**) rather than an automatically inferred canonical conclusion.

---

# 5. New module: `pds-atlas` — Curriculum and Instructional Planning

## 5.1 Why Atlas should be a separate module

Instructional planning is a distinct canonical domain. It should not be hidden inside Core, Meridian, or the suite shell.

- Core owns shared structural authority such as standards, classes, rosters, Academic Periods, and Academic Work infrastructure.
- Meridian owns interpretation of evidence.
- ScoreForm/Quillan/Concord own produced evidence.
- Atlas would own the teacher's **instructional intent before evidence exists**.

This creates a clean relationship:

```text
Atlas: what I intend to teach / ask students to do
Producer modules: what students actually do and submit
Meridian: what the evidence supports under explicit policy
Atlas: how I adjust later instruction
```

## 5.2 Proposed package/repository identity

```text
Repository: Paper-Data-Suite/pds-atlas
Distribution: pds-atlas
Import package: atlas
CLI: atlas
```

Exact names should be checked before repository creation, but `pds-atlas` is currently a strong conceptual fit.

## 5.3 Explicit scope

Atlas should own:

- Course Plan;
- Unit;
- Unit Revision;
- Essential Question;
- Instructional Objective / Learning Target;
- Standard Intent / Planned Standard Emphasis;
- Lesson Sequence;
- Lesson Plan;
- Instructional Resource Reference;
- Planned Activity;
- Planned Evidence;
- Planned Assessment Window;
- Pacing/Schedule Entry;
- Lesson/Unit Reflection;
- Actual Work Link to Core Academic Work after implementation;
- unit-level status and revision history;
- optional planned-versus-actual instructional timeline.

Atlas should **not** own:

- standards text or standard identity (Core);
- class roster (Core);
- student assessment evidence (ScoreForm/Quillan/Concord);
- proficiency or Grade (Meridian);
- portfolio selection (Vitrine);
- behavior/support records (Portia);
- archival lifecycle (Sunset);
- school LMS content or official curriculum authority unless imported as a reference.

## 5.4 Proposed conceptual record model

### CoursePlan

Purpose: one teacher-owned instructional plan for a course/school-year/class family.

Candidate fields:

```text
course_plan_id
schema_version
school_year_id
course_label
title
description
status
created_at
created_by
supersedes_course_plan_id?
source_curriculum_refs[]
default_period_length_minutes?
notes?
```

Avoid embedding a roster.

### Unit

```text
unit_id
course_plan_id
schema_version
title
sequence_number?
status
estimated_instructional_days?
academic_period_refs[]
essential_questions[]
big_ideas[]
standard_intents[]
resource_refs[]
assessment_intents[]
created_at
supersedes_unit_id?
```

### StandardIntent

Represents instructional intent, not evidence or proficiency.

```text
standard_id              # Core durable standard reference
emphasis                  # e.g. introduce / develop / emphasize / assess
planned_evidence_kinds[]
notes?
```

Invariant:

```text
planned standard != assessed standard
planned standard != evidence exists
planned standard != student proficiency
```

### LessonPlan

```text
lesson_plan_id
unit_id
lesson_date?
sequence_number?
title
duration_minutes
learning_objectives[]
standard_intents[]
materials[]
activity_steps[]
checks_for_understanding[]
planned_evidence[]
homework_or_extension?
accommodations_notes?     # should avoid embedding sensitive student-specific records
reflection_prompt?
status
revision
```

Student-specific legally sensitive accommodation records should not be copied into Atlas. The plan may contain generic differentiation strategies or authorized references where appropriate.

### PlannedEvidence

Purpose: state what evidence a lesson is expected to create and which PDS capability could capture it.

```text
planned_evidence_id
evidence_purpose
preferred_producer          # scoreform / quillan / concord / none
format                      # selected_response / writing / collaboration / observation / other
standard_refs[]
individual_or_group
required_or_optional
actual_academic_work_ref?
```

Invariant:

```text
PlannedEvidence != Academic Result
preferred producer != required producer
planning intent != completed work
```

### ResourceReference

Reference, not file ownership by default.

Could support:

- local path reference;
- URL;
- title/author;
- school-approved resource ID;
- teacher note;
- optional immutable digest for local resources when reproducibility matters.

Atlas should not become a general document repository unless a later explicit design requires it.

## 5.5 Teacher workflows

### Create Course Plan

```text
Atlas
-> Course Planning
-> Create Course Plan
-> select school year / classes or course context
-> attach curriculum reference
-> choose standards profile/reference
-> review
-> create
```

### Create Unit

```text
Course Plan
-> New Unit
-> title / duration
-> essential questions / big ideas
-> standards emphasis
-> texts/resources
-> assessment intentions
-> planned PDS evidence opportunities
-> review
-> create
```

### Build Lesson Sequence

```text
Unit
-> Plan Lessons
-> add/reorder lessons
-> assign approximate dates
-> identify lesson objectives
-> identify planned evidence
-> flag assessments
-> review pacing
```

### Create today's lesson from unit context

```text
Open Unit
-> Next Lesson
-> copy previous structural pattern or start blank
-> revise objective/materials/steps
-> choose evidence capture where useful
-> save new revision
```

### Link actual PDS work

After ScoreForm/Quillan/Concord work exists:

```text
Planned Evidence
-> Link Actual Work
-> discover eligible Core Academic Work
-> preview identity and producer
-> create Atlas reference
```

No producer record mutation.

### End-of-unit reflection

Teacher can record:

- pacing differences;
- resources to keep/change;
- planned standards with little observed evidence;
- lessons that need redesign;
- next-year revision notes.

Atlas may consume read-only Meridian coverage summaries later but must not copy proficiency calculations into its own canonical authority.

## 5.6 Atlas and ChatGPT

Atlas should eventually be designed to cooperate with AI planning without making AI output authoritative by default.

A safe future architecture:

```text
ChatGPT / other planning assistant
-> draft lesson/unit text
-> teacher reviews
-> explicit import/proposal into Atlas
-> teacher approves
-> canonical Atlas plan
```

Never:

```text
AI suggestion -> silent canonical write
```

A future `atlas_plan_draft_v1` interchange could be intentionally non-authoritative and review-required.

## 5.7 Atlas minimum viable release sequence

### v0.1.0 — Architecture and read-only foundation

Risk target: mostly **A**.

1. repository/package scaffold;
2. authority ADR;
3. CoursePlan/Unit/LessonPlan draft contracts;
4. synthetic fixtures;
5. in-memory validation;
6. canonical serialization;
7. read-only Core standards/class resolution interfaces;
8. no production workspace writes;
9. no AI integration;
10. release only if useful as a library/contract foundation.

### v0.2.0 — Teacher-local planning persistence

Risk: **B**.

1. module-owned `<workspace>/atlas/` root after explicit architecture approval;
2. create-only/revisioned CoursePlan, Unit, LessonPlan persistence;
3. task-oriented teacher CLI/menu;
4. standards references to Core;
5. resources and pacing;
6. planned evidence;
7. no student-specific analytics.

### v0.3.0 — PDS work linking and instructional feedback loop

1. Core Academic Work links;
2. read-only Meridian standards-coverage consumption;
3. planned-vs-observed coverage;
4. lesson/unit reflection workflows;
5. suite attention/launcher integration.

### v0.4.0 — Reviewed planning-assistant interchange

Only after the canonical Atlas model is stable.

1. non-authoritative plan-draft contract;
2. import preview;
3. teacher edit/reject/accept;
4. provenance identifying source as external/assistant-generated;
5. no student data sent to external service by PDS automatically.

---

# 6. New module: `pds-compass` — Student Goals, Check-Ins, and Conferences

## 6.1 Purpose

Compass would own a neutral, teacher/student-facing goal cycle that is not currently represented cleanly by Meridian, Vitrine, or Portia.

Examples:

- improve use of textual evidence in analytical writing;
- complete a multi-step project by planned checkpoints;
- contribute verbally at least once during each seminar for a defined period;
- revise major writing after teacher feedback;
- improve independent study habits;
- prepare for a reassessment under a concrete action plan.

## 6.2 Explicit boundaries

Compass is **not**:

- an IEP system;
- a 504 system;
- a clinical or counseling record system;
- a behavior/discipline system;
- a risk-scoring system;
- a Grade system;
- a proficiency calculator;
- an attendance system;
- a parent communication system;
- a permanent learner-trait profile.

Preserve:

```text
goal != Grade
student reflection != proof
teacher observation != diagnosis
goal status != proficiency
missed action step != behavior violation
Compass record != Portia Event
Compass goal != IEP/504 objective
```

## 6.3 Proposed record model

### Goal

```text
goal_id
schema_version
student_ref              # exact Core class/student context or durable allowed identity
school_year_id
created_at
created_by
title
description
domain                    # teacher-defined bounded category
status
start_date?
target_review_date?
success_criteria[]
source_context_refs[]?
supersedes_goal_id?
```

### GoalCycle / GoalRevision

Goals should evolve without erasing history.

```text
goal_revision_id
goal_id
revision_number
statement
success_criteria[]
status
reason_for_change?
created_at
```

### ActionStep

```text
action_step_id
goal_revision_id
description
owner                     # student / teacher / shared
planned_date?
due_date?
status
```

### CheckIn

```text
check_in_id
goal_revision_id
date
participant_roles[]
student_reflection?
teacher_note?
self_reported_status?
next_steps[]
evidence_refs[]
```

Avoid making free-text sensitive data broader than necessary.

### EvidenceReference

Reference authorized evidence without copying it.

Possible sources:

- Meridian proficiency/result snapshot;
- Quillan submission/review;
- ScoreForm result publication;
- Concord Activity evidence;
- Vitrine Selection/Edition;
- Portia reference only when purpose/authorization make it appropriate.

Invariant:

```text
reference != ownership
reference != authorization to disclose source content
source evidence != automatic goal success
```

### ConferenceNote

Optional bounded note for teacher/student academic conference.

Should support:

- purpose;
- attendees/roles;
- agenda;
- summary;
- agreed next steps;
- linked goal/check-ins;
- no automatic parent/guardian delivery.

## 6.4 Teacher workflow

### Start a goal

```text
Compass
-> Student Goals
-> select class/student
-> New Goal
-> choose or write goal statement
-> define success criteria
-> define review date
-> optional evidence references
-> preview
-> create
```

### Check in

```text
Open Goal
-> Check In
-> review prior action steps
-> record student reflection
-> record teacher observation
-> attach authorized evidence references
-> choose next steps
-> optionally revise goal
```

### Review goal status

Statuses should be descriptive and teacher/student controlled, for example:

```text
active
paused
completed
revised
withdrawn
```

Avoid automatic `met/not_met` based solely on external scores unless a teacher explicitly defines and confirms that criterion.

## 6.5 Student agency

Compass is strongest if it preserves the student's own voice.

A later paper/digital workflow could allow student reflection and goal check-ins, but ingestion should follow the same PDS principle:

```text
captured student statement
!= teacher judgment
```

If student-authored reflections are imported/scanned, provenance should identify them as student-authored evidence.

## 6.6 Privacy sensitivity

Compass may accumulate highly personal academic reflections. Therefore:

- default logs must not contain goal text;
- suite attention should expose only safe counts/statuses;
- exports require explicit preview;
- no automatic Meridian interpretation of goal text;
- no use as a hidden student-risk profile;
- no cross-year carry-forward by default;
- no automatic Portia linking;
- do not place medical, disability, family, counseling, or protected-service details in ordinary Compass goals.

## 6.7 Proposed release sequence

### v0.1.0 — Architecture and synthetic contracts

Risk: **A**.

1. repository scaffold;
2. authority/privacy ADR;
3. Goal/Revision/ActionStep/CheckIn models;
4. synthetic fixtures;
5. serialization/validation;
6. no workspace writes;
7. no producer integrations.

### v0.2.0 — Teacher-local academic goal cycle

Risk: **B**.

1. module-owned persistence;
2. teacher-created goals;
3. revision/action-step/check-in workflows;
4. conference notes;
5. Core identity resolution;
6. no automatic evidence interpretation.

### v0.3.0 — Authorized PDS evidence references

1. read-only eligible evidence discovery;
2. exact references;
3. source authorization;
4. goal review summaries;
5. Vitrine/Quillan/Meridian references;
6. suite attention integration.

### v0.4.0 — Student reflection/paper workflow

Only after the academic goal model proves useful.

---

# 7. `pds-sunset` — explicitly deferred

`pds-sunset` remains a sensible future model for archival/retention/end-of-year lifecycle, but this roadmap intentionally does not schedule implementation before the later part of the school year.

When eventually designed, Sunset should answer questions such as:

- what remains active after the school year closes;
- what becomes read-only;
- what should be exported before archival;
- what records are subject to teacher/district retention rules;
- what can be safely removed from an active working set;
- how an archived workspace can be independently verified;
- how archived records can be restored without silently becoming current again.

Sunset must not become a generic destructive cleanup command.

Until then:

```text
backup != archive
archive != delete
school-year close != automatic retention decision
```

---

# 8. Other module candidates — intentionally not first priority

## 8.1 `pds-lens` — teacher instructional reflection / inquiry

Potential future domain:

- instructional strategy notes;
- lesson reflection;
- class-level outcome references;
- teacher hypotheses;
- follow-up instructional changes.

However, much of the valuable early version can live in Atlas as lesson/unit reflection. A separate Lens module should be created only if teacher-practice inquiry becomes large enough to deserve its own canonical domain.

## 8.2 Modules not recommended

Do not create separate modules merely for:

- attendance;
- generic email/parent contact;
- seating charts;
- LMS replacement;
- file storage;
- AI grading;
- a generic dashboard;
- standards storage;
- backups.

These either already have an authority, belong in an existing module, or would create harmful duplication.

---

# 9. Recommended post-current-plan implementation order

## Wave 0 — safe design pre-work only, before winter break if desired

No production workspace mutation.

1. Maintain this roadmap in the suite repository.
2. Draft Atlas authority ADR and initial contracts.
3. Draft Compass authority/privacy ADR and initial contracts.
4. Create synthetic-only Atlas/Compass repository scaffolds if desired.
5. Prototype Meridian standards-coverage analysis as pure functions over synthetic fixtures.
6. Prototype ScoreForm item analytics read-only over synthetic exported results.
7. Prototype Vitrine Edition comparison read-only.
8. Write suite backup-policy/pruning requirements but do not enable destructive automation.
9. Design school-year rollover proposal format without implementing live writes.

This work can reduce winter-break design time without risking the active school-year workspace.

## Wave 1 — winter-break operational hardening

Recommended first implementation wave because it reduces risk for the rest of the year.

1. suite backup inventory/policy;
2. guarded pruning;
3. multi-device advisory session marker;
4. sync-aware diagnostics;
5. Core rollover planning service if sufficiently mature.

## Wave 2 — read-only instructional analytics

1. Meridian standards coverage;
2. Meridian longitudinal views;
3. Meridian policy sandbox;
4. ScoreForm item analytics;
5. Vitrine Edition comparison;
6. Portia descriptive support review;
7. Concord group-history diagnostics.

Prefer pure/read-only implementations first.

## Wave 3 — deeper producer workflows

1. Quillan feedback library;
2. Quillan revision-series architecture and implementation;
3. ScoreForm alternate forms;
4. Concord teacher constraints/rotation-aware planning.

## Wave 4 — Atlas

Atlas can begin earlier as a synthetic package, but production persistence should follow a dedicated review.

Suggested sequence:

```text
Atlas 0.1 architecture/models
-> Atlas 0.2 local planning persistence
-> Atlas 0.3 PDS work/coverage integration
-> Atlas 0.4 reviewed AI-planning interchange
```

## Wave 5 — Compass

Compass should follow Atlas unless an urgent student-conference need makes it more valuable sooner.

Reason: Atlas operates mostly at course/unit/lesson level and carries less sensitive student-specific information. It is therefore a safer first new canonical module.

## Wave 6 — Sunset near school-year end

Design archival policy using experience from a full year of actual workspace growth.

---

# 10. Release and migration policy for this future program

Every future milestone should answer these questions explicitly before code is accepted:

1. Does it add a new canonical record?
2. Which repository owns that record?
3. Is the record versioned from its first release?
4. Does installation alone mutate the workspace?
5. Does reading old data trigger a migration?
6. Does the new release require rewriting any existing bytes?
7. Can the previous release still read its own historical records?
8. Can the new release distinguish historical versions without silently coercing them?
9. Does a new derived cache remain rebuildable?
10. Is there a clean rollback path if the feature is never enabled?
11. Does backup/restore preserve the new state automatically as ordinary workspace bytes?
12. Are deletion/pruning operations previewed and separately authorized?
13. Does suite-level qualification prove coexistence with all currently supported modules?

Preferred migration rule:

```text
read historical version explicitly
-> create a new successor only when teacher/application explicitly chooses migration
-> preserve historical bytes
```

Avoid:

```text
open workspace
-> silently rewrite old records
```

---

# 11. Success criteria for the post-plan era

Paper Data Suite should be considered to have reached a mature teacher-local ecosystem when it can support this sequence without collapsing authority boundaries:

```text
Atlas
  teacher plans a unit and standards emphasis

ScoreForm / Quillan / Concord
  students produce evidence

Meridian
  teacher interprets standards evidence and Grade previews

Compass
  teacher/student set and review goals where useful

Portia
  teacher documents support processes where appropriate

Vitrine
  teacher/student curate meaningful work

Atlas
  teacher revises future instruction using observed evidence coverage

Sunset
  teacher closes and archives the school year deliberately
```

The design goal is not to make PDS the official SIS/LMS/gradebook/discipline platform. The goal is to give a teacher a coherent, locally controlled professional evidence and planning system whose parts remain explainable, recoverable, and independently owned.

---

# 12. Immediate recommendation

Do **not** add runtime Atlas or Compass writes to the active workspace while the current development plan is still being finished.

If there is development capacity before winter break, limit it to Risk Class A work:

- documents;
- ADRs;
- synthetic schemas;
- in-memory models;
- read-only analytics prototypes;
- temporary-directory persistence tests;
- issue/milestone planning.

That allows the future program to become implementation-ready without turning the live 2026–2027 workspace into a migration test bed.
