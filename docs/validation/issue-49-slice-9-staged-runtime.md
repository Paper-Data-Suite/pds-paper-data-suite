# Issue #49 Slice 9 — Staged virtualenv metadata acceptance

**Scope:** Four new files: one read-only source, one focused test file, this
validation record and one architecture record. Existing Suite behavior and
historical exact-version manifest remain unchanged.

## Required focused validation

```powershell
python -m ruff check --select I --fix paper_data_suite/evergreen_staged_runtime.py tests/test_issue49_slice9_virtualenv_runtime.py
python -m ruff format paper_data_suite/evergreen_staged_runtime.py tests/test_issue49_slice9_virtualenv_runtime.py
python -m ruff check paper_data_suite/evergreen_staged_runtime.py tests/test_issue49_slice9_virtualenv_runtime.py
python -m ruff format --check paper_data_suite/evergreen_staged_runtime.py tests/test_issue49_slice9_virtualenv_runtime.py
python -m mypy --strict paper_data_suite/evergreen_staged_runtime.py
python -m pytest -q tests/test_issue49_slice1_policy.py tests/test_issue49_slice2_catalog_contracts.py tests/test_issue49_slice3_signature_verification.py tests/test_issue49_slice4_trust_and_cache.py tests/test_issue49_slice5_rotation_and_artifacts.py tests/test_issue49_slice6_wheelhouse.py tests/test_issue49_slice7_signed_lock_and_records.py tests/test_issue49_slice8_staged_site.py tests/test_issue49_slice9_virtualenv_runtime.py
python -m pip check
```

Local (Linux container): **295 focused tests passed**, including **22 new**
Slice 9 tests. On Windows, prior symlink-permission tests can skip (without
weakening their assertions). Native Ruff and mypy are run on the user's active
Windows repository before any commit. No expensive unrelated full suite tests
are needed at this no-production-wiring stage.

The runner requires the exact Slice 8 commit `7142c0356871790368d3a0fd2dde326533eb2dd8`,
expected branch and clean tree; stages only four paths, enforces staged diff
whitespace and scope, then commits and pushes after all checks pass. If a gate
fails, applied files stay uncommitted for a focused recovery.

## Security promises NOT made

The audit never asserts that generated Windows PE code or the staged interpreter
is authenticated, executes none of it, does not establish a protected active
receipt, and does not change the Suite launcher, doctor, managed updater,
installation, Core workspace, or classroom data.
