# Issue #49 — Slice 108: privileged Windows provisioning handoff (read-only)

## Purpose

Slice 107 established that the Windows base directories meet the conservative
read-only ACL policy. On the pilot machine, all four PDS-owned directories remain
absent, and the preflight correctly returned `2` without writes.

Slice 108 adds a deterministic **human/administrator handoff**, not a provisioning
operation. Run `python -m paper_data_suite.evergreen_windows_provisioning_contract`
to see the exact four required directories, observed/missing paths, and explicit
non-authority fields. It reuses the existing Slice 106–107 ACL inspector rather
than silently loosening its checks. The teacher process does not create any
paths, service accounts, services, shortcuts, receipt heads, or ACL entries.

## Directory requirements

| Proposed path | Role | Ownership/write requirement |
| --- | --- | --- |
| `%ProgramFiles%\Paper Data Suite` | Application binaries | Privileged owner; no ordinary-user write |
| `%ProgramData%\Paper Data Suite` | Protected state root | Privileged owner; no ordinary-user write |
| `%ProgramData%\Paper Data Suite\active-receipts` | Receipt custody | Privileged owner; no ordinary-user write |
| `%ProgramData%\Paper Data Suite\service-state` | Durable service transaction state | Privileged owner; no ordinary-user write |

Privileged owner SID candidates come from the previously qualified strict
custody policy (SYSTEM, BUILTIN\\Administrators, TrustedInstaller). This is a
**checklist**, not a generated ACL/security descriptor: actual directory ACLs,
inheritance, effective tokens, installer/service identity, and file-level
custody must be independently established and verified before production use.
The `ProgramData` **parent** retains its distinct Slice 107 read-only policy;
none of its ordinary-user creation/attribute allowances are permitted for
PDS-owned children.

## Required independent administrative decisions (not implemented here)

1. Define the separately administered, authenticated installer and service
   identity; do not derive elevated authority from teacher CLI flags, package
   metadata, an ACL observation, or a locally writable record.
2. Bind canonical installation roots to independently established OS state.
   Environment variables in this diagnostic are not privileged evidence.
3. Define explicit protected owners, inheritance, effective permissions,
   file-level executable/receipt custody and any scoped service access.
4. Establish the service executable identity, lifecycle, crash recovery,
   durable active-head updates, CAS/witness and approved update transactions.
   Keep independently protected service state outside the Core classroom workspace.
5. Add separate installed-machine acceptance proving a non-administrator
   teacher cannot alter the protected executable bytes, active head or service
   ledger, and that a service identity has not been spoofed.

## Exit statuses and safety boundary

- **2:** PDS-owned directories are missing; provisioning required, *not approved*.
- **0:** all named directory ACLs observed; still **no** production authority.
- **1:** path/ACL inspection refuses or is unavailable; do not proceed.

All successful output retains `production_authority=false`,
`active_receipt_authority=false`, `service_identity=...NOT_ESTABLISHED`,
`executable_integrity=NOT_VERIFIED`, `protected_receipt_head=NOT_VERIFIED`, and
`NO_INSTALL_SERVICE_RECEIPT_ACTIVATION_OR_LAUNCH_AUTHORITY`.

This slice has **no write path** and is independent of Core #238–244, Suite
#51–54, and ordinary module/teacher-home workflows. It does not edit the
historical Suite v0.1.0 manifest or the teacher-managed workspace.

Qualification: targeted Ruff checks, strict mypy, Slice 106–108 tests, pip
check, followed by read-only Windows inspection. No claims of physical service
provisioning or end-to-end production installation acceptance.
