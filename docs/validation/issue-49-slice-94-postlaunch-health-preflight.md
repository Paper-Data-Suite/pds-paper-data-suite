# Issue #49 — Slice 94 validation: postlaunch runtime-health preflight

## Scope

Additive files:

1. `paper_data_suite/evergreen_plan_launch_health_preflight.py`
2. `tests/test_issue49_slice94_launch_health_preflight.py`
3. `docs/architecture/issue-49-postlaunch-health-preflight.md`
4. `docs/validation/issue-49-slice-94-postlaunch-health-preflight.md`

## Expected safety outcomes

- The protected process-start reconciliation is durable and matches the exact launch dispatch; any changed upstream record is refused.
- Only a two-sample, unchanged, independently obtained runtime-health observation, bracketed by a fresh signed witness, produces an append-once, non-activating health certificate.
- Missing/unknown process start, absent process, forged executable or service identity, changed instance/heartbeat, false service fences, missing signed witness, unexpected capsule, changed successor, or unavailable independent readers refuse recording.
- Duplicate certification is refused before physical reads. A corrupt record is rejected upon observation. SQLite reopen retains a valid record.
- No launch retry, execution, activation, rollback, slot change or filesystem mutation is implemented by the new coordinator.

## Platform qualification

The source-only archive is verified using SHA-256 and strict four-member scope; Python syntax and SQLite schema/duplicate refusal are checked before release. The guarded runner is intentionally unable to finish Windows qualification in the authoring environment; the exact Windows venv must run Ruff, strict mypy, isolated regression, accumulated Issue #49 and CLI regressions, and `pip check`. **Do not mark committed or production accepted until the Windows log confirms the result.**

Baseline: Slice 93 commit `3007e2ad0070981ba444d954e51f6ffb3b1371bb` on `49-evergreen-launch-and-supported-composition-upgrades`.

Production Windows privileged-process health attestation and activation authorization are not included in this slice.
