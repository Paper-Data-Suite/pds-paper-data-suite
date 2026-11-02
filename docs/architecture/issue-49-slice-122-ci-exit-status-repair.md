# Issue #49 — Slice 122 CI exit status repair

**Parent commit:** `b6f66c22091ae7d2284c1b6b191845660f08d6de`. Scope: exactly one-line end-of-script exit status amendment to `qualify_native_bootstrap.ps1`, additive regression test, and this explanatory record.

## Observed Windows CI evidence

On GitHub Actions run `41391023840` at the Slice 122 parent commit, the Windows x64 job successfully configured CMake, compiled the MSVC x64 executable and emitted the `SLICE122_NATIVE_COMPILED_x64`, `SLICE122_NATIVE_READ_ONLY_DIAGNOSTIC`, `SLICE122_NATIVE_APPLY_FLAG_REFUSED`, and `SLICE122_NATIVE_BUILD_AND_RUNTIME_PASSED_x64` success markers. However the build step was marked failed with exit code `1` immediately afterward. The native binary deliberately returns code `2` when the unsupported `--apply` switch is refused. The PowerShell script had no explicit final process exit after checking that expected refusal. This caused the enclosing CI shell to propagate a failure status despite completed assertions.

The narrow correction appends `exit 0` only at the end of successful x64 runtime qualification. All prior CMake, PE architecture, status parsing, negative permission and refusal checks are preserved. An earlier `throw` still aborts with nonzero status. The cross-compiled ARM64 branch remains compile-only; it does not execute the ARM64 binary and never claims native ARM64 runtime acceptance. No executable is installed, signed, elevated, provisioned, registered as a service, or permitted to write checkpoint or receipt state.

## Acceptance boundary

Run new and existing Python source-contract tests and full relevant #49 security regression set locally, then push the clean guarded commit to trigger the workflow at the new HEAD. **A locally passing test does not prove the new Windows job succeeds.** Independently confirm the GitHub Actions x64 and ARM64 conclusions. x64 should now exit `0` *after* all read-only/negative checks; ARM64 should pass its compilation-only gate. Continue to withhold native installation, protected journal/CAS writes, release activation, and teacher launch authority until independently qualified.
