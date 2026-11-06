# Suite #49 — Slice 122: Windows C++ native build/runtime acceptance gate

**Parent:** Slice 121 `d3c7c837fd8848487e3a17abd0778314628e0da3`.
**Changes:** One standalone PowerShell build/diagnostic script, an additive GitHub Actions Windows build matrix, source-contract tests, and this document. **No source or semantics changes** to the Slice 121 native bootstrap executable.

## Practical acceptance improvement

Slice 121's 19 Python source-contract tests did not build a native executable. This slice adds an executable Win32 C++17 build verification using the Windows 2022 Visual Studio 17/MSVC SDK environment. On a Windows x64 CI runner, compile both x64 and ARM64 targets with explicit CMake generator/architecture, verify the produced PE machine type (`0x8664` and `0xaa64`), and hash exact binary bytes. Run the **x64 runtime** diagnostic and unsupported `--apply` flag negative test. ARM64 is **arm64 compile-only** on this x64 runner, not ARM64 native runtime acceptance.

The build script fails on a missing CMake/VS2022 toolchain, compiler/linker error, unsupported executable architecture, malformed output, unrecognized exit status, or any asserted authority. It never downloads a compiler, initiates UAC, installs the produced executable, registers an SCM service, writes a trust pin, changes ACLs, reads classroom workspaces, or publishes active receipts. The disposable build output is in a uniquely named OS temporary directory outside the source checkout. The script intentionally leaves artifacts for review, not a cleanup step. The Actions job checks repository cleanliness.

## Runtime contract

When executed on a native-architecture host:
- No arguments: return `1` for `NATIVE_WINDOWS_CHECKPOINT_CUSTODY_NOT_ESTABLISHED` or `2` for `NATIVE_WINDOWS_CHECKPOINT_BYTES_OBSERVED_ONLY`. Both are non-authorizing observations; no exit code 0 is allowed.
- `--apply`: must return `2` and `REFUSED_UNSUPPORTED_NATIVE_BOOTSTRAP_ARGUMENT`.
- Every JSON result must have exactly the expected two-line envelope, `native_read_only=true`, and all administrative, service, receipt, protected-write and production-authority booleans `false`, plus the explicit no-authority marker.

This diagnostic may fail on real machines lacking preprovisioned trusted state; that is a valid fail-closed result. It is **not signed**, independently deployed, administrator authenticated, or running as a protected **native service**. The x64 runtime and ARM64 compile-only results must not be promoted into permission to write or activate. An installed teacher account still has **no protected writes** through this program.

## Remaining security and acceptance gates

1. Obtain real CI green for **both** architectures; investigate C++ compilation errors instead of relying on source-contract tests alone. Do not treat a submitted workflow as a successful native build.
2. Run ARM64 runtime diagnostics on a genuine ARM64 Windows host; evaluate x64 emulation separately as applicable.
3. Bind reproducible native binary hash to reviewed provenance and signing. Separately deploy using an independently authenticated administrator/native service outside the teacher-controlled process, and verify DACL/SCM effective rights and negative acceptance under a teacher token.
4. Implement OS-protected independent trust pin and monotonic checkpoint witness; only then implement exclusive, durable journal/CAS transactions and power-failure recovery testing.
5. Continue Issue #49 official-wheel, managed update, launcher, integration and classroom workspace acceptance independently.

**Important qualification distinction:** Local Python unit tests verify only source and workflow contracts. A Windows CI green proves build and limited x64 diagnostic execution, but not production installation, signed provenance, protected receipts or native service privilege separation.
