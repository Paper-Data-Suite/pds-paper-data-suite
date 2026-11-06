# Suite #49 — Slice 111: non-executable administrative installation plan

## Verified entry state

The Windows pilot reports:

- `PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED` for four named PDS-owned directories.
- `SERVICE_NOT_INSTALLED` for provisional name `PaperDataSuiteService`.
- Slice 110 `PROTECTED_SERVICE_INSTALLATION_REQUIRED` and seven independent proof obligations.
- No production installation, active receipt, service impersonation or launch authority.

Slice 111 turns those distinct observations into a **fixed, sequential administrative handoff**. It does not implement an installer or grant any user, executable or process a credential. The presence of this plan cannot be used as evidence of privileged consent or complete installation. It is safe to run from a teacher checkout only because it reads previous diagnostics and prints inert JSON.

## Command

`python -m paper_data_suite.evergreen_windows_admin_install_plan`

The module invokes the earlier read-only Windows service-install-boundary review and compiles a strictly ordered seven-phase plan. It accepts no arbitrary executable path, service name, SID, shell command, remote URL, package source, operator assertion or `--apply` flag.

The plan reports *all phases pending*, and each phase has `authorized_for_execution=false`. It is not a scripting DSL and has no dispatch mechanism. Every top-level authority flag remains `false`. It emits only fixed phase names/evidence obligations plus safe categorical status, not raw paths or student records.

## Administrative phases

1. **Administrator authentication/consent.** Independently authenticate the installing actor, verify exact signed artifacts and transitive dependency closure, and approve a recoverable operation. No teacher-supplied approval tokens.
2. **Protected directory provisioning.** Use independently established OS roots, race-safe handles, explicit effective DACLs/owners; ordinary teacher users cannot write protected PDS directories. Do not apply ProgramData parent creation permissions to existing PDS children.
3. **SCM registration/custody.** Define a controlled service identity and startup/lifecycle policy, then verify service-object DACL rights including `SERVICE_CHANGE_CONFIG`, `DELETE`, `WRITE_DAC`, `WRITE_OWNER` and appropriate control rights. Do not infer rights from Win32_Service metadata.
4. **Executable and effective-token attestation.** Verify signed release artifact identity and installed executable bytes; inspect the actual service token/SID, privileges and service isolation, not merely the registered `StartName` or path string.
5. **Protected receipt/CAS initialization.** Initialize a service-owned durable journal, receipt head and independently witnessed CAS continuity with explicit crash and uncertain-commit recovery.
6. **Negative security acceptance.** Verify through separately authenticated nonadministrator credentials that the teacher cannot rewrite binaries or receipt/journal state, reconfigure or replace the service, impersonate its identity, or publish activation.
7. **Independent activation release gate.** Only a separately authenticated installer/service may evaluate accumulated independent proof and authorize an actual release with recovery. This locally displayed plan is never such authority.

## Status/exit meanings

| Exit | Status | Implication |
| --- | --- | --- |
| 2 | `ADMINISTRATIVE_INSTALLATION_PLANNING_REQUIRED` | One or more PDS deployment directories or the named service are absent; administrative deployment required, no action taken |
| 0 | `ADMINISTRATIVE_PROOFS_OUTSTANDING_METADATA_ONLY` | Both broad observations exist; none of the independent proofs is established and no activation is authorized |
| 1 | Refused | Prior observer failed or result was internally inconsistent; no fallback, write, or approval |

All phase outputs are untrusted until independently validated from OS custody, cryptographic release provenance, secure service state and a physically installed machine. Even a manually forged dataclass or JSON plan remains incapable of authorizing a privileged action because there is **no approval consumer** in this module.

## Microsoft guidance / future implementation

- Service object and SCM access rights are distinct; authenticated identities and access checks matter: https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights
- Service SID types (NONE, UNRESTRICTED and RESTRICTED) affect access-token isolation, and configuration changes may require restart: https://learn.microsoft.com/en-us/windows/desktop/api/winsvc/ns-winsvc-service_sid_info
- Secure installation authoring requires authenticated packages, appropriate ACLs and safe failure paths: https://learn.microsoft.com/en-us/windows/win32/msi/guidelines-for-authoring-secure-installations

## Next actual implementation boundary

A future separately administered *installer prototype* should implement one privileged operation at a time **in an isolated test environment**, starting with verifiable signed-package staging and protected directory creation/ACL validation, with explicit administrator consent, rollback/recovery and a nonadministrator negative test. Do not run such an installer on a teacher workstation until the identity, support authority, and recovery plan are approved and tested. Slice 111 does **not** simulate approval or touch the live machine.

Unchanged: historical Suite v0.1.0 manifest, teacher-managed venv, PDS classroom workspace, Core-owned data, all service and receipt files, Windows ACLs, registry, and SCM state.
