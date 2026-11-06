# Issue #49 Slice 106 — Qualification and acceptance

Parent commit: `24fbaf7ad70fab2e0e2a73386b98759e8b0154b5` on branch `49-evergreen-launch-and-supported-composition-upgrades`.

Additive source: `paper_data_suite/evergreen_windows_deployment_preflight.py`, focused tests and these two documents. The existing `pds launch`, Core workspace, teacher data, Windows security descriptors and actual installation remain unchanged.

Targeted qualification: Ruff full lint and format check; mypy strict for the new module; pytest for Slice 104–106 custody tests; `pip check`. Full Issue #49 regressions intentionally reserved for a subsequent integration/release boundary.

Read-only Windows acceptance:

```powershell
& .\.venv\Scripts\python.exe -m paper_data_suite.evergreen_windows_deployment_preflight
$exitCode = $LASTEXITCODE
Write-Host "Deployment preflight exit code: $exitCode"
```

Interpret `2` as expected **provisioning required** when named directories do not yet exist. `1` is unsafe or unverifiable permission evidence; investigate, do not change ACLs to silence it. `0` proves only that the existing directory ACLs passed this bounded observation, never service/receipt/launch authority. None of the three statuses asserts a protected managed installation.
