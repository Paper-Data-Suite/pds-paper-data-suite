# Guided shared classroom setup

`pds setup` is the suite-level guided workflow for configuring the shared
classroom state owned by PDS Core after a workspace has already been selected
and initialized.

Equivalent invocation:

```text
python -m paper_data_suite setup
```

The workflow is intentionally bounded. It can review and initially configure:

1. the active school year;
2. Core class metadata;
3. Core class rosters;
4. the shared standards library through an explicitly selected Core starter pack;
5. an initial Academic Period calendar.

It is not a general-purpose Core administration surface and it does not create
module-owned records.

## Ownership boundary

The suite owns orchestration and terminal presentation only. PDS Core remains
authoritative for:

- workspace resolution and canonical paths;
- school-year validation and state;
- class and student identifiers;
- class metadata models and persistence;
- roster parsing, validation, and persistence;
- standards models, starter-pack contents, merge semantics, and persistence;
- Academic Period models, hierarchy validation, revisions, and persistence.

The suite does not write Core JSON or CSV files directly and does not maintain a
second setup schema or persisted setup-plan file.

The active release-compatibility manifest must qualify the installed Core
release exactly before Core setup services are used. The current development
manifest qualifies `pds-core==0.6.0`.

## Workspace precondition

`pds setup` operates only on the workspace already resolved by Core. It does not
select, create, or initialize another workspace.

Before collecting classroom information it displays the resolved workspace path
and resolution source and requires the workspace to exist, be a directory, and
be writable.

If no usable workspace is resolved, run:

```text
pds workspace setup
```

then rerun `pds setup`.

## Review-before-write invariant

The central safety rule is:

```text
no persistent setup mutation before final APPLY
```

Before final confirmation, the command may read relevant Core-owned state, read
a teacher-selected roster CSV, load bundled Core starter standards, create Core
model values in memory, and ask Core to validate them.

Before final confirmation it does not open a school year, create class metadata,
write a roster, install standards, write an Academic Period revision, or persist
a suite setup plan.

The final decision is:

```text
APPLY   apply the reviewed plan
E       edit the in-memory plan
Q       cancel
```

Only exact uppercase `APPLY` authorizes Core writes. `apply`, `Apply`, blank
input, EOF, and `Q` do not authorize mutation.

Writer services are loaded only after exact `APPLY` is accepted.

## Initial assessment

The first screen is read-only and summarizes:

- resolved workspace path and Core resolution source;
- active school year, if any;
- valid discovered class folders;
- class metadata presence;
- roster presence and student counts;
- standards definition/profile counts;
- available Core starter standards packs;
- the current Academic Period calendar revision and period count when relevant.

Roster rows, student names, and student identifiers are not dumped during this
assessment.

Malformed or internally inconsistent existing shared state stops setup rather
than being silently repaired or interpreted by the suite.

## School year

The school year is explicit and must use Core's consecutive `YYYY-YYYY` format.
The suite does not infer it from today's date, a roster, class names, Academic
Period dates, locale, district, or prior context.

Behavior:

- no open year: `OPEN` after final `APPLY`;
- same open year: `KEEP`;
- different open year: `REFUSE` until the lifecycle conflict is resolved through
  an explicit Core workflow.

The suite never silently closes or overwrites another open school year.

## Classes

The teacher enters zero or more explicit Core `class_id` values. Core validates
each identifier and Core creates the candidate class metadata for the selected
school year.

Classification:

- `NEW`: no conflicting Core metadata exists;
- `EXISTING_MATCH`: existing metadata already binds the class to the selected
  school year;
- `CONFLICT`: existing metadata is incompatible or an incomplete state cannot be
  interpreted safely.

Existing legitimate Core-owned `module_details` are preserved. New metadata does
not invent course names, teacher names, room numbers, section labels, periods, or
module configuration.

## Rosters

A roster is optional for each selected class. The teacher supplies the CSV path
explicitly.

Core requires the canonical fields:

```text
class_id
student_id
last_name
first_name
period
```

Supported optional columns are preserved by Core.

The suite does not rewrite headers, infer identifiers, coerce numeric IDs, split
a mixed-class CSV, infer the target `class_id`, deduplicate by name, or discard
invalid rows.

