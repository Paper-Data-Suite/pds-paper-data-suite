# Suite Issue #49 — Slice 121: independent native Windows bootstrap diagnostic

**Exact parent:** `8b3872e6e451b0983db333a7bccabc409fbe82c8` (qualified Slice 120). **Scope:** standalone native C++17 Win32 *read-only diagnostic source*; not a privileged installer, Windows service, authenticated publisher, rollback witness, receipt or launch gate.

## Why the native boundary matters

Slices 117–118 produced deterministic, caller-controlled checkpoint/CAS/recovery contracts. Slice 119 inspected paths and ACLs, while Slice 120 read checkpoint and journal bytes with held Win32 handles via Python. A Python process still cannot independently attest its own identity or obtain protected state merely because it invokes Win32 APIs. Slice 121 starts a **standalone native program** that can later be reviewed, built, signed, installed, and exercised independently of the teacher Python virtual environment. No signature or installation authority is claimed in this slice.

## Native source and build

- `native/windows/bootstrap/bootstrap_probe.cpp`: Windows-only native Win32 diagnostic, with a single no-argument entry point and no mutation or arbitrary paths. It obtains **ProgramData** through `SHGetKnownFolderPath(FOLDERID_ProgramData)` rather than an environment variable. It opens the fixed ProgramData root, PDS directory, `service-state` directory, and both named record files with `CreateFileW(... OPEN_EXISTING ...)`. `FILE_SHARE_READ` denies simultaneous write/delete opens while held; it does not constitute an OS-wide lock or prove durability. It checks file types, reparse attributes, file link counts, actual owner/DACL through `GetSecurityInfo`, and bounded record sizes. Both record handles and their ancestor handles stay live through both reads and close on every exit.
- `native/windows/bootstrap/CMakeLists.txt`: Windows SDK CMake project (C++17), no external package dependencies; `advapi32`, `shell32`, `ole32`. Non-Windows configuration intentionally fails. Intended toolchain: separately installed Visual Studio Build Tools + Windows SDK for matching x64 or ARM64 host/target.
- The only possible process results are a sanitized read observation or a refusal. The binary never prints raw checkpoint/journal bytes, filesystem paths, student data, or signer secrets. It has **no `--apply`, `--approve`, install, SCM, write, receipt, or activation interface**. Any unexpected argument refuses.

On a Windows build host with the relevant Microsoft C++ build tools and SDK, a **reviewer may separately** run:

```powershell
cmake -S native/windows/bootstrap -B <build-dir> -A ARM64
cmake --build <build-dir> --config Release
```

For x64 use `-A x64`. This slice's Python qualification **does not require** a C++ toolchain and does **not** claim native compilation or execution happened. Never launch a locally compiled unsigned binary as a privileged installer or install this probe as a service. Source review and build provenance are separate required gates.

## Security boundary and limitations

1. **No protected installation:** This standalone source does not call UAC, SCM, service APIs, elevation, `CreateDirectoryW`, write/replace APIs, or any module launcher. No production deployment or certificate/code signature exists yet.
2. **ACL observation is incomplete:** The conservative owner/DACL scan refuses unrecognized ACE types and nonprivileged mutation rights. It is not an effective-token access check, a full conditional-ACE evaluator, a reparse-safe identity proof across all ancestor transitions, or an independently secured antirollback witness. An allow/deny ACL snapshot must never be used to grant installation authority.
3. **Held handles are not durable transactions:** `FILE_SHARE_READ` limits concurrent opens; other privileged processes may still have preexisting writers. This diagnostic does not use protected journaling, `FlushFileBuffers`, volume durability proofs, filesystem replacement or CAS. Record bytes are bounded **but not cryptographically authenticated or schema-validated by this native prototype**.
4. **Native binary not attested:** A future privileged install path needs a pinned and code-signed native executable, independent administrator authentication/consent, protected state provisioned by that identity, service identity and SCM-object DACL, trusted publisher policy, transactional re-verification of signed artifacts, exact installed wheel bytes, independent high-water antirollback state, crash-fault injection, and ordinary teacher-token negative tests.
5. **No classroom mutation:** This diagnostic does not access the Core-selected workspace or classroom files. Build outputs must remain outside the classroom workspace.

## Qualification and next gate

`tests/test_issue49_slice121_native_bootstrap_source.py` checks the exact native build/source contract, no mutation command surface, reparse/hardlink/ACL paths, held file handles, bounded reads, OS-root selection and no-authority diagnostic. These are static source-contract tests, **not native Windows integration tests**. A later acceptance gate must compile the source, verify the resulting native binary's Authenticode provenance, run it under ordinary and administrative identities, and exercise adversarial ACL/reparse/handle races before considering a protected installer implementation.
