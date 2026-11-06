# Suite #49 — Slice 112: canonical, untrusted installer intent

## Pilot baseline

The Windows pilot ran Slices 107–111 read-only and returned exit code 2:
all four PDS-owned protected deployment paths are absent, and the provisional
`PaperDataSuiteService` has no SCM record. Slice 111 enumerated seven ordered
administrative phases, all pending and all unauthorized.

## New boundary

This additive slice provides a **byte-exact versioned installer intent** for
future independent administrative admission. It does not turn the teacher CLI
into an installer. `parse_untrusted_installer_intent()` refuses malformed,
noncanonical, duplicate-key, oversized, or unknown-schema JSON. It accepts
only one operation, fixed provisional service name, exact 32-hex transaction
ID, exact SHA-256 claims for catalog/recovery/artifacts, ordered known PDS
distribution identities, three-component stable versions, and **all seven**
Slice-111 phases. A new installation requires explicit Core and Suite intents.

No paths, account names, shell commands, extra package indexes, executable
filenames, caller-supplied signer IDs, consent flags, or admin-approval fields
are permitted. These schema restrictions are a narrow attack-surface bound;
**hashes in the request are untrusted claims**, not verified digests of
signed GitHub Release wheels or authenticated publisher metadata.

`inspect_installer_intent()` may correlate these request bytes with the
non-authorizing Slice-111 review, but always returns
`UNTRUSTED_INSTALLER_INTENT_REVIEW_ONLY`. Its output contains a request-byte
digest, artifact count, phase/SCM observations and **no privileges**.
No local file writing, SCM operation, powershell invocation, network access,
installation, receipt change, CAS operation or launcher is performed.

Diagnostic entrypoint:

```powershell
.\.venv\Scripts\python.exe -m paper_data_suite.evergreen_windows_installer_intent
```

Expected exit code **2**: `INDEPENDENT_INSTALLER_REQUEST_NOT_SUBMITTED`.
The diagnostic exposes the permissible contract only. It deliberately has
no `--apply`, `--approve`, `--manifest-path`, or elevation argument.

## Mandatory later independently administered implementation

A privileged installer/service must independently establish all of the
following **outside this teacher-controlled process** before any mutation:

1. A trusted, pinned installed identity and authenticated elevated actor,
   specific informed consent and a recovery path; none can be inferred from
   caller-provided fields or source checkout state.
2. Exact signed release/catalog provenance, signer delegation, revocation,
   monotonic metadata and **every transitive package artifact** and digest.
   Never accept a request digest as source authority.
3. OS-derived protected installation roots, authenticated service executable
   bytes, a reviewed dedicated service SID/token and restricted SCM ACL.
4. Durable active head, CAS/witness consistency, interruption reconciliation
   and separate service custody. Package transactions must not touch the
   Core-selected teacher classroom workspace.
5. Physical negative acceptance under a non-administrator account and an
   independently authenticated activation release gate.

The trusted service must **reparse and independently verify** the exact bytes
and all authoritative state. The schema and any result of this module are
locally constructible and must never be accepted as authorization evidence.
The historical v0.1.0 Suite release and existing teacher install stay intact.

## Qualification

Run scoped Ruff lint/format, strict mypy, Slices 104–112 regression, pip check,
then execute the read-only diagnostic on Windows. A passing diagnostic is not
an installed-service test. No Windows privilege boundary is crossed here.
