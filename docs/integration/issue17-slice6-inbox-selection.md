# Suite #17 — Slice 6: bounded, explicitly selected Core inbox inventory

**PR:** [Suite #59](https://github.com/Paper-Data-Suite/pds-paper-data-suite/pull/59)
**Issue:** [Suite #17](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/17)
**Baseline:** `05c0cc0d66bc7ae21c795bb4e96d5e54918d60c1`
**Scope:** Read-only observation/selection. This does not enable Teacher Home processing, custody or dispatch.

## Teacher CLI

List entries in a **deliberately specified, already existing** Core workspace inbox:

```powershell
pds papers inbox --workspace 'C:\PDS\teacher-workspace'
```

The command invokes `pds_core.scan_routes.scans_inbox_dir(workspace)` only to construct `workspace/scans_inbox`. It does not read or change the global workspace selection. The workspace and inbox must already exist; neither is created. The command enumerates up to **64 entries**, including unsafe and unsupported entries, and refuses directories larger than that limit rather than truncating an inventory. Files are sorted deterministically by name, but **names, paths, QR strings and target data are never printed**. Only an opaque one-based entry number, approximate file type, byte size, eligibility and the advisory inventory SHA-256 snapshot are shown.

To preview a deliberate subset, use the exact digest printed by the immediately preceding listing:

```powershell
pds papers inbox --workspace 'C:\PDS\teacher-workspace' --select 2 --select 1 --snapshot '<64 lowercase hex characters>'
```

No file is decoded during listing. Selection without an exact snapshot is rejected. A change to the listing's directory/file metadata invalidates the digest and prevents silently choosing a shifted entry. Duplicate, out-of-range, over-capacity (more than eight), unsafe, oversized or unsupported selected entries are rejected; no fallback to "preview everything" exists. Each eligible selected file is passed, in the requested order, to the already-qualified **read-only** `run_readonly_papers_preview`, which itself refuses links, enforces exact file/byte/page bounds and parses QR candidates through Core. A snapshot is only advisory: an adversary with filesystem write authority can race or reproduce metadata, so this is **not** a cryptographic proof of unchanged contents, an authorization check, or a durable custody handle. Suite #18 must reopen and revalidate sources under independent teacher authority.

## Security/permission boundary

- An explicitly supplied absolute workspace path is required; no implicit `PDS_WORKSPACE_ROOT`, active workspace setting, or current-directory discovery. Paths with `..` traversal are rejected.
- Refuse symlinked ancestors, POSIX symbolic links and Windows reparse-point/junction components for the workspace, inbox and any selected entry. Unavailable, linked, directory and unsupported entries are **not eligible**.
- No source content reads for listing, no provider metadata or factory call, no scores, no Core source retention or dispatch, no domain writes and no scanner dependency install. No workspace mutation or sidecar state is created.
- Up to 64 inventory entries and 8 explicit selected entries, each no larger than the decoder's 24 MiB source bound. Only PDF, PNG, JPEG/JPG suffixes are selectable; the decoder checks magic signatures and actual readability before reporting any page.
- Errors are path-free. Re-run listing when the snapshot changes. Entry numbers have no enduring identity across invocations.
- Empty inboxes are valid and observable. Missing inboxes and directories over the bound fail closed; neither case initiates workspace setup.
- The ordinary `pds papers preview --source FILE` command and zero-argument `pds` Teacher Home behavior are unchanged.

## Verification

Dedicated tests cover deterministic privacy-safe listing, the no-source-open invariant, approved/unsupported/oversized entries, exact-snapshot selection, stale snapshot rejection, link and traversal refusal, 65-item fail-closed behavior, zero writes, CLI parser delegation and preservation of `papers preview` and no-argument home. CI must rerun full Ubuntu/Windows Python 3.11–3.14 matrix, not claim qualification from local tests only. Separate native PDFium/ZXing acceptance in Slice 5 and the unresolved Concord #170 installed-paper conflict remain accurately labeled.

**STOP:** This completes the *optional inbox selection capability* in the read-only #17 preview. It does **not** implement Suite #18 (teacher-authorized retain-first custody/dispatch) or #19 (Teacher Home processing action and producer result review).
