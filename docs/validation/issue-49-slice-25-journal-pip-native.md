# Issue #49 Slice 25 — Validation

**Base commit:** `52f5233754d536583f4084e1dc1a1a151c064b99`

## Focused acceptance

The new tests produce real offline pip installations of synthetic signed
wheels, then create root-signed native executable evidence and a journal
using the existing official journal API. This validates the composition of
three authentication gates with **no candidate import, launch, or activation**.

Test coverage includes:

- Successful journal-bound real-pip, publisher, and native verification.
- Wrong digest-bound prepared, lock, or native inputs.
- Stale journal revision and wrong transaction ID.
- Missing publisher release signature, tampered installed source, and
  mismatched publisher/native transaction observation.
- Pending recovery, concurrent selection lock, unsafe classroom boundary.
- Changed caller-owned publisher evidence during the audit.
- Preservation of the candidate journal, no residual locks, and no activation.

The isolated new tests passed on the development host. The affected Slices
20–25 regression subset passed locally. The complete local issue #49 suite
was attempted but exceeded its execution limit; **it is not claimed to have
passed**. The guarded Windows runner must finish all 26 slice test files,
Ruff checks, strict mypy, `pip check`, and exact Git scope validation before
creating or pushing the commit. Existing Windows symlink permission skips
are expected and reported, not silently treated as full link coverage.
