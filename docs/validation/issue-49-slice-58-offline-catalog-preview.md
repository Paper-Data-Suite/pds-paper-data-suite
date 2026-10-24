# Issue #49 — Slice 58 validation gates

New files: `evergreen_catalog_preview.py`, a focused pytest module, these two documents. One existing tracked file, `paper_data_suite/cli.py`, receives four exact anchored edits, all covered by the source-only patch manifest and guarded runner.

Checks required: pinned branch/commit/remote, clean tree, unchanged `cli.py` blob, five explicit staged paths, Ruff import/format/lint, strict mypy on new module and CLI, all `test_issue49_slice*.py`, `pip check`, no residual diff, push only after every gate passes. No automatic retry after a failed validation gate.

Test matrix: default modules behavior; partial CLI option refusal; explicit parsed flags; no legacy fallback on corrupt cache; deterministic module/signed integration presentation; revoked vs nonrevoked versions; missing signer document; malformed digest; naive clock; missing/oversized/reparse files; signed-cache/trust failures; no subprocess/installation or network call; no filesystem mutation. Synthetic `CatalogSnapshot` fixtures test presentation only; they **do not** establish cryptographic acceptance. Existing catalog-cache tests independently test full signed-document verification.

Windows qualification must run from the activated Suite `.venv` on the target branch. This slice is not permission to launch from an authenticated catalog. Require separate OS-managed trust pinning and installed-state/witness/physical-byte acceptance before real evergreen launch selection.
