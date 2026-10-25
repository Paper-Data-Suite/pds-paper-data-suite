# Issue #49 — Slice 68 acceptance record

## Scope

- New `paper_data_suite/evergreen_plan_stage_installer.py` and focused `tests/test_issue49_slice68_plan_stage_installer.py`.
- Additive code only; no CLI/launcher/doctor/bootstrap activation, workspace data operations, remote download, or installed receipt writer.
- Slice 67 baseline commit: `a1443ac` (full hash checked by guarded apply runner).

## Local qualification prior to Windows

- Python compilation/AST and exact-source ZIP SHA-256 manifest: passed.
- **25 focused isolated tests passed** with stand-ins for existing signed-plan and pip-file verification. These prove orchestration only; cryptographic proof remains covered in prior tests.
- Disposable pip mechanics smoke: actual host `python -m venv --copies --without-pip` followed by `python -m pip --python <candidate>/bin/python install --no-index --no-deps ... <local wheel>` successfully produced only the wheel's target dist-info and `direct_url.json`; the host pip left no additional target pip distribution. This does **not** prove Windows behavior, publisher signatures, or native evidence.

## Windows runner gates (pending)

1. Exact signed-archive byte manifest, exact branch/HEAD/remote and clean tree.
2. Four additive paths only; Ruff import/format/lint and strict mypy on the new production module.
3. Full tests for Issue #49 Slices 1–68 plus the established CLI suites; discover tests portably on Windows and ensure expected new file is included.
4. `python -m pip check`, staged whitespace checks and exact scope; commit/push only on green.

## Deferral / explicit non-claims

This is an explicitly consented local **installer** for a fresh, unselected stage. It is neither a normal teacher update command nor installed-state/launch authority. Independently signed native stage evidence, Slice 67 final signed-byte qualification, and protected activation/recovery remain outstanding.
