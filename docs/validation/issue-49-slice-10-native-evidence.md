# Issue #49 — Slice 10 verification

## Scope

One standalone root-signed exact-native-binary evidence verifier, with synthetic signing tests. Four additive files; no launcher, package resolver, bootstrap or workspace writes.

## Focused gates

Run `ruff check` and `ruff format --check` on the new Python source and tests; `mypy --strict` on the new source; existing Slice 1–9 focused tests plus Slice 10 tests; `pip check`; staged whitespace and exact file scope before commit.

Slice 10 tests cover synthetic Ed25519 signature verification, Windows and POSIX virtualenv layouts, changed Python binary hash/size, changed console-executable bytes, forged delegated signer, absent/duplicate root signatures, unknown/duplicate/unsafe file pin entries, lock/registry/transaction/trust binding, metadata validity, revision rollback/equivocation, rejection of an altered signed payload, and read-only file behavior.

Local focused run from the isolated test workspace: **318 passed**. No local Ruff/mypy installation was available; the guarded PowerShell runner performs both on the Windows repository before committing. The Windows-specific earlier symlink tests may be skipped without developer symlink privileges; all other security tests must pass.

## Explicit non-goals

- No installation or execution, no trusted executable generation, no root private key publication.
- No authenticated active-installation receipt, activation, rollback, or launch eligibility.
- No automatic trust authority derived from local hashes, and no promise of future root signing for every device.
