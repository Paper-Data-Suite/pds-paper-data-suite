# Issue #49 — Slice 24 validation

## Fixtures and assertions

The Slice 24 tests create proper synthetic wheel `RECORD` metadata, an
independently root-signed registry, a root-signed dependency lock, a separately
publisher-signed exact demo-app release, and a genuine **offline pip install**
into a disposable virtualenv. For individual mutation tests, the staged
installation is copied to a disposable test directory; the original wheelhouse
and signed provenance remain unmodified. No teacher workspace is involved.

Tests cover:

- Valid genuine-pip inventory joined to the registered exact PDS release,
  with script ownership and imported-code execution explicitly absent.
- No publisher envelope, unauthorized foreign signer, wrong signed console
  target, or unexpected extra publisher envelope.
- Tampered installed source, generated launcher, PEP 610 origin, and startup
  injection.
- Publisher evidence changed between verification phases and invalid input
  failing without modifying the stage.

## Qualifying Windows gates

Run the bundled PowerShell script on the exact base branch/commit. It runs
Ruff lint, formatting, strict mypy, focused pytest (Slices 1–24), `pip check`,
exact Git staging/whitespace checks, then commits and pushes only on success.
Windows symlink tests may be skipped if the user lacks symlink privileges.

This slice does not wire its observation into production launch or activation.
