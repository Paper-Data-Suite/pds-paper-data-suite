# Suite #18 — Slice 6A: Exact Published-Wheel Composition Gate

Status: **source prepared; teacher Windows / isolated installed-wheel execution pending**.
This is a qualification tool, not a production teacher intake workflow.

## Purpose and scope

Slice 1–5 established teacher selection, explicit retention consent, Core custody,
retained-byte PDS2 reinspection, ordered Core dispatch, and immutable Core v2
failure/recovery semantics. Their installed Core contract checks are not proof that
published ScoreForm and Quillan wheels can safely be executed together.

Slice 6A adds **independent** artifact authentication and genuine producer
entry-point/admission testing. Neither the source ZIP nor its runners changes
Core, the existing Suite #17 CLI, Suite's #49 historical release manifest, or
any producer repository. Everything is synthetic and remains outside the
teacher's actual classroom workspace.

## Immutable official release evidence (GitHub asset SHA-256)

| Distribution | Release wheel | Official SHA-256 |
| --- | --- | --- |
| Core 0.6.6 | `pds_core-0.6.6-py3-none-any.whl` | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| ScoreForm 0.13.0 | `scoreform-0.13.0-py3-none-any.whl` | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |
| Quillan 0.10.6 | `quillan-0.10.6-py3-none-any.whl` | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |

Source: the published release assets of
[`pds-core`](https://github.com/Paper-Data-Suite/pds-core/releases/tag/v0.6.6),
[`pds-scoreform`](https://github.com/Paper-Data-Suite/pds-scoreform/releases/tag/v0.13.0)
and [`pds-quillan`](https://github.com/Paper-Data-Suite/pds-quillan/releases/tag/v0.10.6).
These are **Slice 6A test pins**, not changes to the official Suite #49
compatibility/trust manifest. A test-environment artifact checksum does not
make an unqualified release a trusted Suite distribution by itself.

The wheel auditor rejects missing/mismatched hashes, dangerous ZIP members,
missing metadata, inconsistent wheel identity, wrong published Core profile
entry point and wrong installed owning distribution. Exact installed Core
0.6.6, ScoreForm 0.13.0 and Quillan 0.10.6 are required. Core's own strict
`build_module_registry(discover_installed=True)` must return **exactly** the
two expected module identities with PDS2, routing-contract v1, registration
schema v1 and active-route support; conflicting or extra profiles fail closed.
The discovery step **runs installed producer factories** and must occur in a
disposable qualification environment, never during #17 preview or startup.

## Synthetic real-handler rehearsal

With the three verified official wheels installed alongside the Suite candidate
wheel in a **new isolated virtual environment**, run
`scripts/issue18_real_producer_rehearsal.py` from outside the repository:

1. Construct a disposable workspace and synthetic Quillan immutable response
   records/issued lifecycle, exact Core registration and retained PNG.
2. Construct a separate synthetic ScoreForm answer-sheet issuance that is
   deliberately **not yet issued**, its exact route registration and retained
   PNG. No real student records or teacher files are consulted.
3. Call the real Core `dispatch_routes` and the real installed module profiles.
   Require Quillan's handler to return its exact route identity; require the
   ScoreForm handler to refuse the unauthorized issuance as a Core
   `ModuleRouteHandlingError`. Snapshot all synthetic files before and after
   dispatch; any mutation during those handler calls is a failure.
4. Return only safe pass/fail statuses and qualification scope, not any
   producer result object, synthetic roster details or path-based diagnostics.

**Nonclaims:** ScoreForm's scoring algorithm has not been shown to successfully
score an issued synthetic sheet. The tests do not show a successful multi-page
PDF QR scan, PDFium/ZXing deployment, real scanner sample or live paper. Suite
has no durable exactly-once replay journal and must not turn a CLI audit into
unreviewed producer admission. No handler is run on an actual teacher workspace.

## Qualification workflow / expectations

The **guarded source runner** checks the clean issue branch, source ZIP hashes,
Slice 1–5 and #17 focused pytest, repo-wide Ruff, strict mypy, exact staged
paths, and Git whitespace; it commits/pushes Slice 6A *source only* if all pass.
The **separate isolated-wheel acceptance runner** builds a candidate Suite
wheel, fetches the three official producer/Core wheel assets with verified
hashes, creates a new disposable venv, installs exactly those three pinned
wheels plus the candidate Suite wheel through the ordinary package resolver,
checks `pip check`, then runs wheel audit/profile admission and actual synthetic
handlers. The isolated runner **cannot change the main Suite .venv**. It must
report an explicit refusal if downloads, dependency resolution, runtime
validation or either handler contract fails. Successful source qualification
must not be confused with successful installed-wheel acceptance.

The later Slice 6B / final PR gate must additionally prove positive ScoreForm
issued-page scoring and actual native mixed-paper (PDF with distinct QR pages)
with Core v0.6.6, ScoreForm and Quillan. It must run Windows/Linux Python
3.11–3.14 CI and existing #49 release/package checks, record native tool
versions and preserve crash/retry nonclaims. No PR or merge should be marked
ready from this source-only slice.

## Known unresolved producer composition gates

- Concord 0.3.4 requires `pypdfium2>=4.30,<5`; Vitrine 0.4.0 `paper`
  requires `pypdfium2>=5.13,<6`. Same-interpreter paper composition is **not
  qualified** while [Concord #170](https://github.com/Paper-Data-Suite/pds-concord/issues/170)
  remains open. Do not `--no-deps` force the conflicting pair.
- Portia 0.2.0 has no published `paper_data_suite.modules` profile. Its
  [#67](https://github.com/Paper-Data-Suite/pds-portia/issues/67) owns handoff.
- Meridian 0.4.2 has no qualified released global Core PDS2 routing profile.
- Core #238–#244 private teacher storage, Notes and roster work remains
  independent. Core's released public scan/routing contracts are the boundary.
- Suite #19 owns teacher-facing review, unresolved-only approval, progress,
  safe next actions, and integration into the Teacher Home menu.

## Explicit status vocabulary for #19

`wheel_hashes_verified` authenticates the exact downloaded distribution files;
`installed_profile_factory_check` means the specific installed factories were
successfully admitted by Core in the isolated venv; `quillan=handler_returned`
means its handler returned a typed Core success; `scoreform=unissued_refused`
is the deliberately negative authorization case. None of those means a live
student's answer sheet was scored or an academic outcome published.
