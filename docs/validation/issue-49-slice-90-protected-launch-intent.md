# Slice 90 — Windows qualification and safety evidence

Baseline: `70e78b6f349dee7bd833e87c95e5ded40ae86a59`.

Scope: four added files only. The runner must refuse an incorrect checkout,
remote divergence, dirty worktree, existing files, a corrupted ZIP member or
missing `--apply`. No reset, retry, stash, force push or overwrite is allowed.

Validation sequence: Ruff import sorting and formatting; Ruff all-lint;
`mypy --strict` on the production module; isolated Slice 90 pytest; complete
accumulated Issue #49 + CLI pytest; `pip check`. The guarded runner checks
Git scope again and permits an exact-four-file commit/push **only if** every
gate passes.

The isolated test suite exercises the real Slice 78–89 SQLite and signed witness
fixture: fresh protected launch intent, no process dispatch or changed student
files, replay refusal, forged or missing protected readiness/certificate,
unauthorized caller, read-only runtime revocation, changed executable/runtime
identity, reappeared or unknown capsule, altered active successor receipt,
unproven deletion termination, wrong witness pin, sample drift, reader
exception, persisted-row readback after database reopening, SQL status
constraint and corrupt stored row refusal.

Windows environment qualification, actual privileged OS fence effectiveness,
crash durability, and process-launch implementation are separate. There is no
actual process execution or authorization in this slice.

**Status until user runs runner:** Pending installed Windows validation. Local
syntax/integrity/SQLite smoke checks are not a substitute for the complete
Windows qualification.
