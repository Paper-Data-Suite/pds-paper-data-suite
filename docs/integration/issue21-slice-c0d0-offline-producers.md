# Suite #21 — C0/D0: offline Quillan and Concord release evidence

**Status:** Source committed; Windows-focused pytest/Ruff/mypy **pending**. This is intentionally a narrow, non-executable prerequisite, not the live provider adapter or official installed-wheel acceptance.

## Deliverable

`scripts/issue21_scoreform_offline_preflight.py` now contains a single shared `inspect_named_producer_offline_release(..., owner_id=...)` that checks a specifically selected **Core + one producer** pair using the existing #16 exact-wheel inspector and installed entry-point metadata reader. The original `inspect_scoreform_offline_release` signature, evidence vocabulary and ScoreForm CLI remain stable and covered by the B1.0 tests.

`scripts/issue21_other_producers_offline_preflight.py` exposes an **explicit**, non-startup CLI with `--owner quillan` or `--owner concord`. The exact published release pins come from `scripts/issue16_official_wheel_acceptance.py`:

| Producer | Official wheel paired with Core v0.6.6 | Exact published SHA-256 |
| --- | --- | --- |
| Quillan v0.10.6 | `quillan-0.10.6-py3-none-any.whl` | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |
| Concord v0.3.4 | `pds_concord-0.3.4-py3-none-any.whl` | `35fbebf4338420c83047f0cb4a09d06b22bb493abf4d67e6082e59ae4fc35b23` |

The Core pair component remains `pds_core-0.6.6-py3-none-any.whl`, SHA-256 `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301`. The candidate's exact public entry-point target/declared distribution/version are read from the fixed #16 spec, not guessed from source or installed code.

## Invariants and limits

- The named owner is one of `scoreform`, `quillan` or `concord`; an unknown owner is refused **before** wheel or metadata observation.
- Only the **selected** producer's pair is checked. Missing/invalid Core or selected producer wheel bytes or metadata, missing/mismatched installed versions, duplicate or foreign selected entry-point declaration, mismatched target and metadata failures refuse with bounded static codes.
- Other producers' entry-point declarations can coexist but no Python provider modules, factories or attention callbacks are imported or executed by this check.
- Output `metadata_consistent_not_admitted` is **not** a publisher attestation, verified **installed executable bytes**, a callable Core profile, an approved request context or authority to evaluate. Even a matching exact published wheelhouse does not prove the running package was installed from it.
- No private workspace data, students, roster, returned-paper records, academic grading, publication, launch, cached reports or #20 label policy are accessed or modified. No broad provider diagnosis.
- Windows hosts that deny symlink fixture creation have a documented coverage limitation, not a pass on symlink protection.

**Core [#249](https://github.com/Paper-Data-Suite/pds-core/issues/249) remains the hard dependency** for safely selecting one executable Core-owned provider profile. It requires a newly **published** Core release (and renewed source/wheel pin); old Core 0.6.6 does not gain the API merely because a new source branch is merged.

## Focused source qualification

```powershell
& {
    $ErrorActionPreference = "Stop"
    git pull --ff-only origin 21-integrate-scoreform-quillan-concord-attention
    if ($LASTEXITCODE -ne 0) { throw "git pull failed" }

    python -m pytest -q -ra `
      tests/test_issue21_slice_c0d0_offline_producers.py `
      tests/test_issue21_slice_b1_offline_scoreform.py `
      tests/test_issue21_slice_b0_scope_selection.py
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

    python -m ruff check `
      scripts/issue21_scoreform_offline_preflight.py `
      scripts/issue21_other_producers_offline_preflight.py `
      tests/test_issue21_slice_c0d0_offline_producers.py `
      tests/test_issue21_slice_b1_offline_scoreform.py
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed" }

    python -m mypy `
      scripts/issue21_scoreform_offline_preflight.py `
      scripts/issue21_other_producers_offline_preflight.py
    if ($LASTEXITCODE -ne 0) { throw "mypy failed" }
}
```

### Optional real downloaded-wheel verification, no provider execution

In a **previously populated, explicitly chosen** official wheelhouse, run these two commands separately:

```powershell
python -m scripts.issue21_other_producers_offline_preflight --owner quillan --wheelhouse "C:\Path\To\Wheelhouse"
python -m scripts.issue21_other_producers_offline_preflight --owner concord --wheelhouse "C:\Path\To\Wheelhouse"
```

There is no implicit download; missing wheel or incompatible installed package returns a static refusal and nonzero exit code. The B1 ScoreForm CLI remains unchanged.

## Next stage

Once the focused tests pass, C0/D0 are **source-qualified only**. The actual Slice C/D provider callbacks, real official installed-wheel and publisher evidence, privacy-reviewed category displays, synthetic read-only attention queries, and independent 3-owner Core invocation results remain unproven and blocked on Core #249 plus exact release admission.
