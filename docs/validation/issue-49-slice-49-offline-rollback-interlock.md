# Issue #49 — Slice 49 validation: offline rollback proposal interlock

## Scope

Add a lightweight, non-authorizing proposal-presence interlock and insert it into **both** historic inert-only rollback entry points. Existing code paths are patched by the exact pinned source-only runner; the runner refuses unexpected branch, remote, baseline, old-code anchors or preexisting local changes.

## Required checks

- Ruff import sorting, formatting and lint of both touched production modules, new helper and tests.
- Strict mypy of both touched production modules and new helper.
- The complete Slice 1–49 pytest suite; installed dependency consistency.
- Dedicated tests: nonexistent proposal retains prior inert behavior; malformed proposal, directory, and symlink prohibit old-pointer restore; both old recovery APIs retain exact pointer/capsule/journal contents on refusal; no teacher-data, network or process side effects.
- Exact staged six-file allowlist, whitespace checks, no unstaged tracked diff, guarded commit/push.

## Not qualified

These tests do **not** prove remote CAS absence, service-wide writer isolation, malicious same-user filesystem resistance, signed physical activation, recovery completion or the teacher production launcher. The function only prevents two cooperating local rollback routines from proceeding when a proposal-path entry is present.
