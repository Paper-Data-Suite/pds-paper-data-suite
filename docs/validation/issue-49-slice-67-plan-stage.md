# Issue #49 — Slice 67 validation

- Baseline: Slice 66 commit `6283ce7`; add exactly four files.
- Ruff import sort, formatting, lint and strict mypy on the new production
  module must pass on the Windows qualification checkout.
- Run every `test_issue49_slice*.py` plus the two existing CLI regression files.
- Check no subprocess, socket, package install, active selection, receipt write,
  or classroom workspace access on successful dry-run inspection.
- Negative tests cover malformed input, workspace overlap, software-root
  escape, intersecting staging directories, changed signed plan or witnessed
  baseline, missing or mismatched prepared wheel/lock, altered stage wheel or
  transaction ID, between-audit inventory drift, and refusal propagation from
  publisher/wheelhouse, prepared-record and native evidence verifiers.
- `pip check`, staged whitespace validation, exact Git scope and remote-state
  recheck precede any commit and push.

**Status:** Full repository qualification is required before acceptance.
These tests exercise coordinator composition with explicit stand-ins for
lower-level cryptographic and physical audits. They are not an end-to-end
signed-wheel installation acceptance and do not establish active-launch safety.
