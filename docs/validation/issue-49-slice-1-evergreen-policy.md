# Issue #49 Slice 1 — Pure compatibility policy and architecture acceptance

**Status:** Candidate for focused local qualification, not a Suite release.
**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

## Files and scope

Added `docs/architecture/issue-49-evergreen-compatibility-adr.md`,
`paper_data_suite/evergreen_policy.py`, and
`tests/test_issue49_slice1_policy.py`.

No existing source, manifest, launcher, doctor, bootstrap, Core workspace, or
installed package is modified. `evergreen_policy.py` is inert until future
verified-release adapters explicitly consume it. The bundle runner itself is
local development tooling, not a runtime package file.

## Proofs required

- Verified candidate releases are not rejected solely for disagreeing with the
  historical bundled version (there is deliberately no old version input).
- Unknown/revoked release identities, mismatched artifacts, broken dependencies,
  invalid owners, unsafe launchers, unsupported Python and incomplete updates
  block independent production launch.
- Missing optional modules are not reported as a corrupted installation.
- An exact integration attestation remains distinct from public contract
  compatibility; features requiring exact evidence refuse approximation.
- A missing/unqualified integration does not retroactively block an eligible
  standalone module launcher.
- Model inputs cannot pass on accidentally truthy strings/integers.
- No I/O, network, cryptography, workspace mutation, subprocess invocation or
  module-private imports occur in the pure policy boundary.

## Focused gate (single pass after file application)

```powershell
python -m ruff check paper_data_suite/evergreen_policy.py tests/test_issue49_slice1_policy.py
python -m ruff format --check paper_data_suite/evergreen_policy.py tests/test_issue49_slice1_policy.py
python -m mypy paper_data_suite/evergreen_policy.py
python -m pytest -q tests/test_issue49_slice1_policy.py
python -m pip check
```

Runner checks each command's exit code, verifies the expected clean branch and
scope, stages exactly these three files, and commits/pushes **only if all gates
pass**. Full suite / installed-wheel acceptance belongs to later slices where
production behavior actually changes. No redundant dirty-then-clean re-run.

## Limitations

Passing this gate does **not** establish release provenance, signature
verification, installed wheel integrity, offline cache correctness, an updater,
or future-version launch success. Those remain explicitly blocked until their
own implementation gates are completed.
