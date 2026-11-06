# Issue #49 — Externally pinned active-receipt continuity (Slice 32)

A verified candidate, an update journal, and a selected local directory **cannot**
establish which installation was historically active. Local files can be replaced.
Slice 32 adds an exact, canonical *receipt claim* and a verifier that requires a
checkpoint obtained from outside the software tree.

## Receipt and independent checkpoint

The bounded v1 receipt contains the selected transaction, generation, stage and
wheelhouse relative paths, hashes of all prepared/registry/lock/native envelopes,
the authenticated native payload and pip inventory hashes, publisher-delegation
digests, the root console identity list, external distributions, UTC timestamp,
and previous-receipt digest.

All receipt fields must be present once, canonical JSON is required, paths and
identifiers are bounded, rows are unique and sorted, and hashes are lowercase
SHA-256. A generation-1 receipt has no predecessor. Every later receipt must
point to the independently pinned previous head and advance exactly once.

`ExternallyPinnedReceiptHead(generation, receipt_sha256)` must be retrieved from
an **independently protected anti-rollback store**. Creating that object using a
hash beside the same receipt, or a locally editable JSON backup, does not add
trust. This code neither provisions a checkpoint nor commits it to an OS store.

## API and boundaries

- `make_untrusted_active_receipt`: canonicalizes an ephemeral journal-bound
  candidate observation into a **draft**; does not sign it or make it trusted.
- `parse_untrusted_active_receipt`: strict syntax and shape check; no IO.
- `verify_externally_pinned_receipt`: compares canonical bytes to an independently
  provided head and verifies parent-head continuity. It cannot authenticate the
  source of an arbitrarily supplied checkpoint.
- `compare_receipt_to_observed_candidate`: compares a pinned claim with fresh
  signed-wheel/pip/native **observation inputs**. Callers must independently
  re-run the real journal/publisher/native verification rather than trusting an
  observation manufactured by the caller.

No filesystem read/write, installation, Core callback, network request,
activation, or executable launch is performed here. A pinned receipt alone
is **not launch authority**, even when its checksum matches. A production
transition still requires OS-protected checkpoint provisioning, atomic durable
activation/rollback and fresh installed-byte checks. Classroom workspaces must
never be used as receipt/key storage.

Threat boundary: hostile same-user processes may still modify the software or
its local receipt; a plain SHA-256 does not prove publisher authority. The
independent checkpoint is one necessary component, not a substitute for the
signed publisher and native verification in earlier slices.
