# Slice 65 validation and handoff

**Base commit:** `7366d50e7a8a4707731646323976499564d46a0e` on `49-evergreen-launch-and-supported-composition-upgrades`.

**Source scope:** two tracked files (`paper_data_suite/cli.py`, `paper_data_suite/evergreen_selected_witness_cli.py`), four additive files (the `evergreen_update_plan_cli.py` implementation, this slice's regression test, and two documentation files), plus exact noncommitted patch manifest in the distribution ZIP. The runner stages only the six actual repository source/doc changes.

**Qualification gates:** exact source ZIP hashes and patch-once anchors; exact Git branch, origin, remote and clean worktree; Ruff import and formatting normalization checked for AST equivalence, followed by check-only lint/format; strict mypy on all three touched production modules; all `tests/test_issue49_slice*.py` and original CLI tests; `python -m pip check`; staged whitespace/scope and remote fast-forward precheck; commit/push only on success.

**Security regression assertions:**

- Valid selected-witness evidence and authenticated catalog produce an explicit per-module plan, PDS dependency closure and exact integration impacts.
- Multiple target arguments support a requested whole-composition change; REMOVE is not silently inferred.
- Invalid/duplicate/missing targets refuse **before** witness/certificate reads and before any installer or launch code can run.
- Invalid witness evidence and unsigned/revoked/unavailable releases fail without reporting a successful plan.
- Historical `pds modules`, `pds doctor`, `pds launch` behavior is unchanged. The old Slice 63 witness diagnostic returns identical text through a one-call wrapper.
- No software, receipt, active selection, classroom data, or wheelhouse mutation. A successful preview is not an active installation or permission to apply.

**Windows caveat:** symlink-creation tests may skip without Developer Mode/admin rights; report the skip count accurately. Full Windows results are the authoritative qualification; isolated tests and syntax checks are preparatory only.
