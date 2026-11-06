# Issue #49 — Slice 72 validation

## Scope

New additive implementation: `paper_data_suite/evergreen_plan_inert_selection.py`.

New additive tests: `tests/test_issue49_slice72_plan_inert_selection.py`.

No change to live `pds` CLI, production launch routing, witness CAS writer, key provisioning, classroom workspace or existing update/recovery modules.

## Expected coverage

- Explicit consent, bounded typed evidence, independent witness transport/pin, whole-second clock and exact platform inputs.
- Strict Slice-68→70→71 transaction, baseline, wheel/native digests and previous receipt identity.
- Exact rev-2 `ACTIVATION_INTENT` journal and previous observation-record hash.
- Prior pending capsule rejection; no fallback to an offline, unsigned or unprotected selection path.
- Reauthentication of signed plan and physical staged files before handing off.
- Delegation to existing locked Slice-40 selector with minimum independent witness revision.
- Exact return, selected local pointer, recovery-capsule identity and retained journal verification.
- Post-write corrupt/missing recovery evidence requires explicit manual reconciliation; never auto-retry or clear state.
- No package execution, installation, receipt or witness CAS during adapter preparation.

## Pre-package local qualification

40 tests passed with isolated typed test stand-ins. Python parsing and source ZIP hashes must pass. These checks **do not** establish real witness acceptance, real root signatures, or complete repository compatibility.

## Windows repository acceptance

Runner requires exact commit `37f1117` full SHA, matching origin and remote, clean branch and four nonexisting additive paths. It checks archive manifest and hashes; runs Ruff import sorting/format/lint, strict mypy on the new production module, the complete Issue #49 Slice 1–72 and existing Suite CLI tests, plus `python -m pip check`; verifies staged scope/whitespace; commits and pushes only after all gates succeed.

The Windows default unprivileged symlink test skips are environment-dependent and must be reported; other failures must stop without commit/push. A failed additive application requires a state-guarded continuation, not rerunning the first apply runner.
