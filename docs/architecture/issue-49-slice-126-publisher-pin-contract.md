# Issue #49 Slice 126 — Strict native claimed publisher-pin policy contract

**Parent commit:** `2f3b3342699218af4b56888469415b23e07b197e` (Slice 125). **Scope:** pure C++17 canonical policy parsing and native CI testing; zero privileged Windows operations, signing, certificate enrollment, service registration, or protected-state changes.

## Purpose and limits

Slice 125 provided an actual native `WinVerifyTrust` observation and verified that an unsigned diagnostic is not accepted as trusted. Windows local certificate-chain trust is not an independently approved publisher. This slice specifies the **claimed policy** encoding that a future independently installed native custodian must validate *only after* acquiring a **provisioned trust root** from independently protected state. The parser is **not a provisioned trust root** and **not an authenticated publisher**, an approved installer, or proof that the pins came from any administrator or trusted source. A matching caller-supplied JSON document is never an authorization credential.

The strict canonical UTF-8 JSON record has four keys, sorted lexicographically, with no spaces, duplicate/unknown keys, escapes, trailing text or unexpected types:

`{"certificate_sha256":"<64 lowercase hex>","revision":5,"schema":1,"spki_sha256":"<64 lowercase hex>"}`

The hashes denote proposed SHA-256 digests of the leaf signing certificate's DER and its SubjectPublicKeyInfo DER. Zero digests, malformed/uppercase hex, revisions outside 1..2^53-1, boolean/decimal/negative revisions, and records larger than 512 bytes refuse. This slice does **not** calculate these hashes from an Authenticode signer; that binding requires a protected native custodian and real signed acceptance fixtures. Nor is a signature's Windows trust-chain success alone enough to prove the publisher pin or a suitable key usage.

A pure `review_claimed_transition(previous, candidate)` classifies three cases: invalid; identical revision and both hashes (`identical_claim_only`); or strictly greater revision (`rotation_claim_requires_independent_native_custody`). A lower revision or equivocation at the same revision refuses. Even the higher-revision case is not permission to rotate policy: a native installer must authenticate the existing high-water mark and apply a separately authorized durable rotation protocol. The routine does not take a user-supplied revision or hash as a trusted baseline.

## Native acceptance

`pds_publisher_pin_contract_test` builds as an independent C++17 executable with warnings as errors. The existing `qualify_native_bootstrap.ps1` compiles it for x64/ARM64, then executes and checks the unique success marker on a matching architecture. The Windows Server 2022 ARM64 job is still cross-compile only; the Windows 11 ARM64 VS2026 job executes it natively. CI failure must block acceptance. No binary is published, installed, signed, or elevated by this slice. Build artifacts remain outside the source tree.

## Remaining trust boundary

Future independent native custody must pin code-signing certificate/SPKI identities through a trusted bootstrap process; validate the signed binary and signer chain with appropriate certificate purpose and revocation policy; pin a durable non-user-writable policy revision witness; reject revision rollback; tie publisher identity to protected installation and service executable bytes; and demonstrate negative teacher-token acceptance on production-shaped Windows installations. Until that work passes, **no installation**, protected checkpoint CAS, receipt publication, activation or launch may derive authority from any claimed policy or this parser's result.
