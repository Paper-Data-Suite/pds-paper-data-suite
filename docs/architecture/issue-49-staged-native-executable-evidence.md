# Issue #49 — Slice 10: Root-signed staged native-executable byte evidence

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base commit:** `7918cfa8388edb2e797217c6f9459a4e108c781f`
**State:** Isolated, **read-only diagnostic prerequisite**; no changes to `pds launch`, updates, bootstrap, production trust policy, interpreter or classroom workspace.

## Why Slice 9 is insufficient

A plausible Windows `MZ` header, a console wrapper whose `__main__.py` matches an expected AST, and matching installed metadata do **not** authenticate the executable machine-code prefix, the Python interpreter binary, or an executable's source. An attacker can preserve the wrapper's expected content while changing executable machine code.

`paper_data_suite.evergreen_native_evidence.verify_signed_staged_native_evidence` adds a different evidence type: it compares exact native executable bytes to a **root-signed, stage-specific expected digest inventory**. It repeats the Slice 9 `inspect_staged_virtualenv` and signed lock/prepared-record verification, requires a domain-separated Ed25519 quorum from *independently pinned* root keys, then checks each expected executable file's actual size and SHA-256 against signed values.

## Version 1 signed contract

Envelope: exactly `envelope_version=1`, canonical `payload_b64` and `signatures`. Each signature has `key_id`, `algorithm=ed25519`, `signature_b64`. The root quorum signs the exact message:

```text
b"pds-evergreen-staged-native-evidence-v1\x00" + exact_payload_bytes
```

Signed JSON payload: exactly `record_type=pds_evergreen_staged_native_evidence`, `schema_version=1`, monotonic `revision`, UTC `issued_at`/`expires_at`, `transaction_id`, `registry_payload_sha256`, `lock_payload_sha256`, `trust_fingerprint`, `python_minor`, `platform`, and `files`.

Every `files` entry contains an allowed relative path (`Scripts/<executable>` or `bin/<executable>`), one lowercase `sha256`, and bounded positive `size`. The inventory must include **every** generated console launcher observed by Slice 9 and the staged Python interpreter; on Windows, the optional `pythonw.exe` must be included if present. All unknown, duplicated, case-conflicting, missing or extra signed entries are rejected. The verifier checks ordinary files, symlink/reparse indicators, exact hashes and sizes, freshness, revision continuity, root quorum, and full binding to the currently reverified prepared composition.

No source root keys or signing private keys are included in the implementation. Tests use synthetic deterministic keys that are not deployed to production. An arbitrary JSON file or computed hash cannot self-authorize an executable.

## Explicit limitations — NOT a production activation certificate

This is an intentionally demanding security primitive: **a root signer must have independently established the exact expected native bytes before signing the inventory**. Signing arbitrary on-device stage output would merely launder tampered bytes. Stage-generated Windows console EXEs can depend on virtualenv path/shebang, so publishing one new stage-specific root signature per teacher install is not a scalable production strategy.

Before shipping an operational managed updater, design independently authenticated *reproducible native launcher templates* and interpreter distribution provenance (or an equivalent reviewed installer authority) that does **not** put root private keys on teacher devices or require live signatures for each local stage. A verified digest does not prove underlying executable safety, that a local file will remain unchanged, or that an installation has ever been activated. A replaceable local checkpoint does not provide full anti-rollback resistance. Additional Windows hardlink/ancestor reparse, concurrent mutation and signed-publisher lifecycle controls are still required.

`VerifiedNativeEvidence` has **no** `can_launch` or activation property, cannot create active-installation receipts, and is not wired into the live launcher. Signed catalog freshness alone is not a reason to disable a previously independently verified offline installation. This slice does not run pip, import staged packages, execute subprocesses, create trust state, or read/write student files.

## Remaining implementation sequence

1. Specify independently published reproducible Python/runtime and distlib launcher provenance, and support complete real-pip-generated metadata and executable templates across Windows ARM64/x64.
2. Unify full staged site-file audit, installed metadata audit, executable integrity and dependent-module/Core contract checks for one target composition.
3. Implement protected monotonic installed-state continuity, owned stage directories, atomic activation/rollback with crash recovery, and migration from v0.1.0 state.
4. Connect teacher-approved targeted/composition update planning and offline `pds doctor`/`pds launch`, respecting per-module launch versus per-feature integration qualification.
