# Suite #20 Slice D — Clean installed Core/Suite attention contract acceptance

**Issue:** [Suite #20](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/20)

## Scope and release distinction

This gate qualifies the **pure** attention projection/renderer delivered by
Slices A–C with a freshly built, installed Suite wheel and an authenticated
**published Core v0.6.6** wheel. It does not install any real producer, load
any producer entry point, read a real workspace, invoke module-owned attention,
or certify a teacher dashboard. Those require separate acceptance under Suite
#21–#23 and #27. This is synthetic contract evidence, not a new Suite release.

The exact published Core wheel is
`pds_core-0.6.6-py3-none-any.whl` with SHA-256
`d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301`.
Artifact checks validate the official, *expected* GitHub release bytes; they
are not independent publisher signing. The Suite wheel is built from a
Git-archived exact candidate commit, not the checkout's import paths. The
installed subprocess runs from an isolated temporary directory with
`PYTHONPATH` and `PYTHONHOME` unset, and validates both imported module paths
lie within its disposable virtual environment.

The Windows runner is intentionally explicit, offline-first and separate from
normal Suite startup. Its `-AllowPyPI` switch permits installation of missing
third-party dependencies **only into that disposable venv**. The official Core
wheel is selected from an explicit teacher-supplied wheelhouse and verified by
hash before any installation. No existing user `.venv` is changed by pip.

## Contract witnesses

`scripts/issue20_d_installed_pure_smoke.py` exercises **Core v1's public
`invoke_module_attention` using in-memory fictional callbacks**. Those
callbacks are fixture functions, *not* ScoreForm, Quillan, Concord, Meridian,
Vitrine or Portia; no producer code is imported or queried.

- Six approved ModuleOperations rows; no extra Core owner.
- ScoreForm-like synthetic `evaluated_items`, Quillan-like `unavailable`,
  Concord-like `provider_failed` and three `not_evaluated` observations,
  proving **partial** coverage rather than an all-clear claim.
- Exact owner/category/class filters, stable count-`None`/zero/nine semantics,
  display-limit disclosure and unreviewed-label suppression.
- Foreign `ModuleOwnerActionRef` is rejected by Core and again by the Suite
  projection. No owner actions are performed.
- All six **synthetic** successful empty evaluations distinguish complete
  evaluated-empty from unevaluated unknown. No priority score or cross-owner
  total is created.
- Hostile fictional record/notice/exception text never reaches rendered text.

The Windows installation runner emits the exact Core and built Suite wheel
SHA-256 hashes and one stable marker per accepted scenario. Its terminal marker
is `SUITE20_D_FRESH_INSTALLED_ATTENTION_VERIFIED`. Source qualification and
installed acceptance are separate decisions and must not be conflated.

## Consumer handoff

**#21–#22 producer integrations** must independently qualify each released
producer's exact metadata/profile/attention callback under an explicitly
selected workspace, school year and class scope. Those tickets establish
source-reviewed safe category labels and notice vocabularies; they may not
copy arbitrary provider text into Suite or treat `ModuleOwnerActionRef` as an
invokable command. Fail/unavailable/empty states must remain distinct.

**#23 Teacher Home Attention Needed** should gather explicit authorized
producer observations, call `project_module_attention(...)`, then
`filter_attention_projection(...)` and `format_attention_display(...)`.
No automatic startup evaluation, background polling, invented severity ranking,
global count or implicit action routing is permitted. Context and owner must
be freshly verified for any qualified later action. Core personal Notes/Tasks
remain a separate UI section, never canonical module-attention evidence.

## Evidence checklist (pending until executed)

- [ ] Windows x64 Python 3.11 clean virtualenv with Core 0.6.6 exact release
  hash and freshly built Suite 0.1.0 wheel, both import paths inside venv.
- [ ] `pip check` passes and all in-memory Core-v1/Suite synthetic witness
  markers pass; raw private test strings do not appear.
- [ ] Ruff, strict mypy, source regression checks, committed source audit and
  standard PR CI pass for the exact candidate source SHA.
- [ ] #21/#22/#23 producer, published callback, UI and teacher-path coverage
  remains explicitly **NOT QUALIFIED** here.

The above checkboxes are **not prechecked** in the source candidate. Record
actual versions, SHA-256 values, platform and results in issue/PR comments
rather than rewriting a witness into retroactive release evidence.
