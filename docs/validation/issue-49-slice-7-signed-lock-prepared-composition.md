# Issue #49 Slice 7 — Focused acceptance

**Base commit:** `9506b2c` on `49-evergreen-launch-and-supported-composition-upgrades`.

## Additive scope

- `paper_data_suite/evergreen_dependency_lock.py`
- `paper_data_suite/evergreen_install_records.py`
- `tests/test_issue49_slice7_signed_lock_and_records.py`
- `docs/architecture/issue-49-root-signed-wheelhouse-lock-and-prepared-records.md`
- this acceptance note

No existing runtime code, dependencies, CLI, launcher, doctor, Core workspace, or historical release manifest is edited. Production installation and signing-key provisioning remain explicitly disabled.

## Focused validation (one pass per gate)

```
python -m ruff check paper_data_suite/evergreen_dependency_lock.py paper_data_suite/evergreen_install_records.py tests/test_issue49_slice7_signed_lock_and_records.py
python -m ruff format --check paper_data_suite/evergreen_dependency_lock.py paper_data_suite/evergreen_install_records.py tests/test_issue49_slice7_signed_lock_and_records.py
python -m mypy --strict paper_data_suite/evergreen_dependency_lock.py paper_data_suite/evergreen_install_records.py
python -m pytest -q tests/test_issue49_slice1_policy.py tests/test_issue49_slice2_catalog_contracts.py tests/test_issue49_slice3_signature_verification.py tests/test_issue49_slice4_trust_and_cache.py tests/test_issue49_slice5_rotation_and_artifacts.py tests/test_issue49_slice6_wheelhouse.py tests/test_issue49_slice7_signed_lock_and_records.py
python -m pip check
```

Synthetic crypto fixtures demonstrate authentic root signer quorum; nonroot signing forbidden; domain separation; exact registry-content binding; expiry and interpreter/platform filtering; malformed base64, JSON and wheel pins rejected; monotonic checkpoint and equivocation; physical wheel tamper and unreachable wheel rejected; canonical prepared record roundtrip, mutation and `installed` forgery refused; changed signed lock or wheel bytes requires revalidation; no live installation or classroom workspace writes.

The Windows symlink cases from Slices 4–6 may skip when unprivileged symlink creation is disabled. New signed-lock and prepared-record assertions must pass, not skip. Historical tests beyond these focused boundaries are deliberately deferred until production launch/update wiring changes.

After gates pass, stage exactly five additive files, check `git diff --cached --check`, commit and push. The runner refuses partial repository application, unknown preexisting paths, a dirty repository or incorrect base branch/commit. Full suite and installed-wheel release acceptance come later.
