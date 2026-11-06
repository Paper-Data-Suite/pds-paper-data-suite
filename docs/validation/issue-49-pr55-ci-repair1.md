# Issue #49 — PR #55 CI Repair 1

Baseline: `82fbe3165f5b3b52098adcb5e35c6d526e21f4bf`.

## Root causes verified from GitHub Actions logs

- On the Linux Python 3.11/3.13 matrix, pip emits a console-script body using
  `sys.argv[0].removesuffix('.exe')` with no `re` import. The historical
  verifier recognizes this exact modern distlib template only when inspecting
  Windows. The rejection cascades across publisher, signed-stage, journal,
  provider, routing and publication tests. This repair admits **only** the
  existing exact distlib AST on POSIX too, not arbitrary Python statements.
  The separate signed wheel, ownership, RECORD, layout and provenance checks
  are unchanged. Regression tests prove wrong targets and extra code still fail.
- Combined installed-suite acceptance expects the existing phrases
  `Core ... public contract is available.`; the new operational doctor
  emitted `public interface` instead. This repair restores the established
  wording, without skipping public callable inspection or weakening failure
  status.

## Qualification

The guarded runner tests existing staged-runtime negatives, real pip-stage
scenarios from Slices 23–31, operational doctor and new regression tests;
then Ruff and strict mypy. It does not install wheels, mutate student data, or
modify the historical compatibility manifest. It commits and pushes only if
all targeted checks pass. CI must then rerun on the PR.

## Other CI failures

The Windows bootstrap job failed to download external release tooling with
HTTP 504. This is not explained by the two code defects above. Reassess after
new PR CI; if repeated, add narrowly scoped download retries while retaining
unchanged checksum authentication. Do not suppress checksum failures.
