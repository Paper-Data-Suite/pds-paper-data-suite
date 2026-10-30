# Issue #49 — Slice 96: Read-only installed-wheel evidence inventory

## Scope

Slice 96 starts the **physical installed-wheel acceptance** workstream without introducing another activation claim, changing the teacher's workspace, installing packages, or authorizing module launch. It supplies a stand-alone, read-only Python module:

```powershell
& python -m paper_data_suite.evergreen_installed_wheel_audit
```

The command examines **the current Python interpreter only**, not all PDS installations on a device. It scans an exact registry of eight known PDS distribution names and returns one machine-readable JSON object with a versioned schema. It does not import candidate module code, invoke console scripts, contact GitHub, write any file, run pip, or inspect classroom data. It may read installed distribution metadata and the files named in a local wheel `RECORD` to verify their digests.

## Explicit separation of claims

1. **Installed metadata and wheel tags**: Is the named distribution visible to `importlib.metadata` in this interpreter? What version, wheel tags, and `console_scripts` declarations are present?
2. **Interpreter confinement**: Does the resolved installation root remain inside the current interpreter environment? A wheel installed in another environment cannot be accepted as this interpreter's installation.
3. **Local file drift**: When the installed `RECORD` is bounded and has SHA-256 entries, do the named installed files exist and match their recorded sizes and hashes? Entries with an absent or unsupported digest are not proof.
4. **Duplicate launcher declarations**: Do two inspected PDS distributions declare the same case-insensitive console-script name? This is a warning even if both `RECORD` files match.
5. **Release authentication**: **Never established by this inventory.** The installed `RECORD` is controlled by the local installation and could be replaced together with its referenced files. It is not a signed, independent release provenance source.
6. **Launch and integration eligibility**: **Never established by this inventory.** Exact signed wheel provenance, trusted installation receipt, executable ownership, current dependencies, public API compatibility, and actual supported installed-wheel launch tests are separate gates.

Every result includes:

```text
provenance = UNAUTHENTICATED_LOCAL_EVIDENCE_ONLY
authority = NO_INSTALL_LAUNCH_ACTIVATION_OR_TRUST_AUTHORITY
```

The overall JSON response always reports `acceptance = NOT_ESTABLISHED`. Even a `LOCAL_INVENTORY_ONLY` result is **not** a trust decision or readiness permit.

## Security and boundedness

- Only eight explicitly authorized distribution names are scanned. A package sharing the PDS GitHub organization, such as Clavis, is not implicitly admitted.
- Exact name normalization rejects traversal, newlines, slashes, lengthy names, and duplicate selections.
- Installed `RECORD` is parsed with CSV and bounded by 2 MB and 20,000 records; any individual file exceeds no more than 60 MB, and an audit stops after 400 MB of examined file data.
- Every resolved `RECORD` path must remain inside the current interpreter environment. Absolute or backslash paths are refused; a symlinked final file is never treated as an unchanged installed artifact.
- Only SHA-256 `RECORD` hash entries are verified. The standard `RECORD` self-entry may be unhashed; other unhashed entries trigger review. Missing, malformed, or mismatched metadata remains visible as `REVIEW_REQUIRED`, never repaired.
- The command reports distribution names, versions, wheel tags, console-script names, counts, and bounded finding codes. It deliberately omits filesystem paths, `direct_url.json` URLs, classroom paths, raw package metadata, local usernames, and secrets.

## No production acceptance yet

This slice is an **instrumentation/acceptance prerequisite**, not a production acceptance result. A later audited installed-wheel gate must bind exact bytes of official signed GitHub Release wheels (including transitive artifacts) to independently trusted catalog/receipt evidence, perform isolated real-wheel installation/launch tests on Windows x64/ARM64 as supported, validate `pds doctor` and `pds launch`, and reproduce the original new-Quillan-with-old-Suite refusal scenario without falling back to a source checkout.

The user can run this inventory after qualification and supply its JSON output; that evidence determines the next concrete acceptance matrix. An absent module is reported as absent and never treated as a fatal error of the other modules.
