# Suite #49 — Slice 134: Native held-service-image owner/DACL observation

**Parent commit:** `c8a8f8487c9ce02b196484f939000ae4d9a79822`.

## Purpose and exact security limit

The Slice 133 read-only probe already reconciles the provisional fixed
`PaperDataSuiteService` SCM executable path with a running process image and
then opens the final executable under the Windows Program Files root.
Slice 134 adds owner and DACL inspection **through that same held handle**.
It obtains file owner and DACL metadata through `GetSecurityInfo` (with
`READ_CONTROL`) and rejects malformed, null, oversized, or unsupported security
descriptors. The allocated descriptor is released by `LocalFree`; the service
and file handles are closed. The program never changes ACLs or service state.

The observation classifies the presence of an allow ACE with write-related
access bits, but an allow ACE may belong to trusted administrators or to an
ordinary user. This is **not effective access** evaluation, is not a proof of
safe inheritance, and is not an authenticated installed-executable custody
verdict. The output only adds `image_owner_sid_observed`,
`image_dacl_observed`, and `image_mutation_allow_ace_observed` booleans.
`executable_custody_verified`, `installed_service_identity_verified`, and
`authorized_to_install` remain false on every path.

## Windows qualification

The existing x64, ARM64 cross-compile, and native Windows 11 ARM64 CI builds
compile the extended C++ probe with warnings treated as errors. Runtime checks
on matching x64 and ARM64 architectures validate the new status fields and
require explicit refusal of `--approve`. A missing provisional service still
produces a fail-closed observation; a hosted CI runner cannot exercise the
positive service-image ACL code without an independently installed test service.

This slice performs **no provisioning**, **no installation**, no protected
write, no ACL change, no service registration or control, and no installed
machine acceptance under an **ordinary teacher** token. An actual separate
administrator must provision and attest a protected service, publisher trust,
file custody, effective teacher access, and rollback-resistant receipts
before production installation may be authorized.
