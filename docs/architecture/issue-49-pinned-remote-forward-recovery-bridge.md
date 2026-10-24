# Issue #49 — Slice 56: bridge one pinned service exchange to fresh forward-recovery inspection

## Decision and boundary

Slice 55 added `ProvisionedRecoveryObservationHttpsClient.fetch()`, and Slice 52 independently rechecks signed witness and candidate installation evidence. The callers of these APIs otherwise have to manually carry `exchange.challenge` and `exchange.signed_envelope` into the Slice-52 read-only orchestrator. Slice 56 adds an **opt-in, network-to-local read-only composition** at `paper_data_suite/evergreen_pinned_remote_recovery.py` to avoid mistakenly treating a forged or mismatched `SignedRecoveryServiceExchange` as verified service truth.

`inspect_pinned_remote_forward_recovery(software_root, classroom_workspace=..., transaction_id=..., request=..., service_client=..., witness_transport=..., pinned_witness_public_key=..., candidate=..., candidate_module_envelopes=..., trust=..., now=..., registry_checkpoint=..., lock_checkpoint=..., native_checkpoint=..., layout=...)` returns **only** `PinnedRemoteRecoveryObservation` with an inert Slice-52 `FreshAttestedRecoveryObservation`, the signed-envelope SHA-256 and explicit non-authorizing status.

The existing signed-transport, local inspector, installed-byte auditor and handoff modules remain unchanged. No executable update path, teacher-facing CLI command, writer admission, CAS dispatch, pointer switch, active-receipt write, rollback or cleanup is added.

## Ordered inspection

1. Before networking, validate typed inputs, a whole-second aware clock, witness pin, exact canonical witness commit request, and transaction identity bound to the successor receipt. Refuse any mismatch.
2. Make **one** request through an explicitly provisioned Slice-55 mTLS HTTPS client. The client generates its own random 32-byte challenge, pins the TLS CA and service signing key, and authenticates the returned Slice-50 Ed25519 statement. It never retries an ambiguous response.
3. Do **not** trust the returned `SignedRecoveryServiceExchange` dataclass, including its `verified` field. Independently check its inert status/authority, reverify the actual envelope against the exact request, challenge and `service_client.pinned_service_public_key`, and require the claimed verified metadata to equal the reverified statement. Reject before local inspection if not identical.
4. Run the existing Slice-52 `inspect_fresh_attested_forward_recovery()` with the reverified envelope/challenge and independent witness transport, publisher keys and signed candidate evidence. That function makes two locked local signed-head observations around another installed-byte requalification with independent witness readback. It refuses predecessor or drift evidence.
5. Correlate the returned envelope hash, authenticated service statement, successor transaction/digest and inert authority with the source exchange. Reject any conflict. Apply a **30-second total monotonic elapsed budget**, encompassing network and local inspections.

This wrapper has no raw `signed_service_envelope`, `challenge`, `convergence`, `requalified` or service-state parameter. Those objects do not become self-authenticating credentials. The returned dataclass can be created by arbitrary Python code and must never be consumed as authority.

## Threat and operational limitations

- An independently pinned TLS certificate, signing key and successful service response authenticate only the signed **statement**. They cannot prove the signer was protected, a genuine service supervisor has stopped and joined all writers, or the service gate cannot be bypassed.
- The client still accepts an externally supplied `now` value. The operator must supply an accurate trusted whole-second clock; the monotonic elapsed budget limits one call but cannot prove service-clock agreement or nonce uniqueness across independent processes.
- Existing local selection/journal locks are cooperating locks. A hostile same-user process can change installed bytes or a selection after the final read. No in-memory or signed observation constitutes an atomic distributed transaction.
- Independent service-wide writer fencing and protected deployment, operator authorization, OS-enforced immutable/controlled installation transition, crash-safe **forward-only** active-receipt reconciliation and real installed-wheel/Windows ARM64 qualification are not present here.
- There is no fallback to unsafe prior-head rollback or an automatic re-fetch after ambiguous failure.
- Classroom workspace paths are passed solely to the existing isolation guard. This code does not open or mutate student/classroom data.

## Scope

Four additive files: this architecture record, validation record, one implementation module and synthetic/real-signed-input regression tests. Existing historical Suite artifacts, previously published contracts and launch behavior remain unchanged. This is **not** production rollout approval.
