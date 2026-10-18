# Issue #49 — Slice 21 validation

- Branch: `49-evergreen-launch-and-supported-composition-upgrades`
- Expected base commit: `ea0604a` (full SHA pinned by PowerShell runner)
- Files: two new Python files and two new Markdown files only
- Production wiring: none

## Automated gates

- `ruff check --select I --fix` and `ruff format` on only the new code/tests.
- `ruff check` and `ruff format --check` on only the new code/tests.
- `mypy --strict paper_data_suite/evergreen_pip_layout_audit.py`.
- Focused issue #49 pytest slices 1–21.
- `pip check`, exact `git diff --cached --check`, expected staged scope.
- Automatic commit/push only after all gates succeed.

## Scope of tests

Synthetic signed wheels and virtualenvs test the supported pip-generated
INSTALLER/REQUESTED metadata, mapped purelib and platlib files, strict
installed RECORD content, source-wheel mutation, updated RECORD with corrupted
code, unexpected site files and bytecode, unsupported wheel schemes, missing
files, read-only operation and symlink/reparse rejection where supported.

## Residual production gates

Actual Windows ARM64/x64 pip installation smoke; authenticated runtime and
native launcher provenance; publisher-bound candidate acceptance integration;
Core/module provider contracts; protected active-state continuity and crash
recovery; teacher-facing update controls and release qualification.
