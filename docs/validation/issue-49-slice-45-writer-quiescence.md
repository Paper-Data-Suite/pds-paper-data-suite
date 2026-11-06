# Issue #49 — Slice 45 acceptance and limits

## Python-only Windows runner

Apply additive sources from `pds_suite49_slice45_source_only.zip` using the separately supplied `apply_slice45.py` on the exact Suite branch `49-evergreen-launch-and-supported-composition-upgrades` at commit `3f7d3e28f3324880f03fc194aaaf78c1c97413e9` (Slice 44). The runner refuses wrong origin, branch, commit, remote tip, untracked files, pre-existing target files, ZIP layout or SHA-256. Four files are added only after preflight. The source-only ZIP contains **no executable scripts**.

It runs Ruff import sorting, formatter, Ruff lint/format check, strict mypy on the new production module, **all issue-49 slice tests 1–45**, `pip check`, staged whitespace and exact staged path checks. It commits/pushes only when every gate passes. On failure: do not blindly rerun the original installer, restore unrelated work, or force-push; inspect its output and continue from the failed gate.

## Acceptance matrix

- Real signed Ed25519 witness heads plus real `MonotonicCheckpointStore` and Slice-44 `WitnessCasFenceLedger`; service actors and writer supervisor deliberately **test doubles**.
- Admission requires a matching Slice-44 reservation, exact canonical request and authenticated service context; duplicate/competing admission refused.
- Crash after durable possibly-in-flight marker refuses replay even when the witness still shows the predecessor.
- Pre-dispatch stop prevents CAS; post-dispatch stop preserves uncertainty; signed successor observation remains forward-recovery-only.
- Stop supervisor denial/unavailability, wrong witness key, network outage, missing stop request, unauthorized actor, corrupted SQLite row, and concurrent state drift all fail closed.
- SQLite process restart preserves the exact stop state; no launch, classroom writes, automatic CAS retry or rollback.

## Non-certification

These tests do not demonstrate physical termination of CAS workers, service-wide write exclusivity, independently protected credentials, durable Windows power-loss behavior, authenticated consent, installed-byte integrity after CAS, a durable *active* receipt, a recoverable production switch, or teacher-facing launch qualification. None of those capabilities should be claimed on the basis of this slice.

Expected commit: `feat(suite): add service-owned witness writer quiescence (#49 slice 45)`.
