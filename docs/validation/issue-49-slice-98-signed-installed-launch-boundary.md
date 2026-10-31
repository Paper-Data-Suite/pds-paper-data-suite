# Issue #49 — Slice 98 validation and handoff

## Baseline and change scope

- Branch: `49-evergreen-launch-and-supported-composition-upgrades`
- Expected clean parent: `817925f2c719c562591e6455e39276ff8e70fabd` (Slice 97)
- Exactly four **new** files: production module, focused tests, architecture and validation documentation. No existing production entry point is modified.

## Qualification

Run Ruff import/format/full lint on production and tests, strict mypy on production, 17 isolated cases, every accumulated `tests/test_issue49_slice*.py` plus `tests/test_cli.py`, and `python -m pip check`. Only after a clean, exact-state validation does the guarded runner stage, commit, push, and independently confirm the remote branch.

## Synthetic tests

Test a signed-release *verifier stub* and a real wheel ZIP plus its installed duplicate in a temporary virtualenv-like directory. This is explicitly not end-to-end cryptographic proof. Previously accumulated tests exercise the Ed25519 verification implementation. Cases include exact byte match, wrong module ID, unregistered module, module code drift, missing module file, wrong interpreter, missing/incompatible dependency, mismatched console target, shared console name, wrong entry-point owner, rejected signature, wrong signed identity, untrusted direct URL dependency, extra-only dependency, corrupted wheel RECORD, and symlinked file.

## Outstanding real-world acceptance

The earlier Windows official-wheel intake verified eight GitHub asset digests and original wheel records but reported `NOT_AUTHENTICATED_NO_INDEPENDENT_SIGNED_METADATA`. The historical installed-wheel lab reproduced Suite 0.1.0 refusing Quillan 0.10.6. Neither supplies a production trust root, protected installed receipt, complete transitive lock, or authorization to execute a new module. Therefore this slice does not claim the teacher-facing issue is fixed; the next slices must implement these production prerequisites and connect the live launcher.
