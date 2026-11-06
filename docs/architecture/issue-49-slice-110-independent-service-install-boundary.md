# Suite #49 — Slice 110: independent Windows installer/service security boundary

## Scope and pilot observation

Slices 107–108 audited the existing Windows Program Files/ProgramData parents,
then reported four missing protected PDS children (`exit 2`). Slice 109
reported `SERVICE_NOT_INSTALLED` for the provisional fixed service name
`PaperDataSuiteService` (`exit 2`). Neither result grants authority.

Slice 110 **reconciles these separate observations** and enumerates proof
obligations for a future independently administered installer and service.
It does **not** implement an installer, register/start a service, create paths,
modify ACLs, sign releases, grant privileges, write receipts, switch installed
packages, or touch teacher workspace/rosters/scans. The teacher process is not
an appropriate source of privileged approval evidence.

## Command and result meanings

Run `python -m paper_data_suite.evergreen_windows_service_install_boundary`
in the existing Suite virtual environment. It calls only the two preceding
read-only diagnostics; unknown or inconsistent observations refuse.

| Exit | Meaning | Authority |
| ---: | --- | --- |
| 2 | Named protected directories and/or provisional service absent | None |
| 0 | Both directory ACLs and SCM service metadata observed; independent security proofs still absent | None |
| 1 | A source query or evidence-validation step refused | None |

All successful results assert `production_authority=false` and
`active_receipt_authority=false`, with service/token, executable, and active
receipt proofs outstanding. The command is an **administrator handoff**, never
an admission token or launch gate. Any forged or local-cached representation
must not be trusted by a future independent service.

## Independently sourced administrative proof obligations

1. **Installer actor and consent:** independently authenticated privileged
   installer identity, physical/administrative authorization, authentic exact
   artifacts and dependency closure; never an elevated `pds` CLI flag.
2. **Canonical protected roots:** OS-anchored installation identity, race-safe
   path handling, deliberate ACLs/inheritance and effective permissions;
   teacher write access to an unrelated ProgramData child is not authority
   over a protected existing PDS child.
3. **SCM object DACL:** inspect *effective* service-object permissions (including
   group membership and denies). Ordinary users must not have dangerous
   control such as `SERVICE_CHANGE_CONFIG`, `DELETE`, `WRITE_DAC`, or
   `WRITE_OWNER`; service start/stop/control rights must follow an explicit
   audited policy. An SCM name or Win32_Service `StartName` is not a security
   proof.
4. **Service SID and token:** independently verify configured service SID type,
   actual running process token/account/privileges, isolation and impersonation
   resistance. A name resembling `NT SERVICE\...` is insufficient.
5. **Executable provenance/custody:** verify signed release artifact identity,
   actual installed executable bytes and file-level rights in a protected root;
   reject reparse-point substitution and writable intermediates.
6. **Protected receipt and witness continuity:** independently administered
   durable active-head state, CAS reservation/quiescence, witness verification,
   recovery after uncertain commit, and protection from teacher writes.
7. **Negative installed-machine acceptance:** prove with separate non-admin
   teacher credentials that binaries/receipts/ledger cannot be replaced,
   the service cannot be reconfigured or impersonated, and no inappropriate
   permission can alter or publish a protected activation.

Windows service-object access rights and service SID types are distinct
facilities, documented by Microsoft:

- https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights
- https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_sid_info

No specific account type, SID mode, service startup policy, installer
packaging, or signed executable is chosen by this slice. Those decisions
require an actual independent administrative implementation and physical
qualification. In particular, a running process cannot self-certify its
own deployment or token solely through teacher-readable metadata.

## Project boundaries

This additive slice introduces only the reconciliation module, focused tests,
and this note. It does not modify the historical Suite v0.1.0 manifest, the
Core-owned classroom workspace, or operational flows under Core #238–244 and
Suite #51–54. The next milestone is real privileged provisioning with
explicit consent, recoverability and non-admin negative acceptance, not another
self-declared approval record.
