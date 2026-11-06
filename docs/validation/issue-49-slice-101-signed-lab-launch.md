# Issue #49 Slice 101 — Windows qualification and lab acceptance

## Source qualification

- Parent: `23cdf83fe834081f8e36f488c95cf9fd424e02ec` on the Issue #49 branch.
- Additive files: `evergreen_signed_lab_launch.py`, `test_issue49_slice101_signed_quillan_lab.py`, and these two documents.
- Ruff (`check`, `format`), strict mypy, focused tests, all `test_issue49_*.py` tests, `tests/test_cli.py`, and `pip check` must pass on the target Windows checkout before commit/push.
- Locally isolated tests: 14 passed under a synthetic filesystem and stubbed signature verifier; Windows full-qualification remains required. The production GitHub code uses actual existing signed-artifact verification, not the isolated test stubs.

## Real signed lab acceptance

The teacher's prior completion yielded signed artifacts in `Downloads/PDS_Issue49_Release_Lab/quillan_signed_release_review/`, with independent trust policy SHA-256:

`cff9d3186807ef8cd1a39d1480910ae4820d4dda9a16939b9e8a1452c51bc720`

The previously tested wheel hash is `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb`. The separate full-dependency lab is `Downloads/PDS_Issue49_Release_Lab/historical_suite_010_quillan_0106_FULL_DEPS_LAB/`.

The lab must first report `SIGNED_LAB_INSPECTED_NO_EXECUTION` and, with explicit `--execute-help`, `SIGNED_QUILLAN_0106_HELP_EXECUTED_IN_DISPOSABLE_LAB`. This is deliberately not a production-launch authorization.

Negative tests reject changed signed wheel files, mismatched pinned policy, wrong release version, missing or incompatible transitive requirements, a second `quillan` console-script owner, inherited site packages, direct-URL runtime dependencies, wrong folder identity, missing wrapper, and incompatible Python requirements.
