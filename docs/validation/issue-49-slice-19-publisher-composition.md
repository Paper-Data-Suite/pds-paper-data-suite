# Issue #49 — Slice 19 validation

Four additive files; no changes to production `application_launching.py`,
bootstrap, managed installation, CLI command tables, or workspace selection.

Focused synthetic tests exercise:

- An exact root-signed wheelhouse containing signed Quillan and external Core.
- Missing, extra, malformed, and misnamed PDS publisher envelopes.
- Incorrect root/undelegated signatures, mismatched wheel hashes, and revocation.
- Expired publisher release assertions and altered wheel bytes.
- Mismatch between root-signed registry/lock and prepared transaction metadata.
- Unregistered root rejection, independently of root lock authenticity.
- A Quillan-to-Portia transitive dependency requiring BOTH delegated publishers.
- No installation, executable invocation, or file mutation during inspection.

The Linux development focused run completed **498 passed**, with Ruff and
strict mypy reserved for the Windows validation runner. Windows symlink-related
skips from earlier slices may persist when unprivileged symlink creation is
unavailable.

The bundled runner pins exact base commit
`a1aecae544b549763a0897e14091d1bc0be9c4eb`, verifies four SHA-256
payloads, uses a clean-tree guard, sorts/formats new Python files, runs Ruff,
strict mypy, focused issue #49 pytest, and `pip check`. After all gates pass it
stages only the four specified files, checks staged whitespace and unstaged
tracked changes, commits and pushes to the issue branch. A failure is
non-committing; any already-applied files remain for a targeted continuation.
