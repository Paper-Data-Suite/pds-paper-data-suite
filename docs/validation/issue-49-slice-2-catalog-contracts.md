# Issue #49 Slice 2: Catalog contract acceptance

**Scope:** Four additive files, no production-launch or release qualification changes.

New source: `paper_data_suite/evergreen_catalog_contracts.py`.
New tests: `tests/test_issue49_slice2_catalog_contracts.py`.
New architecture: `docs/architecture/issue-49-catalog-envelope-contract.md`.

## Required focused gate

```powershell
python -m ruff format paper_data_suite/evergreen_catalog_contracts.py tests/test_issue49_slice2_catalog_contracts.py
python -m ruff check paper_data_suite/evergreen_catalog_contracts.py tests/test_issue49_slice2_catalog_contracts.py
python -m mypy --strict paper_data_suite/evergreen_catalog_contracts.py
python -m pytest -q tests/test_issue49_slice1_policy.py tests/test_issue49_slice2_catalog_contracts.py
python -m pip check
```

The final application bundle runs this gate **once** against applied files. Tests
cover three role schemas, exact payload-byte preservation, shape-only signatures,
bad hashes, duplicate/unknown fields, malformed UTC/sequence, identity collisions,
unsafe targets, prerelease names, oversized inputs, unsupported algorithms, and
unknown signing keys as unverified data. No live cryptographic signature or
publisher delegation has been verified by Slice 2; these are mandatory future
slices before launcher integration.

After the gate passes, stage the **exact four-file** scope, run
`git diff --cached --check`, commit, and push. Do not run the same expensive full
suite tests twice. The existing Suite v0.1.0 manifest, launcher, doctor,
bootstrap, and all module/workspace data remain unchanged.
