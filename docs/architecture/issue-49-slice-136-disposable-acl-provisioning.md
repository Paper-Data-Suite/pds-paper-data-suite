# Suite #49 — Slice 136: disposable Windows ACL provisioning prototype

**Exact parent:** `de0022e044d3ab40287f4dd8d91f30f76ade224a`.

## Meaningful new boundary

This is the first intentionally **write-capable** provisioning experiment in the
Suite #49 series, not another read-only observer. It exercises real Windows
filesystem ACL operations in a random, disposable temporary root on an elevated
CI process. It creates five empty directories modeling the proposed application,
state, active-receipt and service-transaction layout, sets non-inheriting DACLs
with only SYSTEM and Builtin Administrators FullControl, and re-reads ACL
metadata. The CI helper independently checks the five directories and rules.

This is not a production installer; no production installation is authorized. This experiment **does not** provision protected production state. It deliberately
uses the current process's `%TEMP%` root, which may itself be controlled by the
user or a parent account. Parent deletion rights, owner trust, identity of the
privileged operator, reparse races in ancestors, authenticated release artifacts,
ordinary-user effective rights, and crash recovery are **not** proved by this
experiment. A correctly observed DACL does not imply durable independent custody.

## Manual-only use (optional, on an isolated administrator-run test VM)

The ordinary teacher's qualification runner DOES NOT call this script. To test
it directly on a disposable Windows VM, a separately authorized administrator
may run:

```powershell
pwsh -NoProfile -File native/windows/bootstrap/sandbox_acl_provisioning.ps1 `
    -ApplySandbox -Acknowledge SANDBOX_ACL_EXPERIMENT_ONLY
```

The command requires a token with enabled Administrators membership and an
explicit acknowledgment. It selects no user-controlled target path, requests
no username, account password, network location, package, arbitrary executable
or service name. It creates only random temporary directories, with no registry,
SCM, Program Files, ProgramData, receipt, publisher-pin or classroom writes.
The sandbox is deliberately retained for independent inspection; no automatic
cleanup, rollback, reset or delete is performed. Do not run it on a teacher
workstation: source qualification and hosted Windows CI are sufficient here.

Exit **1** means missing consent, insufficient token or failed sandbox
experiment. Exit **2** means the disposable ACL experiment completed, **not**
privileged provisioning or installer approval. The output declares all
production-authority, protected-parent and independent-identity flags false.

The new standalone Windows workflow runs only on an ephemeral hosted runner.
It verifies that no-argument invocation refuses and that an explicitly
acknowledged elevated sandbox invocation produces the expected five exact DACLs.
If the runner lacks a suitable token, CI must refuse rather than silently skip.
Native Windows build acceptance remains unchanged.

## Conditions for real production work

Before any production installer writes, independently select and authenticate
an installer/operator identity, sign/pin exact release artifacts, establish
secure OS-anchored paths and parent delete protection, validate service SID/SCM
rights and held executable identity, implement durable publisher pin and CAS
journal/witness custody, and perform negative acceptance as an actual ordinary
teacher account. No authorization consumer exists in this slice.
