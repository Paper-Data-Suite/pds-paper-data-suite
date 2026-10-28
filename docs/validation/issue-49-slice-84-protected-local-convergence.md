# Issue #49 — Slice 84 validation and guarded handoff

## Scope

Exactly four additive source files: `evergreen_plan_local_convergence.py`, `test_issue49_slice84_local_convergence.py`, this validation note and the architecture decision. Baseline commit: `a1abe4a92c85fd0790a0b4cd6a0347b948be3efd`. Branch: `49-evergreen-launch-and-supported-composition-upgrades` in `Paper-Data-Suite/pds-paper-data-suite`.

The coordinator **never invokes** `service_owned_write`; it has no CLI, local path write, capsule delete, switch, rollback, witness CAS or launch operation. Its SQLite row is service-controlled diagnostic convergence only. No synthetic fixture can establish production privilege boundaries.

## Isolated regression contract

Tests use the real prior Slice 78–83 SQLite chain and a synthetic signed Ed25519 witness. Cases cover: authenticated successor read-only classification; one-shot two-readback certification; independent quiescence/readback sequence; preserved capsule and no second writer call; replay refusal; predecessor, missing and unknown receipt classifications; every false writer-termination/fence/durability flag; malformed or mismatched no-inflight evidence; unauthorized service actors; a missing persisted dispatch claim; forged claim; capsule drift; wrong witness key; a physical readback that changes between samples; reopened protected SQLite; corrupt persisted convergence data; revoked operator consent; missing protected readers; and nested transaction refusal.

The tests **do not** claim independent Windows writer custody, actual process-fence enforcement, power-loss durability, signed service proof, or production installation readiness.

## Required Windows qualification

The guarded source-only runner must verify the exact four-file archive and member SHA-256 manifest, Python syntax, expected checkout HEAD, branch, origin and remote, and clean additive scope before writing. Run Ruff import order, format and lint; strict mypy for the production module; isolated Slice 84 regression; all accumulated `test_issue49_slice*.py` and `tests/test_cli.py`; `pip check`; final exact additive four-file scope and unchanged Git parent/remote. Commit and push only after all checks pass, then verify remote SHA and clean worktree. Do not reset, stash, overwrite, force push, retry a previously uncertain operation or automatically roll back.

## Recovery rule

If the runner stops, preserve the four untracked files and report the entire terminal output. Any correction requires an exact-state continuation that validates existing AST/comments and documentation, rather than re-running the additive runner. A completed Slice 84 record leaves the pending capsule and launch prohibition intact.
