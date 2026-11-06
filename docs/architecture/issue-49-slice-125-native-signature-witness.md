# Issue #49 — Slice 125: Native Authenticode witness, unsigned refusal

Parent: `e43b87f8a699e3580fe76772f81d27cc890b62ef` (Slice 124 native checkpoint record contract, Windows CI green). The slice adds a **separate native read-only WinVerifyTrust witness** rather than expanding the authority of the checkpoint diagnostic.

## Independent compilation and runtime

`pds_windows_signature_probe.exe` determines **its own image path** using `GetModuleFileNameW` and invokes `WinVerifyTrust` with `WINTRUST_ACTION_GENERIC_VERIFY_V2`, disabled UI, chain-revocation evaluation in **offline/cache-only mode**, and a balanced state close. It accepts no user-selected path, trust root, certificate or installation command. Output is bounded two-line JSON/status with `authorized_to_install=false` and `publisher_pin_verified=false`. An observed Windows trust chain is **not an authenticated installer** and never supplies production approval: a publisher pin must be independently provisioned and authenticated by a separately protected native component before the result could participate in installer authorization.

The CI-built diagnostic is **unsigned**. In both the x64 and native ARM64 runtime jobs, the build gate requires `NATIVE_SIGNATURE_NOT_TRUSTED`, exit 1, and zero approval flags. `--install` must fail with `REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT`, exit 2. The existing x64 and ARM64 checkpoint tests remain in place. The 2022-host ARM64 cross-compile job verifies the new PE can compile but does not pretend that it executes there. Build outputs remain outside the checkout; there is **no installation**, signing-key use, service registration, protected-file write, receipt, activation or elevation.

## Important limitations

- The witness is still untrusted user-executable code. Calling WinVerifyTrust on oneself is diagnostic evidence, not a protected root of trust.
- The Windows machine's ordinary certificate trust store is not a publisher pin; Windows-trusted signatures can belong to unrelated publishers. A protected high-water mark, installed program identity and pinned signing material remain absent.
- Offline revocation information may be unavailable; the witness fails closed. Runtime behavior on unsigned CI binaries is required evidence; source-contract tests cannot replace that.
- All native x64 and **native ARM64** CI jobs must pass after merge of this branch commit. Nothing in this slice turns on privileged install or rollback functions.

## Next native trust boundaries

Establish independently provisioned publisher/signing-key pin material and installation identity in protected Windows service/installer custody; verify the candidate executable from a trusted verifier rather than accepting a self-report; then implement an exclusive, durable checkpoint CAS/recovery engine with signed wheel and receipt binding. Ordinary teacher-token negative-security and official-wheel end-to-end acceptance are still mandatory.
