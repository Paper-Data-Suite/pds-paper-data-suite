# Suite #19 — Slice 19A2: pinned wheel-to-installed-payload audit

**Issue:** [#19](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/19)
**Branch:** `19-teacher-home-returned-paper-workflow`
**Expected parent:** `61f4fada42887de82839118463701f3e6224699b`
**Stage:** Read-only installed artifact qualification diagnostic; **NOT** a dispatcher authorization.

## Decision and ownership

Continue #19A without reopening #49's deprecated signing, service or upgrade
machinery. Reuse the **exact official SHA-256 release identities** already pinned
in `returned_paper_installed_wheels.OFFICIAL_WHEELS` by #18. That existing module
also verifies wheel archive identity/metadata/entry-point structure. A2 adds
one missing piece: comparing those archive members with the *currently installed*
distribution's `RECORD`-enumerated files and on-disk bytes under the active
Python environment root. This is a **diagnostic**, not a source of permission.

### Scope

`audit_installed_paper_payloads(wheelhouse)` is read-only:

1. Takes an explicitly supplied local folder containing the three exact
   published wheel archives for Core **0.6.6**, ScoreForm **0.13.0**, and
   Quillan **0.10.6**. No downloads, `pip install`, Core workspace or scan
   access. The default specs come from #18's original verified digest constants.
2. Delegates release-wheel SHA-256, member/path and producer `entry_points.txt`
   checks to `verify_official_wheel`. It does **not** trust an arbitrary file
   named like an official wheel.
3. Uses `importlib.metadata.distribution` and checks exact active distribution
   name/version; refuses an absent/unreadable `RECORD`, missing wheel members,
   changed installed content, symlinks/reparse points, out-of-venv files,
   unsupported wheel `.data` relocation layouts, editable installs and
   unavailable or altered archives. The `RECORD` member itself is excluded
   from the byte comparison because pip rewrites it at installation. It is
   required for installed file membership, not trusted as a content hash.
4. Returns immutable `InstalledPayloadAuditV1` with exactly the three wheel
   identities and verified file counts, and with
   `producer_dispatch_authorized=False` **always**. Negative evidence raises
   `InstalledPayloadAuditError` without changing installed files.

No producer profile, routing registry, paper decoder, native extension, network
service, scanning or handler is imported/invoked by this audit. It does **not**
verify arbitrary third-party dependencies, every unlisted Python import path,
loader state/bytecode, a simultaneous malicious writer, executable provenance
of native libraries, current Core profile registration, classroom ownership or
teacher consent. A successful audit is **not** a trustworthy running-code
attestation, an approved installed wheel *installation history* receipt, or
permission to substitute a nonempty `qualified_modules` in #18.

### Intended evaluation context

The default audit runs in the **active interpreter**, not against a separately
specified site-packages directory. A test-injected metadata lookup, wheel spec
or environment root is a *synthetic test seam only* and cannot produce dispatch
permission. A healthy installed-site audit requires actual official wheel files
available locally; omission should be reported as **diagnostic evidence missing**
and the teacher workflow stays preview-only.

Known official-wheel digests from #18 (unchanged, not copied into a new trust
catalog):

| Distribution | Version | SHA-256 source |
| --- | --- | --- |
| `pds-core` | 0.6.6 | `returned_paper_installed_wheels.OFFICIAL_WHEELS` |
| `scoreform` | 0.13.0 | Same existing pinned #18 contract |
| `quillan` | 0.10.6 | Same existing pinned #18 contract |

### Qualification and required next work

The scoped Windows runner tests A2's forged/changed-wheel/installed-file and
symlink/foreign-path refusal cases alongside #18 installed-wheel verification
and 19A1's default-deny state, plus Ruff, strict mypy, Python compilation and
staged diff hygiene. After passing, it commits only the **three new files**.
No old Suite release manifest, teacher Home, module launch or #18 dispatch
files are modified.

**A3 prerequisite before teacher-menu execution:** decide and qualify a
*controlled isolated official-wheel installation flow* and action-time checks
for exact runtime, Core registry/profiles, native PDFium/ZXing/Poppler and
installed payload. Record limitations; do **not** convert an A2 audit object
into a reusable authorization token. Until an independently reviewed #19
execution seam exists, `inspect_paper_admission` still returns
`processing_status="preview_only"` and `qualified_modules=frozenset()`.

The first read-only teacher-selection work under #19B may proceed without
waiting for producer runtime admission, but **no Core handler is enabled** by
this slice. Full physical scanner, student-record and all-producer acceptance
remains Suite #27 and producer-owned follow-up work.
