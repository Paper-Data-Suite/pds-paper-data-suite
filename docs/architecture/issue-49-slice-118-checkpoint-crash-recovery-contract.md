# Issue #49 — Slice 118: checkpoint CAS crash/recovery classification

**Scope:** strict, pure checkpoint intent journal and read-only interruption classifier. **Not:** a Windows service, privileged recovery executor, durable journal, startup repair, receipt, approval, launch permission or anti-rollback witness. Exact parent: Slice 117 (`ca43ead2bf1045f8a2ff16c9818885e075b1ca2a`).

## Why this slice exists

Slice 117 created a deterministic *proposed* new-install checkpoint CAS transition and documented the independently privileged installer. A process can crash after writing an intent journal, before replacing the checkpoint, after replacement, or before committing proof. Those stages must not be conflated. A local JSON journal is not an administrator credential and does not prove whether an NTFS replace was durable. Slice 118 therefore implements deterministic **classification only**, which a later privileged native component can consult but cannot trust for authorization.

## Canonical schema, supported observations

`prepare_claimed_checkpoint_journal(proposal, claimed_previous_bytes=...)` produces compact, sorted UTF-8 JSON with exactly eight keys: `schema`, `phase`, `transaction_id`, `request_sha256`, `previous_checkpoint_sha256`, `previous_generation`, `proposed_checkpoint_sha256`, `proposed_generation`. This is a **claim**, not an actual journal write. The `phase` is initially `INTENT_PREPARED`. The independent native installer may later record `CHECKPOINT_REPLACED_CLAIMED` **only after OS-level replacement verification**, but neither string is evidence of such a write. Max record size is 4,096 bytes; unknown fields, duplicate keys, noncanonical bytes, all-zero identities, boolean generations, wrong hashes and privilege/approval flags refuse.

`classify_claimed_checkpoint_recovery` checks exact proposal status and all no-authority fields, validates the previous/proposed checkpoint bytes and their SHA-256 values, parses the journal, checks its transaction and hash binding, and recognizes only these combinations:

| Journal phase | Observed current checkpoint | Read-only classification | Native action still required |
| --- | --- | --- | --- |
| `INTENT_PREPARED` | exact *old* bytes | `OLD_CHECKPOINT_REQUIRES_NATIVE_REVALIDATION_BEFORE_CAS` | Reauthenticate state, consent, signed wheels, custody, antirollback witness, then *independently* decide whether to retry |
| `INTENT_PREPARED` | exact *new* bytes | `REPLACEMENT_OBSERVED_JOURNAL_NOT_FINALIZED` | Reconcile durable replace, journal, receipt, live installed bytes and protected high-water mark |
| `CHECKPOINT_REPLACED_CLAIMED` | exact *new* bytes | `REPLACEMENT_CLAIMED_REQUIRES_NATIVE_COMMIT_ATTESTATION` | Independently verify post-install state and journal/ledger commit before receipt/activation |
| `CHECKPOINT_REPLACED_CLAIMED` | exact *old* bytes | REFUSE | Contradictory claimed phase; no implicit rollback/retry |
| Any phase | unrelated checkpoint / corrupt bytes | REFUSE | Security incident / independently supervised recovery |

Every recognized observation returns `False` for `native_custody_verified`, `durable_journal_verified`, `independent_antirollback_verified`, `permitted_to_discard_journal`, `permitted_to_retry_replacement`, `permitted_to_publish_receipt`, and `permitted_to_activate_or_launch`. No string status is an instruction to write, retry, delete, or elevate.

## Required native Windows implementation after this slice

1. **OS-protected acquisition:** independently pinned installer executable and administrator token; protected installation identity, reparse-safe handles, exclusive service transaction lock; deny ordinary-user DACL/SCM modifications.
2. **Write-ahead journal durability:** write a protected `INTENT_PREPARED` record *before* replacement, validate exact previous CAS state under the lock, flush data and required directory metadata, and maintain a separate independently witnessed high-water mark (DACL alone is not antirollback).
3. **Atomic replace and postcondition:** use Windows OS API semantics and volume-specific durability guarantees, verify exact new bytes and service custody; append a protected replacement/commit entry after replace. An unverified `CHECKPOINT_REPLACED_CLAIMED` is not sufficient.
4. **Crash matrix:** simulate process termination at each write/flush/replace/commit/receipt boundary, including power interruption. Reopen by stable OS handles and independently validate previous/current journal and checkpoint. Resolve ambiguity *fail closed* rather than trusting locally supplied claims.
5. **Installed software binding:** rehash exact installed wheel inventory and native launcher/service executable, reconcile signed release and lock metadata, recovery basis and receipt head; enforce negative teacher-token acceptance before activation.
6. **No retroactive genesis:** an existing protected deployment missing its checkpoint must be held for administrative recovery; do not accept user-supplied fabricated genesis bytes.

## Qualification

Synthetic unit tests cover the three recognized crash states; the contradictory `REPLACED+old` case; substituted request/transaction/hash/generation; journal duplicate keys, oversize, noncanonical JSON; forged CAS authority fields; and incompatible third-state checkpoints. The test suite uses **explicit short parameter IDs** throughout to prevent Windows' 32,767-character `PYTEST_CURRENT_TEST` limit from interrupting qualification. The guarded runner invokes Ruff, strict mypy, current cumulative Windows/security/signed-artifact tests, and `pip check`. This slice neither adds a CLI `--apply` mode nor runs any Windows operations beyond those existing independent tests.

**Boundary:** A teacher-controlled process can generate matching proposal/journal/checkpoint bytes, so this classification is never trusted proof of administrator identity, key custody, provenance or durable antirollback.
