# Issue #49 — Slice 53 validation and acceptance

## Review scope

Four additive files only: production transport handler, test file, architecture note and validation note. No changes to existing activation, witness, update, application launcher, workspace, receipt or doctor modules. The branch baseline for application is full SHA `dce801ca7d8207a493ed537c0c53bb0c784a2f7d` (Slice 52).

## Positive acceptance

- A canonical nested Slice-42 witness proposal plus 32-byte client challenge round-trips as exact canonical JSON and is parsed and independently signed only after the service identity callback maps a DER fingerprint to a service authorization context.
- An Ed25519 signature returned by the service verifies through the existing Slice-50 verifier using a separately pinned service public key and the exact challenge, installation identity, receipt chain and witness revision.
- The result identifies itself as an observation and has no methods to activate, rollback, launch, clear or commit anything.

## Negative acceptance

- Unknown/wrong method or route, duplicate/forged client headers, invalid content framing, oversized/missing bodies, noncanonical/duplicate JSON, unknown fields, nested mismatched witness proposals, changed challenge, missing/invalid verified peer DER, or unknown client certificate cannot cause a signer call.
- Unauthorized or absent service gate row, pending CAS, predecessor-stopped classification, stale/wrong request, unavailable policy, or signer failure returns only fixed error JSON.
- No subprocess execution, socket creation, local active receipt mutation, classroom-file writes, witness CAS write, or production CLI activation is called by the handler.

## Required Windows validation before commit

The standalone guarded Python runner verifies exact ZIP members with SHA-256, immutable expected branch/HEAD and remote origin, clean worktree, then applies only the four new files. It runs Ruff import sorting, Ruff formatting, Ruff lint, Ruff format verification, strict mypy of the new production module, complete `tests/test_issue49_slice*.py` (Slices 1–53), `pip check`, staged whitespace/scope, and remote freshness before commit/push. Any failed gate stops without commit or push. Windows unprivileged-symlink skips are tracked separately and do not replace installed-wheel qualification.

## Remaining risk

The tests use synthetic certificates, service contexts, gate callbacks and Ed25519 keys. They **do not qualify a deployed mTLS server, Windows service principal, actual process supervisor, hardware-backed key custody, physical update activation, or cross-module installed wheel launch**. No production use is authorized by this slice.
