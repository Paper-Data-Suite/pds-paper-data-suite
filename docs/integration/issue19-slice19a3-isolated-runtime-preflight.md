# Suite #19 — Slice 19A3: isolated installed-runtime and profile preflight

**Issue:** [Suite #19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Expected branch:** `19-teacher-home-returned-paper-workflow`
**Required parent:** `719c709e668fec33b270e9033ef9cbff46fb7e49`
**Scope:** one runtime-probe module, focused tests and this document. No Home UI or Core dispatch modifications.

## Qualification decision

`inspect_installed_paper_runtime(wheelhouse)` is an **explicit developer
qualification diagnostic**, not a teacher-home initialization or a processing
permission. It joins the three existing authorities *without replacing them*:

1. **19A1** `inspect_paper_admission`: exact Core 0.6.6, ScoreForm 0.13.0,
   Quillan 0.10.6 **candidate** versions, approved owner IDs and installed
   dependency metadata; Windows/Ubuntu on Python 3.11 only.
2. **19A2** `audit_installed_paper_payloads`: original #18 SHA-256-pinned
   published wheel archives and their on-disk installed payloads. It checks
   all three installed distributions within the **active venv**, but is not a
   loaded-code or publisher-attested installation-history certificate.
3. **19A3** native and public Core profile checks: exact initially exercised
   dependency lines (PDFium `>=5.13,<6`, zxing-cpp `>=2.3,<3`, Pillow
   `>=11,<13`), importable PDFium/ZXing/Pillow public symbols, and the already
   existing `qualify_installed_profiles()` strict Core public module-registry
   contract with exactly `quillan` and `scoreform`.

A distinct activated virtual environment and an executable located within
its prefix are also required. Do not run this probe in a global interpreter,
production teacher workspace or regular Suite home startup. **Producer profile
imports are code execution**, not a guaranteed side-effect-free metadata query.
The intended setting is a controlled, disposable wheel-installed acceptance
environment with no classroom records. The probe does not install packages,
write a receipt, build a global trusted catalog, run a scan, issue a route,
call a handler or generate teacher consent.

## Status vocabulary

| Status | Safe meaning |
| --- | --- |
| `runtime_unqualified` | Unsupported host/Python or not an isolated venv |
| `candidate_unqualified` | Exact A1 installed versions / ownership cannot be established |
| `payload_unverified` | Exact official archives/installed payloads not verified |
| `native_unverified` | PDFium/ZXing/Pillow versions or import surfaces cannot be verified |
| `profiles_unverified` | Strict Core registered profile identities and contracts differ or are unavailable |
| `diagnostic_match` | Every observed diagnostic gate passed **in this one probe**; no processing permission |

`InstalledPaperRuntimeProbeV1` is immutable. It enforces truthful stage flags,
three named native dependency versions after a successful native check, and
**always** `processing_status="preview_only"`,
`qualified_modules=frozenset()` and `producer_dispatch_authorized=False`.
No one can pass this object as a bearer token for #18's
`qualified_modules` argument. Neither a test injection nor a fabricated
Python object can create a valid producer execution permission here.

## How to run deliberately, in an isolated rehearsal environment

First install only the reviewed official wheel subset in a fresh, disposable
Python 3.11 venv and verify the wheelhouse with #18's published digests. The
three wheel archives must remain locally available. With the venv interpreter,
in an isolated rehearsal context, execute:

```powershell
& .\.venv\Scripts\python.exe -c @'
from pathlib import Path
from paper_data_suite.returned_paper_runtime_probe import inspect_installed_paper_runtime
result = inspect_installed_paper_runtime(Path(r"C:\path\to\verified\official_wheels"))
print(result.status)
print(result.processing_status)
print(result.producer_dispatch_authorized)
'@
```

The second and third lines **must** remain `preview_only` and `False`, even
for `diagnostic_match`. This callable imports producer profile factories if
(and only if) earlier checks pass. It is not wired to `pds`, `pds doctor`,
`pds papers preview`, `pds papers inbox`, or Teacher Home.

Native import/version checks are **surface checks**, not a real-PDF decode,
QR accuracy, Poppler utility availability or integration smoke test. #18's
existing installed synthetic two-page positive ScoreForm/Quillan tests and
native Linux/Windows CI provide separate evidence; those tests are not
reperformed by this diagnostic. Native extensions or arbitrary producer code
may have state and side effects on import. Loaded-code provenance, same-owner
filesystem races, hostile principal impersonation, third-party dependency
security, and classroom paper acceptance are **not** proven here.

## Review and next slice

Run A3's focused new tests together with A1, A2, #18 6A and #49 local-metadata
checks in the unchanged issue branch, then Ruff, strict mypy, compilation,
archive hashes and Git staged whitespace checks. Commit only if all pass.

**A4/19B handoff:** a later narrowly reviewed teacher action may call the
relevant live checks again immediately before dispatch, with the **separate
fresh #18 `DispatchReviewV1` approval** bound to actual Core-retained bytes.
Do not infer a permission token from this diagnostic, reuse the A3 result
across a module replacement, or broaden #18's supported producer set. Until
that action-time boundary is qualified, teacher processing remains disabled
and read-only source/page selection may proceed under 19B.

Concord/Vitrine PDFium alignment remains Concord #170; Portia global route
handoff #67 and Meridian grade/evidence readiness #125 remain module-owned.
Suite #49's completed manual-wheel compatibility policy and historical
`release_compatibility_v1.json` are unchanged.
