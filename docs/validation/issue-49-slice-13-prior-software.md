# Issue #49 Slice 13 — Previous software byte evidence validation

## Local focused result

- 27 new tests in `tests/test_issue49_slice13_previous_install.py` passed.
- 385 cumulative focused tests across issue #49 Slices 1–13 passed in the local Linux test environment.
- The Windows runner performs Ruff import ordering, Ruff formatting/lint, strict mypy, cumulative focused pytest and installed dependency checks before any commit.

## Covered cases

- Exact selected prior stage, locked wheelhouse, signed executable evidence, signed metadata, transaction and generation reverify.
- Strict canonical record schema, bounded size, unknown fields, duplicate JSON fields, path traversal, invalid hashes, boolean-as-integer and illicit `active`/launch claims.
- Changed executable bytes, changed wheel bytes, signature-input mismatch, changed pointer generation, wrong transaction, wrong wheelhouse path, missing pointer and unresolved recovery marker fail closed.
- Explicit expected record digest mismatch fails closed; locally computed hashes do not grant signing authority.
- Expired metadata refuses a new authenticity claim; read-only checks leave both software trees and classroom data untouched.
- Reparse/symlink safety covered with a permission-aware test that may be skipped on non-elevated Windows systems.

## Gate and release limitation

No root keys, production launch wiring, active receipts, install/activation commands, network downloads, source imports or classroom workspace writes are included. Current signed verification is insufficient for offline-active installed state, and there is no claimed production activation. Stop if any quality gate fails.
