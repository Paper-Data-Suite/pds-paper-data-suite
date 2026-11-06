# Issue #49 — Slice 57 validation: protected service nonce claim

## Automated acceptance

`tests/test_issue49_slice57_recovery_nonce_signer.py` checks:

- first valid domain-separated statement signs once and records a SHA-256 nonce fingerprint rather than raw challenge bytes;
- new independent challenges may sign, while duplicate challenges, request-identity changes and process restarts cannot reuse the same installation/challenge;
- sign callback crash/invalid response burns the nonce without retry or signature reissue;
- malformed/noncanonical/extra/duplicate JSON, Boolean revisions, unknown status/authority, wrong domain, nonce size, identity hashes or dates refuse *before* ledger write;
- the service clock is aware, whole-second, fresh and monotonic across signer objects; future, stale and rollback attempts refuse;
- one-day-expired nonce rows are pruned only after durable high-water advance, with old signed messages still outside the five-second issuance window;
- ephemeral SQLite memory connections and preexisting open transactions cannot qualify as a new protected signer;
- a real loopback mTLS Slice-54 HTTP host can use `DurableRecoveryNonceSigner` as its `sign` callback: the first response is signed HTTP 200, replay of the exact client challenge is HTTP 503 with no second signature or additional ledger entry;
- signed recovery observations grant no launch, rollback, witness mutation or receipt authority, and classroom bytes are untouched.

## Validation gate

Run Ruff import sorting/format/lint, strict mypy for the new production module, `pytest -q` across every existing `tests/test_issue49_slice*.py` plus the new test file, `pip check`, Git whitespace/stage checks, and ensure only four additive files are committed. The runner is guarded to exact Slice 56 commit `8ee0631` and will not rebase or reset another worktree.

Isolated non-network tests may run outside the full repository. Real loopback mTLS tests and all Slice 1–57 regressions remain a required Windows qualification before commit; green synthetic tests do **not** establish independent production deployment or Windows ARM64 installed-wheel suitability.
