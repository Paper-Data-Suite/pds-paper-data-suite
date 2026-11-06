# Issue #49 Slice 38 validation — read-only activation preflight

- Parent: `5f2f8924373495e2ff0ae15baf975fdbd50cfa2f`.
- Branch: `49-evergreen-launch-and-supported-composition-upgrades`.
- Scope: one additive source file, one additive test file, two Markdown files.
- Focused local tests: 27 new tests passed.
- Combined receipt/witness regression: 205 tests passed (Slices 32–38).
- Checks: canonical signed predecessor, local pointer/journal consistency,
  candidate exact-envelope hashes, pending recovery, no duplicate stages,
  mismatched identities, invalid signing key, old witness revision, malformed
  receipt, local drift during remote query, and classroom non-mutation.
- The Windows runner performs Ruff, strict mypy, all 39 issue #49 test files,
  `pip check`, staged-scope and whitespace checks before committing/pushing.
- Not qualified: deployment independence, protected activation, production
  launcher or update CLI, or an installed released-wheel combination.
