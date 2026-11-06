# Issue #49 — Slice 22 validation

Base commit: `a61de79e97a2f1c3a7b8c0dd9aba419ef67fd95c`.

## Gates

The guarded Windows runner checks the exact branch, pristine checkout,
committed blob SHA for the modified Slice 21 audit module, and all package
payload SHA-256 hashes before copying five scoped files. It then runs Ruff
sorting/formatting/lint, strict mypy for both source modules, focused tests
for Slices 1–22, `pip check`, staged whitespace and file-scope verification.
Only an all-green result is automatically committed and pushed.

## Focused acceptance

- Both `Lib/site-packages` to `Scripts` and POSIX site to `bin` pip paths.
- Exact hash/size, ownership, and complete wrapper listing in strict mode.
- Source, script and `RECORD` bytes unchanged by a passing audit.
- Bad hashes and sizes, unhashed script rows, duplicates, unowned scripts,
  case aliasing, normalized traversal, foreign wheel ownership, incomplete
  launcher claims, and source-code tampering rejected.
- Previous Slice 21 synthetic fixture compatibility retained by default.
- No production launcher or installer invocations.

Local Linux baseline: 555 focused tests passed across Slices 1–22. Windows
Ruff, mypy, and pytest results are the release-gating authority; unprivileged
symlink tests may skip according to local Windows permissions.

External trial: offline pip installation of an independently generated simple
console wheel using `--no-index --no-deps --no-compile --find-links` confirmed
that pip records the generated executable using `../../../bin/prober` on the
Linux Python 3.13 environment. That trial is a behavior check, **not** an
end-to-end PDS installation qualification.
