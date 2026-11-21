# Suite #21 — Slice B1.0: offline ScoreForm release evidence

**Status:** Source committed; local tests and exact-wheel acceptance **pending**. This is **not a live ScoreForm integration** and cannot unblock Core #249.

## Existing artifact reuse

`scripts/issue21_scoreform_offline_preflight.py` deliberately reuses the already accepted Suite #16 inspector from `scripts/issue16_official_wheel_acceptance.py`; it does **not** download wheels, invent a publisher-verification scheme, load any entry point or invoke any producer callback.

The fixed candidate pair is:

| Component | Wheel | SHA-256 |
| --- | --- | --- |
| Core v0.6.6 | `pds_core-0.6.6-py3-none-any.whl` | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| ScoreForm v0.13.0 | `scoreform-0.13.0-py3-none-any.whl` | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |

The tool requires an explicitly supplied existing, canonical, unsymlinked wheelhouse. For each wheel, the #16 inspector verifies exact **local file bytes**, parsed wheel metadata and published entry-point declaration. Only after those checks pass, the tool compares **installed metadata**, requiring `pds-core==0.6.6`, `scoreform==0.13.0` and **exactly one** `paper_data_suite.module_operations:scoreform` entry-point declaration with `scoreform.pds_operations:get_module_operations_profile` and owning distribution `scoreform`. A duplicate, a foreign owner, missing/mismatched target, wrong installed version, oversized metadata census or exception is refused without propagating private strings.

It reports one of six bounded codes:

- `wheelhouse_unavailable`: no unredirected, explicit local wheelhouse
- `wheel_evidence_unverified`: a required release file/hash/metadata did not pass #16
- `installed_metadata_unavailable`: installed metadata enumeration failed or exceeded the bound
- `installed_version_mismatch`: installed package version missing or different
- `entry_point_unqualified`: ScoreForm declaration absent, duplicated, wrong owner or wrong target
- `metadata_consistent_not_admitted`: every **offline** observation above agreed

**Critical non-admission invariant:** Even `metadata_consistent_not_admitted` is **not proof of the installed package bytes** or independent publisher authenticity. In particular, matching a downloaded official wheel to installed version and entry-point strings cannot establish that installed Python code came from that wheel. Do not rebrand this code as `provenance_qualified`, an executable profile, a checked callback, teacher authorization, or a safe workspace. A future disposable installed-wheel fixture and post-#249 Core exact-owner API must establish those independent facts.

Core #249 will require a **new published Core release and renewed pin**; this baseline cannot be silently promoted merely because Core source changes or v0.6.6 metadata matched.

## Synthetic tests

`tests/test_issue21_slice_b1_offline_scoreform.py` uses injected synthetic readers. It checks exact Core+ScoreForm ordering, missing or corrupted evidence, mismatched identities, missing/foreign/duplicate entry points, version drift, metadata and inspector exceptions, bounded census, CLI static-only output, no import of the three producers, unchanged synthetic filesystem bytes and Windows symlink refusal when available.

It deliberately does **not** claim to test actual release wheel bytes: the original #16 wheel inspector is already responsible for those bytes; this new test suite uses fakes to prove B1 composition and refusal behavior.

### Focused qualification (maintainer environment)

```powershell
$ErrorActionPreference = "Stop"
git pull --ff-only origin 21-integrate-scoreform-quillan-concord-attention
python -m pytest -q -ra `
  tests/test_issue21_slice_b1_offline_scoreform.py `
  tests/test_issue21_slice_b0_scope_selection.py
python -m ruff check `
  scripts/issue21_scoreform_offline_preflight.py `
  tests/test_issue21_slice_b1_offline_scoreform.py
python -m mypy scripts/issue21_scoreform_offline_preflight.py
```

For an **already populated** local official wheelhouse, explicitly run:

```powershell
python -m scripts.issue21_scoreform_offline_preflight --wheelhouse "C:\Path\To\VerifiedWheelhouse"
```

This command never fetches wheels or loads producer targets. A zero exit code means only `metadata_consistent_not_admitted`. Missing/mismatched evidence exits nonzero. No private paths or exception details are printed.

## Next release-dependent gate

The B1.0 metadata bridge is deliberately isolated from #20's privacy display and from the Suite package startup path. Subsequent B1 work must consume Core #249's separately released public exact-owner diagnostic, verify the actual installed-wheel provenance and exact executable profile, freshly recheck the teacher's B0 scope/consent, and invoke **Core's** `invoke_module_attention` with safe independent failure outcomes.

No change has been made to #49 launch eligibility, #52 Teacher Home, the #20 label allowlist, any academic data, or any producer code.
