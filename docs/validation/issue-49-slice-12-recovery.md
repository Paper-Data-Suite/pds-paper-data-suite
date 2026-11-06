# Issue #49 Slice 12 validation — reversible candidate selection

Branch: `49-evergreen-launch-and-supported-composition-upgrades`
Base commit: `9bf4c59` (runner checks full SHA)

Run `python -m ruff check`, `python -m ruff format --check`,
`python -m mypy --strict` on the new runtime module, and focused pytest for
all issue #49 slices 1–12, followed by `python -m pip check`.

Local synthetic-fixture run: **358 passed** across Slices 1–12. Windows may
skip tests that require unprivileged symlink creation.

Slice 12 regression coverage includes:

- only signed/journaled activation intent can select a candidate;
- exact evidence bytes and staged native hashes are reverified;
- the previous physical slot must still exist;
- an expected previous **authenticated** receipt cannot be satisfied by a
  locally editable pointer;
- pending recovery blocks all normal selection reads and subsequent switches;
- atomic write interruption preserves a preimage and permits explicit recovery;
- an already-restored preimage can be reconciled again after interruption;
- foreign or malformed markers refuse automatic destructive recovery;
- old and candidate software directories remain untouched by pointer switches;
- unexpected software/classroom workspace overlap and competing writer locks
  fail closed.

This is an isolated non-executing recovery primitive. It creates no managed
active-install receipt and does not change production `pds launch` behavior.
