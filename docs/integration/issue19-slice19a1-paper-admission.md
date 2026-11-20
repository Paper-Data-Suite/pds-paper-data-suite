# Suite #19 — Slice 19A1: default-deny exact paper-admission observation

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Required parent:** Suite `main` / issue branch `f094da07b323a626212d7cbf7d15d95cec83817d`
**Files:** one new typed read-only admission module; one focused test file; this document.
**Stage:** First half of Slice **19A**, not a runnable paper-processing menu.

## Purpose

Give #19 a truthful **preview-only** paper processing eligibility observation
without creating an alternate version registry, declaring official-wheel origin,
or admitting a producer from a QR, successful `pds launch`, or local metadata.

The normal entry point is:

```python
from paper_data_suite.returned_paper_admission import inspect_paper_admission

observation = inspect_paper_admission()  # read-only Suite #49 metadata
assert observation.processing_status == "preview_only"
assert observation.qualified_modules == frozenset()
```

`inspect_paper_admission` delegates to the existing Suite #49
`inspect_local_compatibility` on its default path. It consumes `LocalCompatibilityReport`
and `ComponentAssessment` and validates fixed owner/distribution identities from
`APPROVED_COMPONENTS`. It does **not** import Core's routing registry, discover
module profile factories, decode/parse QRs, inspect a teacher workspace or source,
read wheel caches, install packages, create a Core receipt, contact the network,
or call a handler.

## Exact published candidate matrix

| Item | Exact release version | Native evidence | 19A1 conclusion |
|---|---|---|---|
| Core | 0.6.6 | #18 fresh official-wheel Windows/Ubuntu Python 3.11 installed tests | Required **candidate** only |
| ScoreForm | 0.13.0 | #18 authentic issued OMR 4/4 and Core returned handler | Candidate; **never dispatch-eligible** here |
| Quillan | 0.10.6 | #18 Core returned handler; not written student response evidence | Candidate; **never dispatch-eligible** here |

`python_version=(3, 11)` and runtime `win32` or `linux` match **only** the OS/Python
pairs independently exercised in #18's native published-wheel rehearsal.
`darwin`, Cygwin, Python 3.12–3.14 and new producer/Core versions are
**runtime/version unqualified** for this fixed paper admission observation, even
when those installations are otherwise valid and launchable via #49. Future
installed acceptance can expand the qualified matrix **explicitly**.

`exact_release_candidate` means *the observed version and local dependency/entry-point
metadata match a release previously exercised in a synthetic installed test*.
It is **not** publisher provenance, installed-file byte authentication,
a current routing-profile probe, successful native decoder discovery, teacher
consent or permission to execute. All current `PaperAdmissionV1` responses
therefore enforce `qualified_modules=frozenset()` and `processing_status=preview_only`.
Attempts to build a record claiming a nonempty allowed set raise
`PaperAdmissionError`. A forged optional `report` or OS/Python test override
cannot enable Core dispatch.

The `ProducerAdmissionV1` statuses are:
`exact_release_candidate`, `not_installed`, `incompatible`,
`version_unqualified`, `core_unqualified`, `runtime_unqualified`,
`metadata_unavailable`. A wrong or ambiguous registered distribution identity
is **metadata_unavailable**, not eligible. A missing/broken sibling does not
conceal another individually healthy candidate. No producer IDs beyond
ScoreForm/Quillan are accepted in v1.

## Why this is not a production authorization API

Core #18's `execute_with_core_review(..., qualified_modules=frozenset())`
and `execute_prepared_paper_batch` correctly default-deny. Version matching
from dist-info cannot independently attest the installed wheel's origin or
contents. This slice intentionally **does not** expose a `trusted=True`,
`allow_dispatch=True`, user-supplied module list, local receipt toggle, or
blind handoff from `exact_release_candidates` into that Core dispatch argument.

**Required follow-up Slice 19A2**: approve the narrow exact installed-artifact
qualification policy and action-time native/runtime/profile verification. It
must reuse #18's official SHA-256 wheel identities and installed-profile
qualification and #49's local compatibility checks. Merely finding old
synthetic acceptance evidence or a same-version module is insufficient to
assert publisher authentication on a new machine. Define/qualify a trustworthy
installation/wheel-content binding *or keep live dispatch unavailable*. Do not
reopen #49's deprecated publisher-signing/catalog, privileged services or
automatic-update architecture. The first teacher UI (19B) may safely show
preview-only status while 19A2/installed evidence remains unresolved.

## Tests and limits

`tests/test_issue19_slice19a_admission.py` covers 27 parametrized cases on the
local logic contract: exact candidates remain default-deny; Windows/Linux
Python 3.11 and unsupported runtime combinations; future versions; missing,
incompatible, ambiguous and spoofed owner rows; sibling isolation; immutable
permission refusal; malformed runtime arguments; and no handler imports.

The source archive is only three new files and does not touch the existing
`teacher_home.py`, #17 preview/inbox, #18 custody/dispatch, #49 application
launch/doctor, Core/private storage or historic Suite manifest. No classroom
data is accessed by this slice. It creates **no valid production dispatch**.

Scoped repository qualification:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q `
    tests/test_issue19_slice19a_admission.py `
    tests/test_issue49_slice144_local_compatibility.py `
    tests/test_issue49_slice145_cli_integration.py `
    tests/test_issue49_slice146_operational_doctor.py

& .\.venv\Scripts\python.exe -m ruff check `
    paper_data_suite/returned_paper_admission.py `
    tests/test_issue19_slice19a_admission.py

& .\.venv\Scripts\python.exe -m mypy `
    paper_data_suite/returned_paper_admission.py
```

Source-only local harness test result at authoring: **27 passed** using typed
minimal stubs for existing #49 dataclasses and approved registry; it is **not**
the real Suite repository test, Ruff, mypy or installed-wheel gate. The exact
Windows repository runner must pass before commit/push.

## Next step

Once 19A1 is qualified and pushed, produce **19A2** on its exact verified
parent. Close Slice 19A's admission decision *before* enabling a producer menu,
then proceed to 19B's bounded, read-only Teacher Home selection and preview.
