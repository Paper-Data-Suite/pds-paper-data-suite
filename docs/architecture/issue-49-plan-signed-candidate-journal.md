# Issue #49 — Slice 70: independently signed plan-to-journal handoff

## Contract

`record_signed_plan_candidate_intent` connects the candidate established in Slices 64–69 to the existing update-intent journal. This is the **first durable handoff after an independently root-signed native executable inventory**; it is deliberately **not** an activation, receipt-write, software execution, or launch operation.

Inputs originate from an independently authenticated catalog, fresh witness-selected stage observation, Slice 68 candidate result, Slice 69 unsigned native evidence request, exact closed and publisher-signed wheelhouse, and externally produced root-quorum native envelope. The caller supplies the independently pinned trust keyring. No private signing keys, code-signing bypass, vendor-specific executable assumptions, arbitrary package sources, or default networking are added.

## Acceptance order

1. Refuse missing exact consent `RECORD_SIGNED_CANDIDATE_VERIFIED_INTENT`, bad paths or types, bad timing, disallowed layout, and invalid optional previous-receipt expectation.
2. Confine the candidate to `software_root/candidate-builds/<32hex transaction>` and require a separate wheelhouse and classroom workspace. Refuse a pre-existing journal; never overwrite transaction history.
3. **Before consulting the unsigned request as authority**, call `verify_signed_staged_native_evidence` on actual installed bytes. Its existing validator requires root quorum, exact transaction, Python/platform, native paths/sha256/sizes, expiration, and externally pinned trust. Root keys are not provisioned by this slice.
4. Extract the verified envelope's exact payload bytes and match the Slice 69 request's exact payload, SHA-256, transaction ID and file count. Parsing is not authentication; signature verification occurs first.
5. Independently regenerate the unsigned request from the current signed plan, prepared record, installed pip inventory and native executable bytes, using the root-authenticated revision and time window. Equality to the original request is required. A caller-created request is never sufficient.
6. Run Slice 67's full, twice-observed, publisher- and native-bound candidate audit, and match all plan/transaction/catalog/lock/native/pip identities.
7. Call existing `begin_verified_update_intent` once. Its internal verification checks the signed native stage again and writes a local `candidate_verified` update intent; it never selects or launches the stage.
8. Read the journal back, require exact stage/wheelhouse locations, SHA-256 identities, previous-receipt expectation, phase and revision. A post-write failure returns an error and preserves the journal for explicit reconciliation.

## Trust and recovery limitations

This journal is a **same-user-writable local recovery hint**, not a protected active-installation receipt or cryptographic transition authorization. It is insufficient to establish a fresh independent witness head or remembered monotonic signing checkpoint. An eventual activation flow must reacquire the independent witness under the actual selection/CAS lock, verify protected prior state and exact candidate bytes, obtain explicit authorization, and provide a recoverable selection transaction. Nothing here automatically changes active pointers or invokes candidate code. A journal that remains after failure is never auto-promoted or overwritten on retry.

The external signer must independently establish provenance for the interpreter and native wrappers and maintain its own trusted revision continuity. It must not sign a user-measured hash merely because Suite supplied the Slice 69 request. Locally hash-matched unsigned payloads do not constitute native provenance.

## Source scope and migration

This is an additive, opt-in library primitive. Existing CLI, normal offline `pds launch`, `pds modules`, `pds doctor`, historical Suite manifest, selected workspace and activation/recovery APIs are unchanged. No teacher-facing activation command is introduced.

This does not complete Issue #49. Next work: authenticated release-publishing/signing operations (outside runtime), protected witness/CAS coordination, explicit teacher-approved activation, restore and post-activation verification; then installed-wheel acceptance and production pilot.
