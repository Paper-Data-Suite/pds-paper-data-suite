# Issue #49 — Slice 28 verification

- Exact base: `477ccf5` on `49-evergreen-launch-and-supported-composition-upgrades`.
- Additive: `evergreen_provider_import_probe.py`, one test file, these two documents. Existing live runtime/launcher and historical manifest unchanged.
- Real-pip fixture creates an isolated environment from two internally signed synthetic locked wheels; the signed `demo-app` wheel declares an additional `module_operations` entry point. The test provider's function raises when called, proving the probe only imports and checks that it is callable.
- Synthetic root signature binds the candidate's interpreter and generated console launcher bytes to its signed lock, registry, and prepared transaction. No production keys or teacher data used.
- Negative cases: absent optional provider without a subprocess; absent explicit opt-in; invalid timeout; bad native signature; missing delegated publisher evidence; unsupported Core group; altered installed Python source; tampering during the probe; overlapping classroom/software roots; failed subprocess; workspace remains untouched.
- Local checks: `python -m pytest -q tests/test_issue49_slice28_provider_import.py` passed **16 tests**; affected Slice 24–28 regression set passed **74 tests**. A complete local reconstructed test suite exceeded the container execution limit, and **must** run successfully in the Windows runner before any commit.
- Windows acceptance: Ruff import sorting/check/format; `mypy --strict`; all `test_issue49_slice*.py`; `pip check`; exact staged file scope/whitespace; auto-commit/push only on pass. Existing symlink-permission skips are acceptable and must be reported.
- A passing import probe is neither Core provider-contract validation nor installation activation, trusted receipt, or production launch authorization.
