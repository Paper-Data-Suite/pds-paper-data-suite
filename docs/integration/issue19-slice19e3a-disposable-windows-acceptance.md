# Suite #19 — Slice 19E3A: disposable installed-wheel Windows acceptance

**Branch:** `19-teacher-home-returned-paper-workflow`
**Exact parent:** `b33b7b3cd42b6c88ee4def1645f0f25fd7340c60`
**Scope:** one explicit acceptance runner over existing published #18 tests; no new Core dispatch or producer API.

## Motivation and evidence boundaries

E1 gives an isolated installed-runtime readiness *diagnostic*, never dispatch permission. E2 pins a static two-page synthetic ScoreForm/Quillan QR fixture and verifies native PDF/QR decoding, but does **not** exercise issued producer records. The already-qualified Suite #18 scripts do: an actual issued 4/4 ScoreForm sheet, an issued Quillan response, original-source Core retention exactly once, cancellation of both separate review challenges, fresh preparation from retained bytes, and two genuine Core producer handler outcomes. Reuse them; do not implement another routing loop.

The opt-in `scripts/issue19_e3a_windows_installed_acceptance.ps1` accepts an **explicit absolute directory of the three pinned official wheels** and runs on Windows Python 3.11. It verifies official release SHA-256 with #18, builds Suite `0.1.0` from an exact clean committed `git archive` **in temporary storage**, creates a new disposable virtual environment, and installs only the three exact published wheels and the locally built Suite candidate plus required dependencies. It checks `pip check`, installed package versions and module import locations, profile ownership, the E2 real ZXing/PDFium two-page fixture, E1 action-time read-only diagnostic, and all three native Suite #18 synthetic rehearsals. Each rehearsal gets a different fresh, empty `suite18_synthetic_workspace` under the system temporary directory. No teacher workspace is read or written.

By default dependency resolution is **offline** (`pip --no-index --find-links <wheelhouse>`): all transitive dependency wheels must already be available in that directory. `-AllowPyPI` is an **explicit opt-in for dependency download to the disposable environment**; the three published Core/ScoreForm/Quillan wheel paths remain exact local artifacts and are authenticated before installation. No updates, installs, or repairs happen inside the caller's development `.venv` or OS Python. The script leaves its synthetic session under the OS temp directory for review; it does not automatically delete evidence or copy it into teacher workspaces.

## What a full pass proves

A successful run confirms the selected Windows Python **3.11 interpreter running as native `win32`**, pinned imported wheel versions, installed dependency consistency, published wheel payload comparison, native PDFium/ZXing QR scanning, actual registered synthetic ScoreForm and Quillan Core handler invocation via existing #18 rehearsals, cancellation-before-write, and source-fidelity checks. It does **not** authenticate arbitrary loaded native DLL provenance, assert that all possible scoring/grade effects are complete, test a physical scanner, or establish production teacher-workspace safety. Quillan's `handler_returned` is not evidence capture; ScoreForm 4/4 is not a Meridian grade.

The E3A runner is **not** a live application command, not executed at startup, and never changes the default empty `qualified_modules` policy. Any failure terminates without a positive final marker. No automatic replay/retry occurs. Printed native test JSON concerns synthetic records only.

## Windows execution after E3A source qualification

Use your own **previously authenticated** wheelhouse. The path is a parameter, not a guessed location. In your clean Suite checkout on the qualified issue branch:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File scripts\issue19_e3a_windows_installed_acceptance.ps1 `
    -Wheelhouse 'C:\absolute\path\to\official-wheels' `
    -AllowPyPI
if ($LASTEXITCODE -ne 0) { throw '19E3A installed acceptance failed.' }
```

Remove `-AllowPyPI` only if the wheelhouse also holds all compatible transitive/native dependency wheels. Do **not** point the script at an actual teacher workspace or confidential scans. Expect final markers `SUITE19_E3A_SYNTHETIC_INSTALLED_ACCEPTANCE_PASSED` and `SUITE19_E3A_DISPATCH_REMAINS_DEFAULT_DENY` only after all installed tests finish. Record whether dependency download was allowed and native package versions; do not report a pass before executing it.

## Next — 19E3B / 19G

Once actual Windows installed acceptance exists, review the provenance boundary and define a narrow *action-time* producer admission policy for this one known composition, with revalidation immediately before #18 `execute_with_core_review` and the independently reviewed second teacher decision. Retain the default-deny state on other versions, missing dependencies, missing Core profiles, or a stale/advisory witness. Full Home walkthrough in a built Suite wheel and Linux counterpart remain #19G. This slice makes no producer eligible on its own.
