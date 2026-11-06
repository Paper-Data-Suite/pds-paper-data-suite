# Suite #49 — Slice 140: disposable synthetic payload custody

**Exact parent:** `87b8d58b593147a37c847d0b88a0c1b20beb55a3`.

## Scope

The OS-anchored parent, ordinary account, four directory write denials, eight delete-related denials, and external parent-delete denial have been independently exercised on ephemeral Windows CI machines in Slices 136–139. This slice exercises another installer prerequisite: staging **one synthetic test payload** as a real file rather than checking empty directories. This is not a signed release, authenticated package, or PDS binary.

The elevated hosted Windows CI harness creates the disposable file at `app-binaries\synthetic-suite49-test-payload.bin` under a randomly named CommonApplicationData sandbox, then checks the fixed bytes, SHA-256 and SYSTEM/Administrators-only inherited ACL. Under the existing separate standard-user account, a new native access-handle probe tests three successful positive controls (`FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `DELETE`) on its own file before requesting `FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `WRITE_DAC` and `DELETE` on the protected payload. All four requests must produce `ERROR_ACCESS_DENIED (5)`; unexpected errors or grants cause failure. It never performs a payload write, ACL change, rename or delete. No payload byte changes are requested by the child probe.

The administrator rehashes the staged bytes and compares the file security descriptor after the child process. The result must include an explicit denial of production authority. The workflow remains on an ephemeral GitHub-hosted Windows Server 2022 runner. The normal source qualification runner does not invoke the Windows scripts, create accounts, modify ACLs, or stage files on a teacher workstation. There is no automatic cleanup, rollback, deletion, or service registration; disposable state expires with the runner.

## Unattested boundaries

A SHA-256 of a public test string is **not PDS artifact authentication**. This is not a signed release or protected executable custody. It does not verify an independent publisher, certificate chain, independently provisioned administrative trust, recovery, anti-rollback, an installed service, or production permission. `release_artifact_signature_verified=false`, `protected_executable_custody_verified=false`, and `authorized_to_install=false` are mandatory. The next substantive boundary is independently authenticated **signed release artifact staging** and a recoverable, approved installer, not simply more synthetic observations.

No production path (`ProgramData\Paper Data Suite`) or classroom data is modified. No production installer or launch authority is established.
