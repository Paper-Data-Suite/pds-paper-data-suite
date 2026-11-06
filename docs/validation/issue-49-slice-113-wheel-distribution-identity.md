# Suite #49 — Slice 113: Python distribution identities, not repository names

## Regression detected after Slice 112

The Slice 112 installer-intent allowlist incorrectly included `pds-quillan`
and `pds-scoreform`. These are GitHub repository/project labels, **not** the
`[project].name` Python wheel distributions: Quillan publishes `quillan` and
ScoreForm publishes `scoreform`. All six other allowed distribution names
match their currently declared Python package identities.

The existing `evergreen_installed_wheel_audit.APPROVED_DISTRIBUTIONS` already
uses the correct eight distribution identities. Slice 113 aligns the canonical
untrusted installer intent with that inventory and adds a regression test that
compares the entire sorted allowlist against the established installed-wheel
inventory. The test also covers both valid wheel names and rejection of their
repository-name aliases, plus the all-eight-components request.

## Exact scope

One byte-limited, anchored source edit changes the `_DIST` literal in
`evergreen_windows_installer_intent.py`. One new focused test module and this
validation document are added. No update of historical manifests, installed
wheels, service configuration, protected receipts, or classroom workspaces.

This correction does not approve or authenticate any release: an intent
artifact SHA-256 remains an **untrusted caller claim**, and signed release
metadata, wheel bytes and installation approval must still be independently
verified by a separately administered installer/service. The parser still
refuses unknown distributions, altered schema, arbitrary paths, commands,
consent or approval flags; production and active receipt authority remain false.

## Qualification

Exact parent commit and tracked source blob, clean branch and origin, exact
ZIP manifest and hashes, focused Ruff lint/format, strict mypy, Slice 104–113
regression tests, pip check, narrow staged-byte/scope checks, commit and
normal fast-forward push. Preserve state on any failure; no reset, stash,
rollback, cleanup, automatic retry, or force push.
