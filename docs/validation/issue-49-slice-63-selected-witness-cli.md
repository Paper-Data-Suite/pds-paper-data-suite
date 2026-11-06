# Issue #49 Slice 63 validation plan

**Baseline:** `5d33c10ab387981fa7346259949aa91e19e1fe02`

**Change scope:** one exact `paper_data_suite/cli.py` patch and four additive files (production adapter, tests, architecture and validation docs). No changes to existing witness, selection, package-auditing, or launch code.

## Required negative/positive gates

- Preserved default `pds modules`, `pds doctor`, and `pds launch`; no implicit witness network access.
- Explicit CLI flags require full catalog trust triplet; reject incomplete, competing staged, or metadata comparison modes without fallback.
- Strict JSON configuration: schema version, exact fields, duplicate detection, bounded size, safe existing absolute paths, symlink/reparse refusal.
- No external communication for bad trust pins, missing catalog, extra/missing signed publisher documents, missing/bad receipt, incorrect witness public key, changed TLS CA, or invalid client credential files.
- Reuse independently pinned signed catalog verification, existing mTLS transport, and Slice 62 coordinator. Do not grant launch authority from local selection, self-asserted configuration, or a successful network reply.
- No local file writes and no command/package execution; never render client keys or internal directories in diagnostics.
- Fail closed on signature, witness, physical-stage, and operational failures; do not attempt legacy inventory fallback.
- Ruff import sort + format + lint, strict mypy for new production and changed CLI, Slice 1–63 regression suite plus existing application/CLI suites, `pip check`, staged whitespace and exact file scope before commit/push.

Local isolated smoke tests exercise logic and CLI dispatch with dependency stand-ins; only the user's complete installed Windows checkout can establish the final gates.
