# Issue #49 Slice 8 — Focused staged-site qualification

**Scope:** four additive files. Branch must be
`49-evergreen-launch-and-supported-composition-upgrades`, based on Slice 7
commit `63d1f4d20ea80bef2d5850f44b4d54808134423a`.

## Checks

- Authenticate registry and root-signed lock via the Slice 7 verifier; compare
  the prepared record with current signed wheelhouse bytes before inspecting
  the staged site.
- Accept the exact private stage and report hashes, no activation claim.
- Reject changed/missing/extra package content, altered metadata, forged
  prepared records, changed wheel artifacts and unsupported active prefix.
- Reject malformed, incomplete and mismatched installed RECORD hashes/sizes,
  cross-distribution file claims, and path traversal.
- Reject symlinked staged members where local privileges allow creating one.
- Verify source wheel bytes using the same open file descriptor across wheel
  member inspection; never convert a caller-provided path/hash into authority.
- Legacy Suite launcher, doctor, Core workspace and classroom data untouched.

The Windows runner performs one focused gate after applying files:

```powershell
python -m ruff check --select I --fix paper_data_suite/evergreen_staged_install.py tests/test_issue49_slice8_staged_site.py
python -m ruff format paper_data_suite/evergreen_staged_install.py tests/test_issue49_slice8_staged_site.py
python -m ruff check paper_data_suite/evergreen_staged_install.py tests/test_issue49_slice8_staged_site.py
python -m ruff format --check paper_data_suite/evergreen_staged_install.py tests/test_issue49_slice8_staged_site.py
python -m mypy --strict paper_data_suite/evergreen_staged_install.py
python -m pytest -q tests/test_issue49_slice1_policy.py tests/test_issue49_slice2_catalog_contracts.py tests/test_issue49_slice3_signature_verification.py tests/test_issue49_slice4_trust_and_cache.py tests/test_issue49_slice5_rotation_and_artifacts.py tests/test_issue49_slice6_wheelhouse.py tests/test_issue49_slice7_signed_lock_and_records.py tests/test_issue49_slice8_staged_site.py
python -m pip check
```

Only after the gates pass, stage exactly the four additive files and verify
`git diff --cached --check`, then commit and push. A failed gate leaves an
uncommitted local change; never rerun a clean-tree-only script after that.

Local Linux execution: **273 tests passed** across Slices 1–8. Ruff and
strict mypy are not installed in the local packaging environment; the user
Windows runner is the authoritative lint/typing/dependency gate.
