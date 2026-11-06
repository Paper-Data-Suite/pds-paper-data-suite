# Suite #49 — Slice 130: Native read-only SCM service-security observation

**Parent:** `168f9aac3652d84af83a043299c0a5fe5fe00b32`.

## Scope

Observe the **provisional** fixed service name `PaperDataSuiteService`, already
used by Suite Slice 109. The new native C++17 executable requests only
`SC_MANAGER_CONNECT`, `READ_CONTROL`, and `SERVICE_QUERY_CONFIG`; it uses
`QueryServiceObjectSecurity` to inspect bounded service-object owner/DACL
metadata and `QueryServiceConfig2W` to inspect the configured service SID type.
All handles are closed on exit. Unrecognized or excessive ACE data and failed
queries refuse. The output does not disclose SIDs, executable paths, principals,
service account names, binary bytes, certificate evidence, or policy contents.

The presence of potentially mutation-capable ACE entries is an observation,
not an effective-access judgment. The ACE loop does not implement Windows
`AccessCheck` over an independent ordinary teacher account's actual token,
inheritance, group membership, privileges or access-deny ordering. Therefore
**service identity is not independently authenticated**, and
`effective_teacher_rights_verified` is always false. A nonzero refusal code
or service-absent code must not be recast as authorization.

## Execution and acceptance

The existing native x64/ARM64 Windows build gate invokes Slice 129's helper,
which now builds the SCM witness using the same CMake configuration. The helper
verifies the PE machine type, allowing ARM64 cross-compilation only without
runtime claims. It then executes both ordinary read-only observation and the
`--install` refusal on x64 or genuine Windows ARM64. CI cannot install a test
service or modify the machine; an absent provisional service is the normal
accepted negative observation on hosted runners. All results deny provisioning,
protected writes, service registration, active receipts and installation.

The three existing Windows jobs must pass: VS2022 x64, VS2022 ARM64 cross-build,
and VS2026 on a real ARM64 Windows runner. Local Python source tests do not
replace native compiler or runtime acceptance.

## Unresolved independent boundary

Actual release signing and vendor identity, an independently administered
service and protected publisher-pin policy, cryptographically authenticated
installer consent, ordinary teacher negative-security tests on the *installed*
service-object, executable custody, service process SID/token, protected
checkpoint CAS/recovery, and rollback-resistant trusted witness remain
outstanding. In particular, **no provisioning**, **no installation**, no service
creation, security-descriptor edit, signing operation, receipt publication or
classroom-file access occurs in Slice 130.

Microsoft references:

- https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights
- https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryserviceobjectsecurity
- https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryserviceconfig2w
