# Issue #49 — Slice 39 validation

## Windows acceptance

Run `run_slice39.ps1 -Repo .` from the verified `49-evergreen-launch-and-supported-composition-upgrades` branch at SHA `3bc04bab56fe765abbbb359f18ad4ce7546a4808` using the existing working virtual environment. The runner refuses wrong repository, branch, commit, origin, dirty state, already present targets, incorrect package SHA-256, unexpected staged scope or test inventory. It writes only four new files until the validation gate passes; after success it commits and pushes. It does not execute an activation.

**Gates**: Ruff import sorting and formatting, Ruff lint/format check, strict mypy on new production module, all issue #49 slice tests (Slice 1–39), dependency consistency, staged diff, and exact staged file set. The running test count and skip count are determined by the actual Windows execution, not asserted in this document.

## Security regression intent

The test module checks: signed current witness acceptance; two-sided byte recheck; stale, forged or replayed journal and receipt inputs; invalid witness key or revision; wrong input types; already-held locks; unreconciled recovery; selected-slot/journal drift while the remote witness is called; previous/candidate byte modification before or during the call; a forced second-pass native audit failure; witness expiry before commit; interrupted/failed atomic journal writes; untouched selection, package directories and classroom workspace; and absence of subprocess/provider launch.

The unit test audits use deliberately constrained test doubles for publisher/pip/native stage verification. They verify **coordination and fail-closed orchestration**, not a production end-to-end integration test with real publisher-signed PDS wheels. The existing earlier slice tests cover the underlying signature/native/pip verification functions separately. Do not certify physical software activation, OS-level interprocess security, external witness independence or teacher launch eligibility from these tests alone.

## Git handoff

Expected commit: `feat(suite): arm witness-gated recoverable intent (#49 slice 39)`.

On success record the actual commit SHA, `pytest` pass/skip totals, and push result. If a gate fails, leave the branch **uncommitted and unpushed** for review; do not bypass checks.