Structured Core roster diagnostics are rendered using row/column location and a
bounded value-free explanation. The suite does not echo `RosterIssue.value` or
student data from validation failures.

For an existing class roster, `student_id` is the class-scoped identity key. The
preview reports counts for:

- `NEW` students;
- `UNCHANGED` students;
- `CONFLICTING_EXISTING` students;
- existing students absent from the incoming whole roster.

An absent roster produces `CREATE`. A materially identical import produces
`KEEP`. Any different valid import is a whole-roster `REPLACE`; the suite does
not implement row-level merge semantics. Replacement remains protected by Core's
overwrite behavior and occurs only after the reviewed final `APPLY`.

## Standards

The existing shared standards library can always be kept unchanged.

Available starter packs come only from the qualified Core release. The command
shows Core-provided pack ID, title, source, grade bands, courses, standard count,
and profile count. No pack is selected automatically.

In particular, the presence of an NJSLS starter pack does not cause the suite to
infer New Jersey, a subject, or a course.

For an explicitly selected pack the suite asks Core to perform a dry in-memory
merge with `overwrite_conflicts=False`. The review reports additions, identical
records, and conflicts for standards and profiles. Any conflicting protected
record blocks `APPLY`; the guided workflow never enables overwrite merely to
finish setup.

## Academic Periods

If a current Core Academic Period calendar already exists for the selected school
year, guided setup keeps it unchanged. This workflow is not a calendar revision
editor.

If no current calendar exists, the teacher may either skip Academic Period setup
or explicitly configure an initial calendar.

Each proposed period requires all Core fields:

```text
period_id
period_type
label
start_date
end_date
parent_period_id or none
sequence
lifecycle
```

The terminal displays Core's allowed period types and lifecycle values but does
not choose defaults. The complete calendar hierarchy is validated by Core in
memory. The final review lists every proposed period definition before `APPLY`.

A new calendar is written as revision `1` with Core's expected-current-revision
protection.

## APPLY preflight and write ordering

After exact `APPLY`, the suite first re-reads the reviewed shared state before any
mutation. If the workspace, Core-owned state, selected roster source, standards
baseline, or Academic Period state changed after review, setup refuses the write
and instructs the teacher to rerun `pds setup`.

If preflight succeeds, writes are sequenced through public Core services in this
order:

1. open the school year if needed;
2. create required class metadata/folders;
3. create or explicitly replace reviewed rosters;
4. install the explicitly selected starter standards pack if needed;
5. create the initial Academic Period calendar if needed.

After each successful step, enough Core state is re-read to verify the intended
result.

Roster replacement receives a just-in-time recheck before `overwrite=True` is
used. Standards receive a just-in-time baseline recheck and are installed with
`overwrite_conflicts=False`.

## Failure and rerun semantics

These operations span several Core domains and are not one cross-domain
transaction.

If a later Core operation fails after earlier writes succeeded, the command:

- reports the successful Core writes;
- reports the failure;
- does not claim rollback;
- does not attempt a speculative cross-domain rollback;
- instructs the teacher to rerun `pds setup` so current Core state is reassessed.

Safe reruns are part of the workflow. Already-matching state is classified as
`KEEP` and a fully current reviewed setup completes as a no-op.

## Recommended first-time pilot sequence

After installing the suite-qualified environment:

```text
pds doctor
pds workspace setup
pds doctor
pds setup
pds modules
```

Then launch an available teacher application explicitly, for example:

```text
pds launch scoreform
```

`pds workspace setup` and `pds setup` are deliberately separate. The first owns
workspace selection/initialization; the second configures shared classroom state
inside the already resolved workspace.

## Installed-wheel acceptance

After building the suite wheel, run the dedicated classroom setup smoke test with
the exact qualified Core wheel:

```text
python .\scripts\smoke_test_classroom_setup_wheel.py <suite-wheel> <core-wheel>
```

The smoke test creates an isolated virtual environment and synthetic user profile,
removes inherited `PYTHONPATH` and `PDS_WORKSPACE_ROOT`, and verifies both installed
entry surfaces. It proves that lowercase `apply` does not authorize mutation,
cancellation leaves shared classroom state unchanged, exact `APPLY` opens the
explicit school year, no suite setup-plan artifact is persisted, and a rerun of
already-current state is an idempotent no-op.

All smoke-test data is synthetic.
