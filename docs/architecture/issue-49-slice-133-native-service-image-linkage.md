# Issue #49 — Slice 133: Native read-only service image linkage observation

**Parent:** `77676485c268aaa20f8868702e12e889cc1c1137`.

## Scope and security boundary

Slice 133 adds a separate native C++17 observer for the **provisional service**
`PaperDataSuiteService`. Its sole purpose is to compare the service's configured
image with the actual **running process** image, under the Windows-known
**Program Files** root and the provisional `Paper Data Suite` subdirectory.
The SCM query uses fixed service identity and read-only rights; no caller path,
service name, executable, token or policy bytes are accepted.

The comparison rejects ambiguous unquoted commands, command-line arguments,
relative/UNC/device paths, environment expansion, alternative data streams,
dot segments, doubled separators, unsafe path-prefix matches and differing
process images. The Windows probe checks the live service status and process
ID, queries the process image, and holds the executable through a read-only
Win32 handle. The final component must not be a directory or a reparse
point, and hardlinks are rejected. It compares the normalized final handle
path against both the configured and process-image paths. It does not
print service paths, process identifiers, account identifiers or binary data.

All success is a **read-only, non-authorizing linkage observation**. Even
path agreement is **not authenticated** service identity, **not executable custody**,
not publisher-signature authentication, not durable protected state, and not
independently verified ordinary teacher access. Process identity may race;
ancestor ACLs, every possible reparse route, certificate provenance, active
service token and independently protected receipt state are not proven.
`installed_service_identity_verified` and `executable_custody_verified` are
always `false`. No provisioning, no installation, no protected writes,
no SCM mutation, no receipt publication and no launch permission are possible.

## Windows qualification

CMake builds a pure `pds_service_image_contract_test` executable and
`pds_windows_service_image_probe`, with strict MSVC warnings-as-errors.
The existing Windows gate verifies the compiled probe's PE machine type for
**x64** and **ARM64** and runs both executables only on a matching CPU.
The pure C++ contract exercises canonical image agreement and numerous
confusable-path refusals. The Windows probe must report a valid non-authorizing
status and refuse `--approve`. The existing three CI jobs remain mandatory:
VS2022 x64, ARM64 cross-compilation, and real VS2026 native ARM64 runtime.

On hosted CI the provisional service is absent. Its refusal therefore proves
only that absence cannot be promoted to installation acceptance. A real
ordinary teacher negative-security run must be performed separately against
an independently administered, verified, installed service. An observed
running image is never a production installer approval token.
