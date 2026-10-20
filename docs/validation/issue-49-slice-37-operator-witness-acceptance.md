# Issue #49 Slice 37 — Operator witness head acceptance

- Parent commit: `0d8a75e4f799908191c5a695d268d33248373c34`.
- Branch: `49-evergreen-launch-and-supported-composition-upgrades`.
- Scope: one additive Python module, one additive test module, two documents.
- Interface: `python -m paper_data_suite.evergreen_witness_acceptance`.
- No `pds` CLI dispatch change, service startup, signed-key generation,
  activation, installation or classroom workspace access.
- The external witness is **not** considered deployed or independent merely
  because cryptographically valid replies are observed.
- Local validation: 31 new tests pass. Slice 33–37 regression: 146 pass.
- Acceptance gate (Windows): Ruff, strict mypy on source, all issue #49
  slice test files (38 files), `python -m pip check`, exact four-file staged
  scope and whitespace checks; only then automated commit and push.
- The new tests use one fake callable transport to exercise real Ed25519
  signing and SQLite store. Slice 36 separately tests actual loopback mTLS;
  neither fixture qualifies a real independently operated deployment.
