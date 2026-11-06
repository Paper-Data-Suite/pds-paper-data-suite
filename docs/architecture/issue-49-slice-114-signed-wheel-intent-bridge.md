# Suite #49 — Slice 114: signed wheel bytes to installer intent (no admission)

## Why

Slice 112 introduced canonical but **untrusted** installer requests; Slice 113
aligned ScoreForm/Quillan with their real PyPI distribution identities. A
request's digest fields alone cannot authenticate the actual wheel to be
installed. This slice requires the exact requested wheel identities to agree
with the existing signed-release wheel verifier, which independently checks
registry/module Ed25519 signatures, release policy, wheel bytes, metadata and
entry points **against a supplied keyring**.

## Bounded bridge

`review_installer_signed_wheels(raw_intent, candidates=...,
registry_envelope=..., trust=..., now=...)`:

1. Reparse exact canonical v1 intent bytes. Match one ordered candidate for
   each requested distribution. No aliases (`pds-quillan`/`pds-scoreform`),
   missing/extraneous candidates, duplicate wheel locations or duplicate
   signed component identities are tolerated.
2. Invoke `verify_signed_release_wheel` separately for **every** candidate,
   passing the same registry envelope and keyring; the verifier checks signed
   current registry, delegated module metadata and actual wheel bytes.
3. Match the returned signed wheel distribution, version, SHA-256 and verified
   registry *payload* digest to the untrusted intent. A mismatch fails closed.
4. Report only matched distribution/digest summaries, never wheel paths,
   signed-envelope bytes, account names, or a privileged approval token.

The `catalog_sha256` field in v1 installer intent is interpreted as the
**signed registry payload digest**, not the raw JSON-envelope file digest.
This is a schema-semantic clarification, not permission to trust the claim.

## Mandatory security boundaries still outside this module

The caller can construct its own `TrustedKeyring`. This module neither pins the
root keyring from OS-administered state nor maintains durable anti-rollback
checkpoints. The underlying verifier authenticates signatures against that
keyring but cannot attest who supplied the keyring. A teacher-controlled call
cannot establish real deployment authenticity or grant privileges.

A subsequent independent installer must source the trusted root, monotonic
revocation/revision checkpoints, authenticated actor, explicit consent,
protected canonical paths, recovery basis, transitive dependency closure and
service identity **from independently protected sources**, and reverify there.
No authentication state can be imported from this returned dataclass.

No `--apply` CLI, file installation, SCM operation, elevation, service startup,
receipt update, CAS publication, network access, or classroom-data access is
added. The read-only diagnostic command
`python -m paper_data_suite.evergreen_windows_installer_signed_wheel_bridge`
exits 2 (`INDEPENDENT_SIGNED_WHEEL_EVIDENCE_NOT_SUBMITTED`) because it accepts
no teacher-supplied wheel paths or keyrings.

## Qualification

Target Ruff lint/format, strict mypy, Slices 104–114 tests, `pip check`, guarded
Git commit/push and the no-input Windows diagnostic. This bridge is not the
separately installed/privileged acceptance required for Issue #49 closure.
