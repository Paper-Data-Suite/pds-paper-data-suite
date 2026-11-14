# Suite #18 — Slice 6B2: Native Mixed-PDF PDS2 Qualification

Status: **source prepared; teacher Windows isolated-wheel acceptance pending**.
This is a synthetic **qualification harness only**, not the live classroom workflow.

## Exact baseline and scope

Requires qualified Slice 6B1 issue-branch head
`c04629ec3b068fce8ec0b8b8e681e6959d42ec60`, released
Core 0.6.6 / ScoreForm 0.13.0 / Quillan 0.10.6 and no historical
Suite #49 compatibility-manifest modification. The three official wheels
remain SHA-256 authenticated as in Slice 6A. In its disposable environment,
install compatible `pypdfium2>=5.13,<6`, `zxing-cpp>=2.3,<3` and the actual
release wheel dependencies through normal pip resolution; record versions.

The generated **two-page PDF is a real PDF**, not a fake `DecodedPage` fixture:

1. Page 1: the B1 production-geometry synthetic **issued** ScoreForm OMR
   sheet, marked A/B/C/D, with a distinct genuine serialized PDS2 QR.
2. Page 2: a separate Quillan synthetic response page with its own genuine
   PDS2 QR and legitimately issued Quillan immutable record/registration.

The harness obtains genuine PDFium-rendered physical pages and ZXing-cpp QR
observations through Suite's `decode_with_optional_backends`, then strictly
parses both through the Core PDS2 parser. Module ownership is verified as
`scoreform`, `quillan` in one-based physical order. It **does not** infer a
full route from #17's advisory `PagePreview`.

## Authorization and custody

The harness constructs the actual #17 read-only preview, calls the #18
`build_processing_plan`, first **cancels** a fresh plan-bound Core retention
challenge and proves no new workspace writes. It then approves a fresh
challenge, retains the *complete source PDF exactly once* with
`pds_core.scan_retention.retain_source_scan`, verifies Core byte provenance
and observes exactly one retained PDF. The original external PDF is untouched.

`prepare_retained_pds2_requests` independently rereads **retained PDF bytes**,
redecodes both QRs, reconstructs real typed Core locators/requests and checks
page positions and source IDs. The harness cancels the initial dispatch
challenge and proves no writes. It then approves **one new** challenge to
`execute_prepared_paper_batch` with a strict discovered Core registry and
exactly two qualified handlers. A passive test-only dispatcher wrapper records
the original Core `dispatch_routes` outcomes transiently and returns them
unchanged; **neither page is replayed**.

## Success and failure truth

The two Core typed outcomes must both be `RouteDispatchSuccess`. Page 1's
producer result must be a genuine `ScoreFormPageDispatchResult` with the
correct 4/4 A/B/C/D ordered answers, exact route, retained-source SHA and
source-page-1 identity. Quillan's actual page-2 result must carry its exact
route identity; a handler return is **not evidence capture or grading**.

Original Core retention, registrations, immutable producer issuance/records,
source PDF and all pre-existing files must remain byte-identical. New
producer diagnostics, if any, must be confined to ScoreForm's managed debug
area. Suite does not persist an opaque module result, student ID, grade,
original path or QR payload. Errors are reported as bounded type codes only.

No automatic retry, repair, cleanup of Core-owned data, background processing,
teacher-workspace scan, global grade database, or cross-producer transaction.
This test does not qualify physical scanner/mobile input, long-path physical
scanner behavior, complete four-module composition, Suite #49 release trust,
Linux/Python 3.11–3.14 CI, or the eventual #19 Teacher Home UX. Concord #170
PDFium conflict and Portia #67 remain separately bounded.

## Qualification gate

The guarded source runner requires clean exact local/remote B1 HEAD. It
verifies source ZIP/member hashes, runs repo-wide Ruff, focused strict mypy
and #17/#18 source regressions, and checks the exact three untracked files.
**Before commit**, its separate disposable wheel runner authenticates official
release assets, builds a candidate Suite wheel, installs with `pip check`,
installs and records native dependencies, and runs the actual end-to-end
native rehearsal. Only a successful native run allows three-file staged-path,
whitespace, commit, push and clean-tree checks.

Expected completion markers:

- `SUITE18_SLICE6B2_SOURCE_QUALIFIED`
- `SUITE18_SLICE6B2_OFFICIAL_WHEELS_AUTHENTICATED`
- `SUITE18_SLICE6B2_NATIVE_BACKENDS_IDENTIFIED`
- `SUITE18_SLICE6B2_INSTALLED_PROFILES_QUALIFIED`
- `SUITE18_SLICE6B2_NATIVE_MIXED_PDF_QUALIFIED`
- `SUITE18_SLICE6B2_INSTALLED_ACCEPTANCE_PASSED`
- `SUITE18_SLICE6B2_QUALIFIED_COMMITTED_PUSHED`

Do not mark any of these as passing until the Windows runner actually reports
success. After B2, perform focused security/recovery review, full Windows and
Ubuntu Python-version CI, package smoke and #49 nonregression before PR review.
