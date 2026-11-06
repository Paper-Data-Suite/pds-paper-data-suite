# Issue #49 Slice 4 — Trust policy and local signed-cache qualification

**Scope:** Five additive files. `pyproject.toml`, the bundled v0.1.0 manifest, legacy Suite CLI/launcher/doctor/bootstrap, and classroom workspace are unchanged.

Added modules:

- `paper_data_suite/evergreen_trust_provisioning.py`: strict independently SHA-256-pinned public-key policy; no production keys and no implicit trust acquisition.
- `paper_data_suite/evergreen_catalog_state.py`: signature-reverified bounded signed metadata cache, revision checkpoints, conservative non-dropping updates, atomic replacement and lockfile.

The focused tests use **synthetic private signing seeds from Slice 3 only**. None are distributed in production code. Tests cover pinned SHA mismatch, malformed keys/policy, exact signed registry + delegated module/integration verification, idempotent cache reload, monotonic revisions, same-revision equivocation, cross-role signing refusal, tampered cache, wrong root policy, expiration, clock regression, stale lock, symlink destination, oversized/duplicate JSON, and failure without partial overwrite.

## Single local gate

```powershell
python -m ruff format paper_data_suite/evergreen_trust_provisioning.py paper_data_suite/evergreen_catalog_state.py tests/test_issue49_slice4_trust_and_cache.py
python -m ruff check paper_data_suite/evergreen_trust_provisioning.py paper_data_suite/evergreen_catalog_state.py tests/test_issue49_slice4_trust_and_cache.py
python -m mypy --strict paper_data_suite/evergreen_trust_provisioning.py paper_data_suite/evergreen_catalog_state.py
python -m pytest -q tests/test_issue49_slice1_policy.py tests/test_issue49_slice2_catalog_contracts.py tests/test_issue49_slice3_signature_verification.py tests/test_issue49_slice4_trust_and_cache.py
python -m pip check
```

The runner checks the exact expected parent commit, current branch, and clean working tree before applying the files. On successful checks, it stages only its five new files, runs `git diff --cached --check`, commits, and pushes. It does not repeat the full suite or installed-wheel tests; production behavior has not changed.

## Explicit limitations

The cache does not establish tamper-resistant rollback continuity after deletion/replacement of the entire local cache, authenticate installed wheels, publish actual production signing keys, enable safe key rotation, or authorize any launch/update action. Report its outputs as signed-metadata claims only. Root trust and protected local state require additional qualification before enabling the production launch path.
