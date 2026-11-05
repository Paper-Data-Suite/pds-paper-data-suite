# Issue #49 — Slice 147: Offline Wheel Acceptance and Release Handoff

Status: **candidate qualification**, not an assertion that the issue is closed or
that any mixed release set is officially authenticated.

Parent commit: `9097ba3870b59f09e804f9a40d3d314bb2ec4f42`.

## Scope

This slice adds read-only acceptance tests and a release checklist. It does not
change Suite runtime behavior, install or update any teacher packages, elevate
privileges, alter student records, rotate keys, sign releases, or modify the
historical v0.1.0 compatibility manifest.

The preceding three slices provide:

- 144: fixed approved distribution/console registry and offline local metadata
  assessment, separate from official provenance and historical integration.
- 145: normal `pds modules` and `pds launch` wired to the local assessment,
  retaining current-interpreter script confinement and isolated launch failures.
- 146: version-tolerant `pds doctor` and Core workspace/setup admission while
  retaining public-interface gates and teacher-confirmed `APPLY` semantics.

## Automated acceptance matrix

The test `tests/test_issue49_slice147_installed_wheel_acceptance.py` builds
**synthetic, explicitly non-official** PEP 427 wheel fixtures. A subprocess
installs them with `pip --isolated --no-index --no-deps --target <pytest temp>`;
this never installs anything into the active teacher Python environment.
Installed `.dist-info` is read via the real `importlib.metadata` API. The wheel
modules deliberately raise an exception if imported, so successful metadata
inspection demonstrates that evaluation does not execute module code.

| Scenario | Required result |
|---|---|
| Core 0.6.6 plus all six newer application fixture wheels | All seven locally compatible; actual versions reported |
| Newer Quillan 0.10.6 with Core 0.6.6 | Locally compatible; not historically integration-tested |
| Quillan installed with missing Core | Incompatible; no implicit launch authorization |
| Core 0.7.0 with Quillan | Incompatible against current Suite Core range |
| Quillan console target differs from approved target | Incompatible; no provider import |
| ScoreForm has an unsatisfied dependency | Incompatible; dependency missing |
| A second installed wheel also declares `quillan` | Incompatible; ambiguous ownership |
| Installed Portia has an editable-install metadata marker | Incompatible; editable PDS install |
| Metadata inspection | No new `pds_core` / `quillan` imports |

These fixture versions are **test inputs**, not claimed latest releases or
trusted release provenance. Real package dependencies, runtime behavior, and
teacher workflows need separate acceptance with real, official wheel files.

## Qualification commands

The guarded runner applies only the new test and this Markdown document, then
runs the bounded regression set including prior Slices 144–146, standard CLI,
launching, doctor, Core workspace, and classroom setup tests. It also runs Ruff
and mypy against the relevant unchanged implementation modules.

For a manual read-only smoke test in the intended active Python environment:

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m paper_data_suite modules
& .\.venv\Scripts\python.exe -m paper_data_suite doctor
& .\.venv\Scripts\python.exe -m paper_data_suite launch --help
& .\.venv\Scripts\python.exe -m paper_data_suite setup --help
```

`pds doctor` may correctly return nonzero when packages or environment
prerequisites are genuinely unhealthy. Do not waive real dependency failures.
Do not automatically downgrade a newer compatible module to the historical
manifest version.

For a teacher-driven functional check, separately choose a known-official
installed application and explicitly run `pds launch quillan` (or the intended
module). A successful console menu does not by itself certify integrations
between modules. For `pds setup`, inspect the current classroom assessment and
cancel before `APPLY` when only checking admission. Do not use real student
records as disposable test data.

## Final issue #49 acceptance and merge decision

Before declaring the new manual-wheel path teacher-usable on a given machine:

1. Record wheel source, version, filename, and checksum for each **actual**
   approved installed distribution; do not treat local metadata as signature
   or provenance verification.
2. Confirm `pip check` and that `pds modules` reports newer compatible wheels
   without historical exact-pin failures. Each missing or incompatible module
   must be isolated and explained.
3. Confirm `pds doctor` distinguishes compatible, absent, incompatible,
   historically untested, and provenance-unverified states without hiding
   genuine dependency, interface, or workspace failures.
4. Confirm the approved console launcher resolves from the current Python
   environment, starts the expected module, and preserves the child exit code.
5. Confirm `pds setup` admits supported newer Core and does not modify
   classrooms/rosters until the teacher explicitly confirms `APPLY`.
6. Run the selected integration checks only for providers/features actually
   being enabled; never infer provider compatibility from launch eligibility.
7. Review the issue branch diff and CI, create/review a PR, and merge only
   after the real-wheel smoke and teacher acceptance evidence are recorded.

**Do not close #49 solely because these synthetic-wheel tests pass.**
The implementation slices can be complete while real-wheel/teacher acceptance,
release tagging, or a reviewed merge remain pending. Preserve all prior native
and signed-catalog experiments as deferred infrastructure, not normal manual
installation prerequisites. Existing advanced updater/signing tickets retain
their separate scope and do not block the normal teacher path.
