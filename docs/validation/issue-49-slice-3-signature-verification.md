# Issue #49 Slice 3: Ed25519 verifier focused gate

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Parent:** Slice 2 commit `aa37586`.

## Scope

Add `paper_data_suite/evergreen_catalog_verification.py`, synthetic signature
fixtures in `tests/test_issue49_slice3_signature_verification.py`, the Slice 3
security architecture and this validation note; declare
`cryptography>=45,<47` in runtime dependencies. Do not replace or edit any
historical v0.1.0 manifest, launcher, bootstrap/doctor code, or installed wheel.

Cryptographic acceptance exercises real library signing and verifying of exact
bytes; invalid/tampered/foreign signatures; two-root threshold; per-module
repository/distribution/key identity; unknown and cross-role delegations;
independent integration signers; current UTC windows; scoped revision rollback;
same-revision equivocation; and mismatch between trust keyrings used for
registry and leaf verification. Test Ed25519 private seeds are **synthetic**
and exist only in the tests, never a production trusted identity.

### Required focused validation (one run on the developer machine)

```powershell
python -m ruff format paper_data_suite/evergreen_catalog_verification.py tests/test_issue49_slice3_signature_verification.py
python -m ruff check paper_data_suite/evergreen_catalog_verification.py tests/test_issue49_slice3_signature_verification.py
python -m mypy --strict paper_data_suite/evergreen_catalog_verification.py
python -m pytest -q tests/test_issue49_slice1_policy.py tests/test_issue49_slice2_catalog_contracts.py tests/test_issue49_slice3_signature_verification.py
python -m pip check
```

The PowerShell runner performs a non-mutating dependency preflight, stages only
five expected files, and commits/pushes only after all checks and `git diff
--cached --check` pass. No full installed-wheel or physical acceptance gate is
needed: existing production launching remains unchanged in this slice.

## Limitations

This gate proves *signature and delegation algorithms* against test fixtures,
not production key provisioning, persisted anti-rollback, authenticated package
installation, module-version forward launching, integration correctness, or
release artifact provenance. Production trust activation is prohibited until
those separate boundaries are complete.
