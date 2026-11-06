# Issue #49 — Slice 99 validation

The isolated tests require a generated encrypted root key and delegated key, sign exact registry bytes, and pass the generated envelope to the existing `verify_registry_document` implementation with independently supplied public-key trust. Negative coverage includes encrypted-key password mismatch, invalid key IDs, short password, duplicate JSON fields, malformed JSON and unsupported document kind.

Windows acceptance: Ruff imports/format/lint, `mypy --strict`, focused tests, all `test_issue49_*` and `test_cli.py`, and `pip check`. The guarded runner must pin clean parent `08c40e10387350df93715bb3f7544b013db97bd4`, exact origin/branch, five additive source files, and verify commit/push only after every gate passes. This slice makes no claim that production root key provisioning, signature issuance, or installed-wheel launch acceptance has already happened.
