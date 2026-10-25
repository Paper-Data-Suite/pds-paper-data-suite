# Issue #49 — Slice 63: explicit witness-selected installation diagnostic

## Purpose and boundary

Connect Slice 62's independently signed witness-head and staged-byte observation to an explicitly invoked `pds modules` command. This is an **online, diagnostic-only** inspection. It is not an active installed-state receipt, does not authorize any execution, and does not participate in ordinary offline `pds modules`, `pds doctor`, or `pds launch`.

`pds modules --catalog-cache CACHE --trust-policy POLICY --trust-sha256 SHA256 --audit-witness-selected CONFIG.json`

All three existing catalog trust inputs must be present. This mode cannot be combined with `--compare-local-metadata` or the three `--audit-staged-*` options. A malformed/incomplete request fails closed with exit code 2; verification failure exits 1 with no legacy fallback. No output is produced until all checks finish.

## Strict diagnostic configuration (schema v1)

The configuration is a single bounded UTF-8 JSON object (maximum 8 KiB) with **exactly** these fields, no duplicates:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1`, not boolean |
| `software_root` | Existing absolute software directory, separate from classroom workspace |
| `classroom_workspace` | Existing absolute classroom directory, never mutated |
| `receipt_file` | Bounded untrusted locally stored receipt bytes |
| `evidence_directory` | Fixed Slice 61 evidence layout: `prepared.json`, `registry-envelope.json`, `lock-envelope.json`, `native-envelope.json`, `modules/` |
| `installation_id` | Exact 32-character lowercase hexadecimal installation ID |
| `witness_id` | Expected independent witness identity |
| `witness_origin` | Provisioned fixed HTTPS DNS origin for the witness |
| `witness_ca_file` | Existing CA certificate PEM path |
| `witness_ca_sha256` | Lowercase SHA-256 pin of the CA bytes |
| `client_certificate_file` | Existing mTLS certificate path |
| `client_private_key_file` | Existing mTLS private key path (never printed) |
| `witness_public_key_file` | 32 raw Ed25519 witness public-key bytes |
| `witness_public_key_sha256` | Lowercase SHA-256 pin of those 32 key bytes |

File paths must be absolute and must not traverse symlinks or Windows reparse points. Evidence inventory is exact and module files must match the independently registered PDS distributions in the prepared manifest. Signed claims are authenticated using an already independently obtained **trust-policy SHA-256**. Local input pins and paths are not self-authenticating; production onboarding must provision and validate them outside the teacher-editable software tree.

## Sequence

1. Validate the configuration schema, software/workspace separation and exact evidence-file layout; reject unsafe paths.
2. Independently digest-check publisher trust policy, then load/reverify the authenticated release cache.
3. Read the prepared candidate, calculate exactly which publisher evidence documents are required and refuse extra/missing modules.
4. Read bounded receipt bytes, witness key and mTLS credential files; compare pinned witness key and CA digests **before network access**.
5. Instantiate existing Slice 35 `ProvisionedHttpsWitnessTransport` (no network until invoked).
6. Invoke Slice 62 `inspect_witness_pinned_selected_staged_bytes`. That coordinator validates selected pointer and receipt, queries independently signed witness head, audits publisher/pip/native bytes, and repeats witness/selection observations.
7. Display only the resulting transient read-only observations, clearly marked as **not launch authority**. No credential values, private paths, or raw student/classroom data are included.

Signed witness *read* operations can consume a nonce on the independent server; this diagnostic is therefore explicitly networked and is **not** a side-effect-free remote request. Locally the operation does not write, launch, or change teacher data.

## Remaining scope

This slice does **not** implement independently protected installed-state durability on the Suite host, a protected activation transaction, receipt finalization, verified executable launch, ordinary offline evergreen launch, update selection, rollback, or qualified teacher UI workflows. Those remain separate Issue #49 acceptance criteria; this mode must never be used as their surrogate.
