# Issue #49 — Slice 123: Native ARM64 Windows runtime qualification

**Purpose:** run the *existing* read-only C++ bootstrap diagnostic on an actual Windows ARM64 GitHub Actions machine, rather than infer runtime behavior from x64-host cross-compilation. Parent commit: `b0574c0ba33b01f0f85596ca7722c2180f1c67c1`.

## Change

The Slice 122 Windows Server 2022 job continues to compile x64 and ARM64 through Visual Studio 2022. Its x64 job also executes the diagnostic and proves that `--apply` is refused. The existing PowerShell script adds an allowlisted `-Generator` parameter, defaulting to Visual Studio 2022, so current callers behave exactly as before. It permits `Visual Studio 18 2026` only through a literal ValidateSet, not a command-line fragment or unbounded custom executable.

A new *independent* native ARM64 job uses `windows-11-vs2026-arm`, the hosted Windows 11 ARM64 image with Visual Studio 2026. It configures `-Architecture ARM64 -Generator 'Visual Studio 18 2026' -RequireRuntime`. `-RequireRuntime` is a hard refusal if actual `OSArchitecture` differs from ARM64; the same script verifies the compiled PE machine is `0xaa64`, invokes the executable twice, requires bounded no-authority diagnostic output, checks the unsupported `--apply` refusal, and returns process exit code zero only on success. The explicit marker `SLICE123_NATIVE_ARM64_RUNTIME_PASSED` appears only after actual ARM64 execution and negative tests. Builds stay in disposable external temp locations and source hygiene remains mandatory.

## What remains unproven

An actual passing GitHub Actions job (not local source tests) is required for native ARM64 execution acceptance. This binary is **not signed**, **not a service**, and has no administrator, publisher, installation, receipt, activation or protected-write authority. In particular, it neither provisions a **protected installation** nor supplies independent **antirollback** witnesses; read-only Win32 handle inspection alone is not durable custody. Native x64/ARM64 CI is not a substitute for ordinary teacher-token negative acceptance on a production-shaped installation, release signing, secure SCM registration, protected checkpoint CAS/recovery, or end-to-end installed-wheel qualification.

## Recovery and security

A failed native ARM64 job must block this slice's ARM64 runtime acceptance. No automated retry, alternate architecture emulation, disabling the runtime requirement, unsigned binary acceptance, or installation occurs. The existing static source-contract and cumulative pytest gates qualify only the checked-in workflow and parameters, not actual hosted hardware behavior.
