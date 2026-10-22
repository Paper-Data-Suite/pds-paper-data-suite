# Issue #49 — Slice 43 validation handoff

## Strict Windows gate

Run `run_slice43.ps1 -Repo .` on `49-evergreen-launch-and-supported-composition-upgrades` at exact SHA `e2b1c5cf3aeacff5bf4e5b8ae9dcc1c6074782b7`. The runner refuses incorrect origin, branch, local HEAD, remote HEAD, a dirty working tree, an existing target or changed payload hash. Only four new files are copied before validation. It invokes Ruff import sorting and formatting, Ruff lint/format check, strict mypy for the new production module, all Slice 1–43 pytest modules, `pip check`, the exact staged-path guard and Git whitespace validation. Only after all gates succeed will it commit and push.

## Regression acceptance

The new tests exercise: exact canonical prior/successor proposal, controlled persistence with untouched journal/pointer/capsule, no classroom workspace mutation, fresh signed predecessor check, signed successor readback, explicit unresolved predecessor classification, missing/replayed/corrupted/noncanonical proposal refusal, altered pending capsule/selection/journal, forged or stale draft/signature, witness outage, changed local state across a remote read, concurrent lock refusal, symlink refusal where available, interrupted atomic write, and no production launch or service CAS.

The local proposal and tests **do not** qualify physical activation. They do not replace the existing publisher/native/pip tests and do not establish external witness independence, protected local file custody, or service-side consent. The Windows run establishes software regression acceptance, not a live end-to-end deployment qualification.

## Handoff

Expected commit subject: `feat(suite): persist pending successor proposals for signed recovery (#49 slice 43)`.

Record the actual test pass/skip counts and commit SHA from the user's Windows environment. On any failure, do **not** bypass it or push a partial commit; inspect the exact error and supply a bounded correction package.
