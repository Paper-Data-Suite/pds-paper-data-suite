# Issue #49 — Slice 64 qualification

## Required gates

Windows guarded runner requires exact Slice 63 baseline, canonical origin/branch/remote, clean index/worktree, four additive files, SHA-256-matched source archive, Ruff import sorting and formatting, strict mypy, complete Issue #49 regression suite with existing application CLI tests, `pip check`, staged whitespace/source scope and unchanged remote before commit/push. No automatic cleanup or pre-validation commit.

## Focused acceptance

- Request newer Quillan: change Quillan and dependency-driven Core, leave unrelated ScoreForm unchanged; label the origin of each change.
- Explicit whole-composition changes: add Portia and update Quillan in one review; enumerate the dependency closure.
- Explicit removal: remove ScoreForm without silently removing Core or Quillan.
- Named integration scope: Quillan/Core exact qualification becomes unqualified when its wheel identities differ; independent ScoreForm feature stays qualified. An unsupported platform never inherits exact acceptance.
- External dependencies: report `packaging>=24.0` without claiming a trusted wheel lock or installed environment.
- Refusal: unregistered component, unsigned or revoked version, impossible Core constraint, conflict between fixed request and dependency, forbidden removal, bad Python/platform, changed baseline digest, inconsistent signed publisher identity, external direct URL.
- No file write, network request, package import, installer execution, active receipt change or launcher execution performed by the planner.

The synthetic fixture proves deterministic planning semantics, **not** future official release authenticity or production installed-wheel qualification. Windows native tests and the whole signed dependency lock integration are separate acceptance stages.
