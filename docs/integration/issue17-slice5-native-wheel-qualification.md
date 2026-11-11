# Suite #17 — Slice 5: native-scanner and official-wheel evidence gates

**Parent:** [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)
**Source baseline:** `17-mixed-paper-read-only-intake-preview` at `20ffb0cfd2ddd8db7497d44ea81129894075ec2d` (Slices 1–4).
**Scope:** Acceptance harness, not a new scanning pipeline or teacher-facing app.

## Separate, honest acceptance levels

Slice 4's Windows tests passed (`105 passed, 4 skipped`) and were committed at `20ffb0cfd2ddd8db7497d44ea81129894075ec2d`. The **four skips** comprise two Windows symlink-privilege cases plus the absent native QR and PDF libraries. Slices 1–4 are **source-qualified** but the absence of `zxingcpp` and `pypdfium2` in the active Suite `.venv` means that they have **not** accepted real native PDF/QR decoding on Windows.

This slice provides **two independent executable checks**. Neither is a claim that students' submitted pages were safely processed:

1. **Native synthetic scan acceptance:** using an independently created throwaway Python environment with official Core v0.6.6, `pypdfium2>=5.13,<6`, `zxing-cpp>=3.1.1,<4`, Pillow, qrcode and packaging. Generate a real nine-page synthetic mixed PDF, PNG and JPEG, decode with the **actual** Suite reader and **real** Core PDS2 parser, and assert physical-page ordering, four supported published module candidates, a Portia syntactic-but-unqualified candidate, invalid legacy QR, conflicting QR, duplicate-exact QR, no QR, source/empty-workspace immutability, and no processing. Outputs only bounded JSON evidence in an external disposable evidence directory. This is a software synthetic-scanner check, **not** hardware scanner, physical-paper, malicious-PDF sandbox or teacher-authorized workflow acceptance.
2. **Exact official-wheel metadata audit:** validate all five frozen official assets (Core, ScoreForm, Quillan, Concord and Vitrine) by SHA-256, wheel `Name`/`Version`, routing entry-point declarations, and the published `pypdfium2` requirement metadata. Read ZIP contents without **installing, importing or executing** producer code. Distinguish *known release-asset digest* from publisher signature or full composition authorization. Produce a manifest that explicitly reports `combined_paper_wheel_installation_qualified=false` and a Concord #170 blocker.

**Do not install Concord's official v0.3.4 wheel alongside the `pypdfium2` v5 native synthetic-scanner environment.** Its hard `>=4.30,<5` dependency is incompatible with Vitrine's `paper` extra's `>=5.13,<6`. The test environment intentionally uses Core and Suite **source** only, and does not bypass producer dependency resolution. Concord must qualify/release its compatible change under [Concord #170](https://github.com/Paper-Data-Suite/pds-concord/issues/170); no silent pin override or bare `--no-deps` installation of the conflicting producer wheels.

## Pinned exact release artifacts (as observed 2026-11-10)

| Repository | Official wheel | SHA-256 |
|---|---|---|
| Core | `pds_core-0.6.6-py3-none-any.whl` | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| ScoreForm | `scoreform-0.13.0-py3-none-any.whl` | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |
| Quillan | `quillan-0.10.6-py3-none-any.whl` | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |
| Concord | `pds_concord-0.3.4-py3-none-any.whl` | `35fbebf4338420c83047f0cb4a09d06b22bb493abf4d67e6082e59ae4fc35b23` |
| Vitrine | `pds_vitrine-0.4.0-py3-none-any.whl` | `0255f9ddad3a7b5216316a964e171271e10655f5822380e64a1254a7e439dfd2` |

These are the *frozen release targets* for this test, not a guarantee that no newer releases exist when it runs. The runner retrieves precisely these wheel filenames from their canonical GitHub release URLs if they are not already in the designated outside-repository wheelhouse; **each downloaded or reused wheel must pass the pinned SHA-256 check before inspection or installation**. A hash match against publicly observed release metadata does not replace independent signed provenance.

## Workflow, permissions and outputs

The runner has two phases. **Source qualification:** exact clean branch and baseline; copy only three new files (`scripts/issue17_slice5_native_acceptance.py`, `scripts/issue17_slice5_wheel_audit.py`, `tests/test_issue17_slice5_qualification.py`) plus this document; run focused tests, Ruff, mypy and Git whitespace; commit/push only on success. **Optional native qualification:** create a new independent venv under the teacher's Downloads (never inside the repository/active Suite environment); install only Core from the pinned wheel and native scanner/test dependencies, then execute the synthetic scan and offline wheel audit, storing JSON evidence in the same outside-repo qualification directory.

Installing source code into a **different** venv does not make a developer Suite wheel an official published Suite artifact. The acceptance runner uses the checked-out Suite source via `PYTHONPATH`; only Core is installed from its exact published wheel. The published producer wheels are **inspected without installation**. Native dependency versions and the relevant pinned release SHAs are explicitly reported, not inferred from a passing test summary.

Failure of any native dependency download/install, actual decoding, or exact wheel check produces **PENDING / NOT QUALIFIED** for that gate. It must not retroactively invalidate already-passed source tests, be mislabeled as a producer release issue, or be silently converted into a skip. Only a verified successful native-run marker and its external JSON constitute a positive native acceptance result.

## Safety and next steps

- Only synthetic QR data and temporary files. No source scan is retained; no `retain_source_scan`, `dispatch_route(s)`, result/grade or Portia domain callback is made. The empty synthetic workspace and sources are hashed/snapshotted before and after.
- This does not test actual scanned paper quality, scanner drivers, hostile native PDF input isolation, process timeouts, Windows symlink/junction attacks, producer-specific validators, or per-handler processing. Bound/untrusted PDF native execution is **not** a sandbox and must not be advertised as such.
- Any physical scanner acceptance should use sanitized, non-student materials and remains a future D3/D4 qualification item. Where actual producer ownership cannot be established, a candidate remains unverified.
- **Concord #170 remains a required subsequent combined-paper composition gate**. If the native decoder accepts, Suite #17's source/preview component may be reviewed/merged with an explicit integration deferral; it is not permission to close #18 or enable #19's Teacher Home action.
- [Suite #18](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/18) must re-open and revalidate originals, obtain teacher authorization, retain via Core, then dispatch; [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19) owns the one integrated UI and actual outcomes.
