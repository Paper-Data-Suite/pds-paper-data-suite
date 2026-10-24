# Issue #49 — Slice 55 validation: recovery HTTPS client

## Before application

Guarded runner checks exact branch/remote HEAD `71949cc33d7b2027d21864001e0205824c726d7d`, clean worktree, expected PDS origin, exactly four additive source-ZIP entries with SHA-256 and size, safe targets, and exact stage scope. A refusal leaves the commit unattempted and does not reset any work.

## Focused tests

`tests/test_issue49_slice55_recovery_observation_https.py` uses the Slice-54 synthetic certificate fixture and actual loopback mTLS server, with the recovered signing statement verified by Slice 50. More focused cases exercise the wrong independent Ed25519 key, wrong CA hash, absent/symlink credential, invalid origin/port/timeout/public key, non-aware validation time, internal nonce generation and replay-distinct request challenges, denied redirects and non-200 HTTP statuses, duplicate or cacheable/unframed response headers, content or transfer encodings, oversize/truncated signed payloads, and stale/forged signatures.

These tests are **synthetic**. A test-generated CA and signer are not a deployed trusted service. Import of the client never binds, sends, changes software, or reads student workspace data. Existing Slice-54 HTTPS server tests independently cover malformed requests and unauthenticated TLS clients.

## Required Windows execution gates

The runner runs:

1. Ruff import sorting and formatter, lint and format verification on the two new Python files.
2. Strict mypy on the new production module.
3. Full issue-#49 Slice 1–55 pytest inventory (56 files in this branch), including transport and installed-byte negative tests; unprivileged Windows symlink skips are expected where applicable.
4. `python -m pip check`.
5. Exact staged-file scope, staged whitespace and unstaged-diff checks; remote remains at baseline before commit.
6. Commit and push only if every gate succeeds. Log the resulting commit, totals and skips.

## Remaining gates

Independently administered service protection, signed trust-root lifecycle, actually controlled writer stop/join, atomically protected installed receipts and physical slot selection, Windows x64/ARM64 installed-wheel acceptance, teacher CLI/doctor/launcher integration, and final milestone-level qualification **have not been established by this slice**. Never enable production activation or rollback on the basis of this transport.
