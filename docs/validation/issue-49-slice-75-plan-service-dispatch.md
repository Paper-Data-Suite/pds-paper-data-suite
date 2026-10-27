# Issue #49 — Slice 75: guarded validation record

## Exact scope

- `paper_data_suite/evergreen_plan_service_dispatch.py`: two explicit service-side operations; one-shot dispatch and independently shutdown-gated signed recovery.
- `tests/test_issue49_slice75_plan_service_dispatch.py`: synthetic signed checkpoint + independent local SQLite fence/gate fixtures; normal dispatch; unsigned/forged refusal; revocation between admission and dispatch; wrong service context/key; once-only replay protection; durable restart; actual successor signed readback; prior signed unresolved crash-window recovery; lost acknowledgment; supervisor denial; signer/outage failure; no classroom workspace changes.
- `docs/architecture/issue-49-plan-service-dispatch.md`: service trust boundary and state machine.
- This record.

## Qualification process

1. Verify exact predecessor Git SHA, branch, origin and remote ref; require a clean tree and only four new paths. Independently verify the source archive's embedded SHA-256 manifest.
2. Write exactly these four additive files, no updates to earlier slices. Run Ruff import/format correction, then read-only import/format/lint gates and strict mypy for the production file.
3. Run Slice 75 tests first, then accumulated Issue #49 tests and existing CLI suite. Run `pip check` before staging.
4. Stage exactly the four additive paths; verify staged add-only list and whitespace; commit and push only if every gate succeeds. No automatic reset, stash, re-run of a failing full suite, or Git force push.

## Local validation versus Windows

The Python sources are syntax checked and archive hashes are checked before distribution. Local lightweight tests, when reported, exercise deterministic test doubles only. **Full Windows installed-repository Ruff, strict mypy, accumulated pytest, dependency consistency and Git qualification remain pending until the user's guarded runner completes.** The existing 21 Windows symlink skips may remain; any new failure requires investigation before commit.

No real independently provisioned witness service, physical installation switchover, classroom migration, local active-receipt publication, end-to-end Windows installed-wheel acceptance, or safe teacher launch is established by this slice alone.
