# Slice 66 validation — authenticated plan-bound wheelhouse

**Scope:** Four additive files. No tracked production edits or CLI activation.

## Expected qualification

1. Verify exact Slice 65 baseline, clean worktree, correct Git remote, signed source ZIP manifest, and absent additive paths.
2. Ruff import sorting, formatting and lint; strict mypy for the new coordinator.
3. Run Issue #49 Slices 1–66 regression tests and both existing CLI suites; dependency consistency via `pip check`.
4. Confirm exact staged file scope, whitespace check, commit and push only upon successful acceptance.

## Isolated acceptance cases

- A signed locked wheelhouse matching the complete recomputed plan can be reported, with no mutation or execution rights.
- Missing PDS packages, extra registered packages, unknown `pds-*` dependencies, altered wheel digests, incomplete root sets, and missing publisher evidence refuse before install.
- Missing wheel files and mismatched registry cache refuse; signed dependency lock refusals do not fall back to unsigned acceptance.
- A second audit detecting drift refuses rather than reporting success.
- Invalid witness/catalog/trust inputs refuse early.

Mocked signing/lock callbacks in focused tests exercise orchestration and negative paths only; full real-signature and wheelhouse verification is covered by the existing Issue #49 trust and wheelhouse tests. Successful synthetic tests do not establish signatures or authorization for official releases. The Windows target still needs end-to-end installed-wheel acceptance with independently provisioned signing keys before enabling managed updates.
