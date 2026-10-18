# Issue #49 Slice 18 — Verification and acceptance

**Base:** `d24d036e556b52d5c1cf346f1bdd552938e7dc8c`
**Scope:** `evergreen_public_contract_acceptance.py`, its focused unit tests,
and this architecture/validation documentation. No modifications to existing
Suite runtime, managed install or launcher paths.

## Focused checks

The synthetic fixture uses a root-signed wheelhouse lock, a matching staged
Python environment, an unarmed verification journal, and signed synthetic
native executable evidence. The opt-in target-import subprocess is mocked
in the normal suite. No actual candidate package code is executed by tests.

Cases include exact root console ownership/entry-point names, use of the
isolated interpreter with `-I -B`, full installed wheel-payload file auditing,
`RECORD` validation, tampered Python code and altered native executables,
extra site packages, interrupted journal/selection state, imported-code
mutation, CLI import failure, process timeout, spawning failures, staged
working-directory separation, lock contention, and malformed input refusal.

Run Windows gates via `run_slice18.ps1`: exact commit/branch, clean checkout,
SHA-256 payload manifest, Ruff import sorting, Ruff check/format, strict mypy,
Slices 1–18 focused pytest, `pip check`, exact Git staging, whitespace check,
commit and push after all gates succeed.

Tests and staging code do not touch teacher OneDrive workspace or installed
production applications. The CLI target import probe is never called by
`pds launch`, doctor, update discovery, or the package runner itself.

## Acceptance limitations

A synthetic successful subprocess does **not** qualify real Windows binary
execution, real Core/module provider imports, public interfaces, persisted
software ownership, active state, or production signer provisioning. Root-signed
locked package identity alone is not per-module publisher-signed release
identity. Record these separately in the later issue #49 acceptance gate.
