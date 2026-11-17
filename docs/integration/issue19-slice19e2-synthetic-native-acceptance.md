# Suite #19 — Slice 19E2: two-page native acceptance fixture

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Parent:** `9e623b6b1b8f4eb0e861939831c912e69bf3210b`
**Scope:** An exact, synthetic two-page PDF and an opt-in **decode-only** native witness. No Core custody, handler, scores, grade publication, student data, network, or producer admission.

## Fixture

`tests/fixtures/issue19_two_page_synthetic_pds2.pdf` is a deterministic two-page US-letter PDF (36,346 bytes) with one PDS2 QR on each physical page. Page 1 points to ScoreForm and page 2 to Quillan. Both use synthetic route/class/work identifiers, *not* real registrations or students. The fixed SHA-256 is `21d18d5fc7f5451d4f661cf944fb0def41651e1d3a8d22d3dbb5876e869a9548`. The fixture is test input only: **do not ingest into a real student workspace**.

The Python witness refuses missing, renamed, linked, oversized, or modified input before any native decoding. Its production path uses the existing #17 `decode_with_optional_backends` (PDFium, ZXing-cpp, Pillow) and Core's existing PDS2 parser. It demands **exactly two physical pages** and the **exact single QR** on each page, in ScoreForm-then-Quillan order. It never calls producer profiles or Core dispatch, never opens a student workspace, and never writes Core retention files. Exceptions become bounded status codes without printing private paths, QR payloads, or native tracebacks.

This is stronger than simply verifying a native symbol exists, but much narrower than an **end-to-end producer run**. A green two-page decoder test does **not** demonstrate route registration, actual Core source retention, a producer handler side effect, scoring, correct custody reconciliation, or installed provenance. The existing 19E1 diagnostic continues to permit zero `qualified_modules` even on complete payload/launcher/native/profile matches. This 19E2 witness likewise always has `producer_dispatch_authorized=False` and `qualified_modules=frozenset()`.

## Deliberate installed-environment check

In a **disposable, independently installed Windows or Ubuntu Python 3.11 venv**, after separately downloading/pinning the actual official Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6 wheels, native PDFium/ZXing/Pillow dependencies, and a locally built Suite wheel, run:

```powershell
python -m paper_data_suite.returned_paper_synthetic_acceptance `
    --fixture 'C:\explicit\tests\fixtures\issue19_two_page_synthetic_pds2.pdf' `
    --wheelhouse 'C:\explicit\official_wheels'
```

This opt-in command performs the exact synthetic native decode and E1 current-environment metadata/payload/native/profile `pip check` diagnostic. Exit code 0 means **both nonauthorizing observations passed in the disposable environment**; exit 1 means at least one did not. Neither result is executable dispatch permission. If your working checkout uses Python 3.13 or a non-disposable environment, the E1 exact-runtime diagnostic should fail closed; do not weaken it or claim Python 3.13 producer qualification.

The checked-in unit tests use an injected decoder/parser *only* to exercise failure categories and immutability without requiring installed native packages on every developer machine. Those injected results do not qualify a real decoder. A separately commanded **real** installed native test must call the production defaults above; a normal skipped optional-PDFium unit check is never native acceptance evidence. The fixture was independently rendered with PDFium and its two QR texts recovered using OpenCV during generation, but **this is not a ZXing-cpp acceptance claim**.

## Next boundary

19E3 must run the exact built Suite wheel, official-wheel hashes, native synthetic two-page document, teacher Home workflow, **both actual approvals**, and real ScoreForm and Quillan handlers in a disposable installed environment. The reviewed live installed-composition admission policy must be independently justified and checked immediately before any handler call. Preserve cancellation and default-deny if provenance, native capabilities, active workspace, or actual Core registration is absent. Continue to use #18's `execute_with_core_review`, never a Suite-specific dispatch loop or fake producer result. #19G will own final Windows installed UX acceptance and recording of exact versions/hashes.
