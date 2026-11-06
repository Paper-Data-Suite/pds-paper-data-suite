# Issue #49 — Slice 17: Explicit isolated candidate runtime smoke

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `f75acbb` (runner verifies full commit identity)
**Status:** Additive, opt-in runtime probe; no live launcher or activation wiring.

## Purpose and contract

`evergreen_candidate_acceptance.accept_verified_candidate_runtime` adds an explicitly invoked operational smoke check for an already authenticated, staged Python environment. Earlier metadata inspectors established source-wheel hashes, installed metadata, launcher structure, and signed native executable digests; those checks **did not** establish whether the staged interpreter starts or whether the installed Python distribution graph passes pip's dependency checker.

This slice does **not** install packages, approve package sources, acquire release-signing authority, activate a candidate, publish a trusted receipt, or qualify mixed PDS producer/consumer contracts. Its result is named `ObservedCandidateAcceptance` and has no `can_launch` property. This observation alone is not sufficient for production update success or `pds launch` eligibility.

## Required preconditions

- An existing journal for the exact requested transaction in revision **1**, `candidate_verified`. It is not a way to recover or re-arm an `activation_intent` journal.
- Exact prepared record, registry, signed dependency lock, and signed executable inventory bytes matching the journal hashes.
- Read-only complete signed native-stage verification against the staged wheelhouse, repeated immediately before **and after** subprocess execution.
- A real stage and wheelhouse under a safe software manager root that is disjoint from an explicitly supplied classroom workspace.
- The staged layout must match the executing host (Windows `Scripts/python.exe`, POSIX `bin/python`). The cross-host `layout` test override from read-only inspectors is not accepted for runtime execution.
- Cooperative global candidate-selection and transaction locks. Pending selection recovery prevents execution.
- An explicit caller decision to execute the staged Python interpreter. This action is never invoked by routine doctor, launch, update discovery or metadata refresh.

## Bounded execution

The two foreground checks use the *exact staged interpreter path* (never arbitrary `PATH` execution), in order:

1. `python -I -c <constant identity probe>`: fail if `sys.prefix` does not identify the selected venv, if the interpreter resolves outside its own `Scripts`/`bin`, if the base Python prefix equals the venv prefix, or if isolated/no-user-site mode is absent.
2. `python -I -m pip check`: check the installed interpreter's declared dependency graph without package installation or online index access.

Each has a bounded per-command timeout (default 30 seconds, maximum 60 seconds). `stdin` is disabled; stdout and stderr are discarded rather than persisted or included in error records. The child process inherits only an explicit minimal environment, with `PIP_NO_INDEX`, `PIP_CONFIG_FILE`, no ambient `PYTHONPATH`, and temporary HOME/config/cache/TEMP directories under the software root, not the classroom workspace. Temporary folders are removed after the run. Failed return codes and process launch/timeouts are not accepted.

After execution, the verifier repeats exact installed wheel/native evidence checks. Any failure on either side, or mismatch of those observations, fails closed. Cooperating update writers remain locked during the bounded subprocess interval. The journal revision and candidate selection are **not changed**.

## Explicit security limitations

**This is not a sandbox.** A signed, compromised, or concurrently modified candidate process runs with the ordinary user's OS privileges and could read or modify other accessible files, including classroom data. The restricted working directory and sanitized environment are hygiene controls, not Windows process isolation. Terminating a timed-out parent subprocess does not guarantee termination of descendants. Same-user mutation between checks remains possible, and root/publisher signed native evidence needs a real independent publisher workflow rather than teacher-local self-signing.

No synthetic signed fixture is executed in tests: the subprocess boundary is simulated and its arguments/environment/timeouts are checked. Genuine, independently sourced Python runtimes and real `pip check` behavior on Windows ARM64/x64 still require a dedicated acceptance lane. Existing `pds launch`, bootstrap, doctor, update menus, and classroom workspace remain untouched.

## Next boundary

Provision reproducible approved interpreter and launcher artifacts, run real installed-wheel acceptance and public contract probes, introduce protected monotonic active-receipt continuity, then wire only fully authorized compositions into recoverable activation and teacher-facing update/launch operations. The historical Suite v0.1.0 manifest remains immutable.
