# Issue #49 — Slice 69: plan-bound unsigned native evidence request

## Objective

Connect the explicitly consented offline stage from Slice 68 with the existing root-signed native-evidence verification boundary, without manufacturing signing authority or promoting executable files into the active installation.

Slice 68 returns `IsolatedPlanStageResult` after verifying that exact publisher-approved wheels were installed in a new, unselected virtual environment. The existing `verify_signed_staged_native_evidence` verifier requires a different, stronger input: a valid root-quorum Ed25519 envelope binding the candidate's native executable bytes, transaction, registry, dependency lock, platform, and expiry. Previously there was no deterministic, plan-validated payload preparation step between those two interfaces.

## API

`prepare_unsigned_native_evidence_request(snapshot, witnessed, installed, software_root, *, classroom_workspace, wheelhouse, requested_targets, python_minor, platform_tag, registry_envelope, lock_envelope, module_envelopes, trust, now, revision, issued_at, expires_at, layout=None)`

The result is `UnsignedNativeSigningRequest`, carrying canonical `payload` bytes, their SHA-256, exact native-file count, lock identity, and pip-inventory identity. It is **not** a signature, signed envelope, attestation, installed receipt, activation credential, or authorization to execute any candidate code. There is no automatic file write, call to a signer, network call, package install, or update transaction.

## Checks and data lineage

1. Require explicitly passed independently provisioned trust and a witness-selected installation observation from the verification path; the objects are *not* their own trust authorities.
2. Confine the candidate to `software_root/candidate-builds/<transaction_id>`; reject classroom overlap, escaping paths, and wheelhouse/candidate overlap.
3. Recompute the authenticated PDS composition plan and validate the root-signed closed transitive wheelhouse, delegated publisher releases, prepared transaction, and physical pip files using the existing verification modules.
4. Check the exact Slice 68 transaction, baseline witness revision, registry/lock SHA-256 values, and installed pip inventory against the reverified data.
5. Ask `inspect_staged_virtualenv` for its signed-wheel-derived launcher inventory. Include **only** the candidate interpreter, each expected signed launcher, and optional Windows `pythonw.exe` if present. Bound to 64 files, size 1–64 MiB each; reject symlinks, reparse points, collisions, changed file metadata, and unsafe paths through the existing native byte-inspection primitive.
6. Repeat the complete signed-plan, prepared-record, pip, runtime, and native-byte observation and require exact agreement before serializing the payload.
7. Produce deterministic, size-limited canonical JSON using precisely the field names, timestamp representation, and native inventory schema expected by `evergreen_native_evidence`.

The **unsigned** payload has `record_type=pds_evergreen_staged_native_evidence`, schema 1, transaction ID, revision, issued/expiry timestamps, registry/lock/trust digests, Python/platform identities, and relative native paths, SHA-256 and byte sizes. Validity window must include the current UTC time, use whole-second issuance and expiry, and be at most 30 days. This local revision request must not override independently remembered replay history.

## Independently trusted signing authority (not implemented here)

The designated signer must **separately** authenticate that the source interpreter and any generated native stubs are official, approved artifacts and must validate the candidate, platform, trust policy, stage identity, issuance/expiry, and monotonic revision. Merely trusting a teacher-side candidate manifest or signing every locally reported checksum would convert a local code-substitution attack into an apparently valid root attestation. Private keys must remain outside the Suite repository, wheels, and teacher runtime. The existing verifier requires root-threshold Ed25519 signatures over `b"pds-evergreen-staged-native-evidence-v1\x00" + payload` with its supported envelope contract; it must recheck the original stage bytes after the independent signer provides the envelope.

The unsigned request should be transferred using a reviewed, controlled signing workflow—not uploaded to an arbitrary service. It contains no classroom records, student identifiers, credentials, machine-absolute paths, or wheel binaries. It is nonetheless a candidate-specific software integrity document; a separate authority must review it as untrusted input.

## Non-authority and subsequent work

Slice 69 does **not** mint release provenance, publisher signing keys, official Python runtime authenticity, journal entries, active-state receipts, or a switch authorization. Later work must provision an independently managed native attestation signer, accept a valid signed envelope, run the full plan-bound Slice 67 candidate audit, persist a reversible intent under protected locks, and complete witnessed activation/recovery. Signed native evidence cannot stand alone as proof of protected active software state.
