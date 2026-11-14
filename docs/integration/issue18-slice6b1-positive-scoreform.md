# Suite #18 — Slice 6B1: Real Issued ScoreForm Positive Scoring Gate

Status: **candidate test source; installed official-wheel acceptance pending**.

Slice 6A qualified a genuine issued Quillan response-page handler return and a
ScoreForm **unissued** refusal, but deliberately did not claim positive OMR.
Slice 6B1 fills this narrower coverage gap without changing production Suite,
Core, ScoreForm, Quillan, the existing #17 read-only commands or Suite #49's
release compatibility manifest.

The explicit qualification script runs only in a new disposable venv with the
three SHA-authenticated official wheels pinned in Slice 6A and the candidate
Suite wheel. The caller supplies a freshly empty workspace named
`suite18_synthetic_workspace` beneath the OS temporary directory; no actual
teacher workspace, roster or source scan is used.

The fixture uses **only genuine ScoreForm 0.13.0 public persistence APIs** to
create a managed four-question A/B/C/D assignment, immutable answer-sheet
records, exact Core registration and a **revision-guarded issued lifecycle**.
It draws four filled OMR answers with ScoreForm's published registration-mark
and bubble geometry. Core retains the complete source PNG and routes page 1
through the strict installed `build_module_registry` and real `dispatch_routes`.

Qualification requires a typed Core success whose opaque `module_result` is
a real `ScoreFormPageDispatchResult`, with **4/4 correct answers in order**,
identical locator, Core retained provenance, source page and SHA-256. Every
pre-existing source, issuance and registration file must remain byte-identical;
new diagnostic files, if any, are constrained to the ScoreForm-owned work debug
area. No arbitrary module-result serialization or Suite-owned scoring store is
created.

A failure returns a sanitized refusal marker and nonzero status. No automatic
retry, teacher approval claim, student grades publication or cross-module
transactionality is inferred. Even successful B1 acceptance does **not**
qualify a native two-page mixed QR/PDF intake (B2), a printed-and-scanned
physical sample, multi-platform CI, full Suite publisher trust or teacher UX
owned by #19.

## Required evidence

- Retain the exact SHA-verified Core 0.6.6, ScoreForm 0.13.0 and Quillan 0.10.6
  composition from Slice 6A without resolver bypasses.
- Run repository Ruff, focused strict mypy, #17/#18 regressions and exact stage
  gates before committing any new source.
- Run separately in a fresh isolated installed environment with `pip check`.
- Show `SUITE18_SLICE6B1_POSITIVE_SCORE_QUALIFIED` **only** after exact 4/4
  matching positive scoring and Core custody/route evidence.
- Preserve the existing #49 manifest and all production modules.

The next Slice 6B2 will require a **single native multi-page PDF with real
PDS2 QR payloads from different producer routes**, sequential retained-source
reinspection and explicit selected-page authorization. This script must not be
misrepresented as that test.
