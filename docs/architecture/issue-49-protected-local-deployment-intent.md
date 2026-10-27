# Issue #49 — Slice 81: protected local receipt deployment intent

## Decision: record the exact *before* state without writing the *after* state

Slice 80 durably recorded the independently witnessed successor's canonical active-receipt bytes in the protected service's SQLite database. **That record is not a local active receipt.** Moving bytes into a separate on-disk installation has a new crash boundary; an SQLite transaction and a Windows file rename cannot be assumed to form one atomic operation.

Slice 81 adds an opt-in service-owned, write-once **local receipt deployment intent** in the same protected SQLite connection as Slices 78–80. Its only stored state is `LOCAL_RECEIPT_DEPLOYMENT_PREPARED_NO_FILE_WRITE`. This records the exact logical successor, Slice 80 receipt metadata, expected **current local predecessor receipt**, an independently pinned destination identity, and the still-pending local proposal, selection, capsule and journal hashes. It does **not** write any active-receipt file, clear a capsule, update a journal, switch a slot, release a fence, run packages, make a witness CAS call, or authorize teacher launch.

The new service table `plan_local_deployment_intent_v1` is keyed by installation and has an immutable status constraint. This is a **write-ahead correlation record**, not a credential. Its SHA-256 bindings detect accidental disagreement between separately controlled observations only; they cannot substitute for operating-system access controls or authenticate a caller-supplied Python dataclass.

## Exact prerequisites and ordering

`ProtectedLocalReceiptDeploymentPlanner.prepare_once` accepts the exact canonical witness request, three *untrusted* reference objects from the Slices 78–80 service, a service context, a service-provisioned pinned target identity digest, two separately provisioned independent readers, and a pinned witness transport/key. All actual protected records are read again from the same SQLite connection **inside** `BEGIN IMMEDIATE`; a fabricated dataclass cannot create missing reservation, preclaim or protected-receipt state. Authorization requires the dedicated `prepare_local_deployment_once` operation.

Before the durable insert, the service must:

1. Parse the bounded canonical witness request and prove the caller's original reservation, preclaim and protected service receipt describe that *same* installation, transaction, receipt hash, generation, witness revision and complete prior record hashes.
2. Reject any existing deployment intent, including byte-identical replays. Revalidate actual service-owned Slice 78–80 rows and the freshly read protected physical evidence, explicitly retaining stopped-writer status, package-byte integrity and operator consent.
3. Call `independently_read_local` under separately enforced OS/process/file custody. It must validate that the **current** local active receipt is the independently witnessed predecessor (not already the successor), the active receipt and recovery capsule are ordinary protected files, the capsule/selection/proposal/journal still match reserved preimages, the target is the service-pinned destination, the selected candidate bytes remain independently audited and every installation writer remains exclusively fenced. A caller-supplied callback with `True` fields does not satisfy this operational requirement.
4. Obtain a new challenge-bound pinned-key **signed successor** witness head with the exact next revision/generation/digest; a prior or divergent head cannot proceed.
5. Commit a single new intent row to the exact service database, then stop. The earlier reservation, preclaim and protected receipt remain intact. Local bytes remain unchanged and the pending recovery capsule stays present.

A lost SQLite COMMIT acknowledgment is uncertain: inspect read-only and reconcile with independent service evidence. **Never automatically re-prepare, reset, compensate, overwrite or delete.** The intent's `observe()` operation validates persisted bounds and hashes but does not establish that any local file was deployed.

## Trust boundaries and follow-on

Real production deployment requires operating-system trust separation; a protected, independently pinned destination; no reparse/symlink traversal; durable service database and filesystem; privilege-separated local snapshots; exclusive writer and process coordination; fresh pinned witness observations; protected operator consent; and meaningful crash/fault injection on Windows. These protections cannot be inferred from synthetic test readers or Python dataclass shape. A standalone SQLite intent **does not** protect a local file against same-user modification.

Next work must provide a separately fenced, privileged file-deployment operation with a durable pre-write `MAY_HAVE_WRITTEN` marker, same-filesystem temporary write/fsync/atomic replacement where supported, post-write hash readback, recovery classification for predecessor/successor/unknown states and a retained capsule until *separate* verified convergence. No active-receipt local writer, capsule cleanup, or launcher readiness is authorized by this slice.
