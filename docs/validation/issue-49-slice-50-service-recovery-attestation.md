# Issue #49 — Slice 50 validation

## Scope

Four additive files only: this validation document, one architecture decision, one standalone service-attestation module and one negative-path regression suite. No production activation/CLI edits, witness writes or filesystem mutations.

## Checks

1. Strict package integrity, pinned branch/remote/HEAD `30ecf8f` and clean tree before install.
2. Ruff I sorting, full lint, formatting and strict mypy for the new production module.
3. All `tests/test_issue49_slice*.py` through Slice 50; `pip check`.
4. Signature binds the canonical serialized exact request, service successor/installation identity, witness revision/generation, and independent pinned key.
5. Challenge replay, signer mismatch, tampering, expired or future statements, missing/invalid key and nonce, malformed/noncanonical/duplicate JSON, unknown schema and invalid signers refuse.
6. Pending or predecessor service states, forged service identity, digest/revision drift and invalid authority refuse *before* signing.
7. No launch, rollback, journal mutation, active receipt write, witness CAS, subprocess, networking or classroom workspace accesses.

## Intentionally not demonstrated

Unit tests with synthetic Ed25519 keys do not prove real service isolation, fresh key-provisioning, signer compromise resistance, protected worker shutdown, or freshness against a hostile system clock. This module does not grant rollback/launch/activation authority. A successful Windows test run will not be construed as installed-wheel or physical service acceptance.

## Windows acceptance

Run guarded `apply_slice50.py` with `pds_suite49_slice50_source_only.zip` on the exact completed Slice 49 branch. The runner must stop without committing/pushing on any failed gate, stage exactly four additive files, and show its final pushed SHA on success. The expected baseline regression count is **1197 passed, 14 skipped**, plus Slice 50 tests; the exact final count is determined by Windows.
