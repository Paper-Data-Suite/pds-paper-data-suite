# Issue #49 — Slice 56 validation plan and retained evidence

## In-scope checks

- Valid canonical predecessor/successor witness request and signed Ed25519 service envelope are correlated by a one-call Slice-55 client to a Slice-52 fresh recovery observation.
- Verify exactly one service request precedes two local signed-head reads and one requalification audit; no repeated network request, installed-code execution, mutation, activation, receipt commit or cleanup.
- Wrong transaction, missing service pin, malformed request/clock, wrong input types and missing witness key refuse **before** an external request.
- Service connection/signing failure refuses before local work. A modified envelope, challenge, self-declared status/authority or forged `verified` metadata refuses before local work, regardless of the dataclass type.
- Predecessor signed head, physical byte requalification failure, post-audit changed signed head or exceeded elapsed budget does not produce a successful observation.
- A caller cannot bypass the service fetch by injecting a raw envelope or precomputed convergence object into the new API.
- Retain previously covered Slice-54 real mTLS host tests and Slice-55 real mTLS client round trips. Slice-56 unit tests deliberately reuse genuine Ed25519 canonical input fixtures while substituting local/physical inspectors. Synthetic fixtures **do not establish real independent deployment**.

## Required Windows completion gate

From the pinned Slice-55 commit `cda38b62533844963a61e21b240f0da4f9cd6b02`, the guarded runner must verify exact source archive hashes, clean branch/origin/HEAD, Ruff import sorting and formatting, Ruff lint, strict mypy for the new implementation module, all `test_issue49_slice*.py` regression tests, installed `pip check`, exact staging/whitespace and remote HEAD stability before committing or pushing. Record the observed test/skip totals and commit after the Windows run. Symlink-permission skips must remain visible and must not be reclassified as passing tests.

No real service deployment, protected writer stop/join, operating-system installation transaction, production release validation or pilot launch is claimed by this slice. Do **not** enable activation based on the result.
