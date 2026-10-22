# Issue #49 — Slice 44 Windows acceptance and security regression

## Handoff

Apply exactly four additive source/documentation files to `Paper-Data-Suite/pds-paper-data-suite` on branch `49-evergreen-launch-and-supported-composition-upgrades` at exact **Slice-43** baseline `bbf8da1` (full SHA verified by runner). Deliver a **source-only ZIP** and a separate, plain Python 3 script; **no PowerShell script, batch file or executable archive member**.

The runner must refuse wrong origin/branch/local or remote SHA, prior uncommitted work, unexpected source paths, mismatched SHA-256/ZIP contents, or staged changes. Once applied, it must gate a commit and push on Ruff import sorting + formatting + lint/format verification; strict mypy of the new production module; pytest Slice 1–44 test files; `pip check`; exactly four staged changes; and `git diff --cached --check`. No test skips are fabricated: report actual Windows pass and skipped counts. If validation fails, leave four uncommitted, additive files; never push.

Commit title: `feat(suite): fence witness CAS attempts and signed readback (#49 slice 44)`.

## Regression targets

The test module covers guarded reservation before the possible-CAS marker, one-attempt dispatch, real signed Ed25519 head readback and successor classification, a crash before the CAS call, a real durable CAS followed by intentionally lost ACK, denied independent service approval, unavailable network, invalid pinned witness key, wrong service identity, missing reservation, replay or competing successor, SQLite persistence across restart, pre-commit storage failure, corrupt service record, concurrent state mutation during readback and absence of launch/rollback authority.

## Qualification boundary

The tests use independently configured **test doubles** for service authorization and installed-state approval. Real signed witness store and separate SQLite ledger do not establish that the service is genuinely independent, exclusive across every writer, or that the software installation is physically protected. This slice neither enables production `pds launch` nor authorizes rollback or automatic local receipt finalization.
