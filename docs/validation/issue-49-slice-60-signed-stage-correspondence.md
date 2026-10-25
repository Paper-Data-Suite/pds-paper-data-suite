# Slice 60 qualification — authenticated cached releases versus staged file audits

- Additive-only changes: `evergreen_catalog_stage_correlation.py`, a focused test module, and two documentation files.
- Source-only, no import side effects, no networking, subprocess, package execution, CLI activation, receipt write, lock change, or classroom data access.
- Exact negative cases: unsupported inputs; unauthenticated or mismatched registry/module envelope; unknown publisher; unlisted/version/filename/wheel-hash mismatch; revoked wheel; publisher file audit failure; root native-signature failure; stage publisher-digest mismatch; changed pip or native audit across paired rechecks.
- Positive synthetic coordinator case: cached delegated release matches audited candidate; root-locked transitive wheel not mistaken for an independently approved PDS publisher; exact transaction/native/pip digests recorded; output remains inert.
- Existing production pip-file verification and root-signed native inventory are invoked through their public audit entry points and retain their own established regression coverage.
- Required Windows gates: Ruff `check --select I`, Ruff `format`, Ruff lint/format check, `mypy --strict` on the new production module, focused tests through Slice 60, `pip check`, staged scope/whitespace checks, commit and push only after success.
- The 15–17 unprivileged symlink test skips seen on Windows should remain explicit and should not be silently interpreted as passed tests.
- No claim of real OS-protected active-state authorization or installed-wheel/ARM64 end-to-end operational qualification from synthetic coordinator tests alone.
