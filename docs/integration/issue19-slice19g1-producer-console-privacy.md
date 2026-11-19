# Suite #19G1 — Producer diagnostic console privacy repair

Issue: https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19
Exact parent: `b96e7bfbe972c518d7f3ed3c9895f3cc8b327488`
Scope: Suite's existing `returned_paper_ordered_dispatch._core_dispatch` adapter, three regression tests, and this note. No modification to official Core, ScoreForm or Quillan wheels, teacher approvals/challenges, admission policy, producer-owned records, or immutable Core results.

## Installed evidence and observed failure

The previous installed Windows Python 3.11 acceptance revalidated the official wheelhouse, package versions, native PDFium/ZXing QR decoding, and the three #18 synthetic producer rehearsals. The G1 Teacher Home journey verified all first three scenarios: first-consent cancellation, retained-only review, and second-consent cancellation. The fourth, affirmative two-page `DISPATCH`, failed with `SUITE19_G1_HOME_FAILURE_CODE=privacy_violation`.

The G1 harness correctly rejects any appearance of the private synthetic workspace path or the sample student name in the teacher-facing transcript. The separately successful native ScoreForm rehearsal showed the handler writing diagnostic PNG absolute paths to the terminal. Suite's `_core_dispatch()` passed `pds_core.module_dispatch.dispatch_routes(...)` stdout/stderr straight to Teacher Home. This is a genuine output-isolation gap, not a justification for weakening the G1 privacy assertion. Because the failing G1 transcript is deliberately not disclosed by the harness, the precise failing substring remains unverified until a new installed run.

## Scope and safety

The adapter now redirects **Python-level stdout and stderr** to the OS null device only during synchronous Core dispatch. The Core dispatch function is still invoked once per selected page, with identical input and typed Core result returned unchanged. Exceptions propagate, allowing existing Core/Suite uncertainty and no-retry treatment. Cancellation, source custody, route validation, current installed eligibility, fresh teacher approval, review recording and grade non-publication are unchanged. Unit tests require both streams muted, result identity, the caller's stream restored, no invented success, and no suppression of handler exceptions or retry.

This is **not** a general OS-level stdout sandbox: producer code writing directly to file descriptors or separately held log handlers, child processes, and concurrent threads can bypass Python stream redirection. The full installed Home acceptance remains necessary and must fail if an actual private path or other output escapes. Do not use live classroom data as test input.

## Rerun requirement

Source qualification: guard exact clean SHA `b96e7bfbe972c518d7f3ed3c9895f3cc8b327488`, verify old Git blob/ZIP hashes, patch the adapter, add these tests and documentation, run scoped Ruff/mypy/pytest, and commit/push only on passing qualification. **Then use the full existing E3A installed test with `-IncludeTeacherHome`**. It builds a *new Suite wheel from the repaired commit* in a fresh Python 3.11 disposable environment. The old fast-resume runner still has an installed, pre-repair Suite wheel and is *not* a valid test of this production change. Passing unit tests alone cannot satisfy the #19G1 installed privacy acceptance gate.
