# Suite #19G1 — Installed Teacher Home synthetic E2E acceptance hook

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Parent:** `9f4eec05f588a8a4d9cd87a7e8c3c103ec42f4d3`
**Scope:** A bounded, opt-in **real installed** Suite CLI/Teacher Home transcript added to the independently verified E3A Windows Python 3.11 disposable wheel acceptance. No production dispatch code, admission policy, Core writer, or data store is altered.

## Evidence and cases

The existing E3A acceptance first verifies the exact published official Core 0.6.6, ScoreForm 0.13.0 and Quillan 0.10.6 wheels, locally built Suite 0.1.0, `pip check`, native PDFium/ZXing and published Core routing profiles. It runs the previous three #18 real producer synthetic rehearsals. When **and only when** `-IncludeTeacherHome` is explicitly supplied, it then invokes the new installed Home harness from the committed source snapshot in the same disposable venv, with `PYTHONPATH` cleared and outside the source checkout.

The G1 harness creates four **different**, initially empty `suite18_synthetic_workspace` roots beneath the isolated OS temporary session. Each uses producer-owned public APIs to issue a synthetic ScoreForm 4-question sheet and a synthetic Quillan response, builds a single two-page native PDF with correct PDS2 QRs and actual ScoreForm marked bubbles, and stages that PDF in the selected Core `scans_inbox`. It verifies native physical-page observations before entering `cli.main(())` with terminal-shaped, finite input/output streams. All consequential Suite/Core/producer calls are the real installed functions; the harness does not inject authorization callbacks, forged admissions, fake dispatch results or alternate record writers.

1. **First consent canceled:** explicitly choose both physical pages, review plan, type `CANCEL`, verify no difference in synthetic workspace file hashes and no Core retained PDF.
2. **Retain only:** repeat from a fresh root, type `RETAIN`, choose read-only `V`, verify exactly one byte-identical Core source receipt, legitimate prepared requests and no handler result.
3. **Second consent canceled:** start another fresh root, retain, choose `D`, supply the explicit official-wheelhouse path, type `CANCEL`; verify Core attempted zero pages and retained the original whole source.
4. **Both consents approved:** start a final fresh root, select two pages, type `RETAIN`, choose `D`, supply explicit wheelhouse, type `DISPATCH`; require two Core handler attempts, a `completed` Core run, two distinct `handler_returned` page states, real producer-group display, one intact Core-retained source, and no statement that grades have been published.

Each case checks the inbox original SHA-256 remains unchanged, output does not echo the temp workspace path, and no raw PDS2 QR string appears. Only bounded acceptance markers are printed; failures do not expose exception messages or transcript contents. Case data and acceptance logs remain in the OS temp session for deliberate review rather than automatic deletion. `NO_COLOR` is set only inside the harness and restored.

This **does not** certify physical scanners, live students, teacher account isolation, all module compositions, Linux live admission, one-to-one handler idempotency in failure cases, or Gradebook/Meridian evidence publication. Native Core handler success itself must not be represented as academic scoring/publication by Teacher Home. The E3A producer-only 4/4 ScoreForm witness remains a separate supporting gate; G1 asserts what the teacher UI can honestly verify.

## Running the installed gate after the guarded source qualification succeeds

From the clean issue branch with the three previously authenticated official wheels in one explicit absolute directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File scripts\issue19_e3a_windows_installed_acceptance.ps1 `
    -Wheelhouse 'C:\absolute\path\to\official-wheels' `
    -IncludeTeacherHome `
    -AllowPyPI
if ($LASTEXITCODE -ne 0) { throw '19G1 installed Home E2E refused.' }
```

Omit `-AllowPyPI` only when the wheelhouse also has all transitive/native dependency wheels. This installs **only** in a new, disposable virtual environment; it does not modify the development `.venv`. The explicit opt-in may install/download dependencies and execute local **synthetic** producer handlers. No real teacher workspace may be used. The expected positive marker is `SUITE19_G1_INSTALLED_TEACHER_HOME_ACCEPTANCE_PASSED` followed by `SUITE19_G1_ACTUAL_INSTALLED_HOME_VERIFIED`, not merely E3A's older native rehearsal marker.

## Remaining #19G / audit

G1's source unit tests and Windows developer-venv regressions cannot substitute for the above installed run. Following a green installed gate, review Linux default-deny/preview behavior and producer-specific manual handoff, run an adversarial privacy/navigation matrix, and reconcile exact #19 issue acceptance criteria before closure. No installed acceptance is claimed until the user supplies the actual final transcript.
