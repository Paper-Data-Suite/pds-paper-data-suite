# Issue #49 Slice 23 — Validation

Base: `abafa6638a6ac80be11b5a95f8790cd18f53d5d6`

## Scoped changes

- Modify only `paper_data_suite/evergreen_pip_layout_audit.py`: bounded local PEP 610 metadata recognition and expected inventory/RECORD inclusion.
- Add `paper_data_suite/evergreen_pip_direct_url.py`: strict signed-wheel local origin parser, without I/O beyond input bytes.
- Add `tests/test_issue49_slice23_real_pip_direct_url.py`: offline actual pip installation and negative provenance/byte-tamper tests.
- Add this validation note and architecture document.

## Checks

- Apply only against exact expected committed Slice 22 audit Git blob and clean branch.
- Ruff import sorting/format/lint; `mypy --strict` on both affected implementation modules.
- Focused pytest Slices 1–23, including offline `venv --copies --without-pip` and `pip --python` installation of two local fixture wheels. No network access or package index fallback.
- `pip check`, `git diff --cached --check`, exact staged-file scope, commit and push only after validation passes.

Linux focused subset: 69 tests across Slices 20–23 passed; Slice 23 alone: 12 passed. Broad local test suite exceeded its execution limit and is **not** claimed to have passed. Windows completion requires the bundled gates.

The tests do not read or write the Core-managed classroom workspace, nor change the live Suite launcher, managed installations or environment-marker state.
