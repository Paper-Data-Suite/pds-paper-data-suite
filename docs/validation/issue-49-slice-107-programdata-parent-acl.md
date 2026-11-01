# Issue #49 — Slice 107: ProgramData parent ACE compatibility

## Observation

After Slice 106 qualified, the read-only Windows preflight returned
`REFUSED: ACL custody refused at ProgramData: non-administrator principal
has DACL write authority` (exit 1). The prior Program Files custody check
passed. The ProgramData ACL itself has **not** been captured, so the specific
ACE causing refusal remains unverified.

## Narrow policy correction

Windows commonly permits ordinary users to create unrelated files and child
directories in ProgramData, and to write the **parent directory's own**
extended attributes (`FILE_WRITE_EA`, `0x10`) and attributes
(`FILE_WRITE_ATTRIBUTES`, `0x100`). Neither right, by itself, grants rights
to edit an existing, independently ACL-protected child directory. Slice 106
already permits `FILE_ADD_FILE` (`0x2`) and `FILE_ADD_SUBDIRECTORY` (`0x4`).

The revised ProgramData **parent-only** policy also permits `0x10` and `0x100`.
It continues to refuse untrusted parent ACEs with `DELETE_CHILD`, `DELETE`,
`WRITE_DAC`, `WRITE_OWNER`, `GENERIC_ALL`, or `GENERIC_WRITE`.

The Program Files base, named PDS application directory, named PDS state
root and `active-receipts`/`service-state` subdirectories still use the
unchanged **strict** custody validator: every ordinary-user write permission,
including attributes, refuses. A missing PDS-owned directory must result in
`PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED` (exit 2), never permission to
install, update, issue receipts, or launch.

This change does not inspect Windows access tokens, create directories,
provision an independent service, implement installation receipts, or
establish executable identity. `production_authority=false` and
`active_receipt_authority=false` for all observational outcomes.

## Qualification

Run focused Ruff lint/format, strict mypy, Slice 104–107 regression tests,
`pip check`, then repeat the real read-only Windows preflight. If Windows
still returns exit 1, inspect the actual ProgramData ACE flags rather than
loosening additional policy bits without evidence.
