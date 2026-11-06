# Issue #49 — Slice 85 validation and acceptance

**Parent:** Slice 84 commit `261326c261d63f4bb4812207b4ea9e20e048604e` on `49-evergreen-launch-and-supported-composition-upgrades`.

**Exact additive file set:** `paper_data_suite/evergreen_plan_capsule_clearance_preflight.py`, `tests/test_issue49_slice85_capsule_clearance_preflight.py`, this validation note and `docs/architecture/issue-49-capsule-clearance-preflight.md`.

## Runtime acceptance (must be observed on Windows)

- Ruff import sorting, format check and lint of both new Python files; strict mypy of the new production module; isolated Slice 85 pytest suite; every accumulated Issue #49 pytest regression and `tests/test_cli.py`; `pip check`.
- The original protected reservation through signed convergence chain remains immutable, independently authorized and stored in the **same** protected SQLite connection. A forged or absent convergence claim is denied even if caller dataclass fields appear plausible.
- One valid whole-file recovery capsule SHA-256 plus double protected byte inspection succeeds once without changing or deleting the capsule. Database reopening permits read-only observation, but refuses second preparation.
- Deny missing or changed capsule bytes, mismatched pinned identity, regular-file/parent/fence/writer flags not strictly true, capsule drift across samples, predecessor-active receipt, missing protected convergence, changed witness key, unresolved writer operation, and unprivileged service context.
- Demonstrate `CHECK`-constrained status and typed/digest-validated readback. No file deletion, hidden reset, automatic retry, rollback, launch, update journal switch, or witness commit is added.
- Guarded runner refuses wrong HEAD, origin, remote, dirty worktree, already-present paths, source hashes, or omitted `--apply`. It performs Git commit/push only after all checks pass. No reset, stash, force push or automatic repair.

**Security caveat:** Python callbacks and simulated fixture flags do not validate actual Windows service custody, signed physical evidence provenance, target identity, filesystem tamper protection or crash durability. Those remain blocked production acceptance steps. No automatic capsule deletion is introduced in this slice.
