# Issue #49 — Slice 127: signer certificate and SPKI evidence (observation only)

Parent commit: `1f2b854bbdd222415a43b9cb00a7af931993fba8`.

## Native observable evidence

The existing unsigned `pds_windows_signature_probe` uses `WinVerifyTrust` with offline chain/revocation constraints. For a trusted signature result, it queries the executable's own embedded PKCS#7 signer, looks up the signer certificate using its issuer and serial number, computes SHA-256 over DER-encoded certificate bytes and separately over DER-encoded `SubjectPublicKeyInfo`, and verifies the resulting hexadecimal digests. It closes the certificate, message, store and local-allocated buffer on every path. No extracted certificate or digest is printed or persisted.

Native output gains a boolean `signer_evidence_observed`, which is false for unsigned diagnostic builds, unsupported arguments, and failed extraction. An unavailable signer after a chain result is distinguished by `NATIVE_SIGNATURE_EVIDENCE_UNAVAILABLE`. The observed status remains not authorized. No installation is permitted; no service, trust store, registry, signed receipt or protected checkpoint is modified.

## Claimed publisher pin comparison

A pure standalone C++17 contract accepts a canonical Slice 126 policy *claim* and two signer-evidence digest strings. It checks exact lowercase SHA-256 encoding and strict policy syntax before reporting invalid, mismatch, or `claimed_match_without_authority`. Even a claimed match is **not authorized**, because the policy input may be attacker controlled and is **not independently provisioned**. The executable does not accept caller-selected paths or policies, does not publish digest evidence, and does not treat a Windows-valid chain as an approved publisher.

## Acceptance limits

CMake builds the pure `pds_publisher_pin_evidence_test` with warnings as errors. x64 and native ARM64 CI execute negative tests against claimed matching, mismatch, malformed input, zeros, case changes and noncanonical input. The unsigned native signature binary must still refuse its signature and `--install`, with both `publisher_pin_verified` and `authorized_to_install` false.

The read-only signature observation does not prevent a privileged process from replacing the file between separate WinVerifyTrust and CryptQueryObject calls. This is not a trustworthy authorization boundary. Production requires signed, deployed native code, independently protected and antirollback publisher pin custody, caller-token and service identity checks, handle-bound identity/revalidation, OS-enforced protected checkpoint transactions and recovery, and negative teacher-token acceptance. The current slice is not independently provisioned, not a privileged service, and provides no installation authority.
