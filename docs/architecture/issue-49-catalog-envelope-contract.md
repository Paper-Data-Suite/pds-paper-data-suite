# Issue #49: Signed catalog envelope v1 (Slice 2 contract)

**Status:** Parser and schema defined; signature verification **NOT IMPLEMENTED**.
**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

## Separation of authority

This additive schema is **not** a drop-in replacement for the immutable Suite
v0.1.0 exact manifest. Its output is syntactically valid **unverified claims**.
No launcher, `pds doctor`, update routine, or cached receipt consumes it yet.
In particular, a correctly structured Ed25519 signature field is **not** proof
that a signature is correct, trusted, delegated, current, or unrevoked.

The next implementation boundary must verify real Ed25519 signatures using an
audited library, independently pinned trust roots, module-specific delegations,
replay/rollback protection, expiration, revocations and local root rotation.
Only **after** that security adapter and installed-wheel provenance are working
may any release be projected into an evergreen launch policy observation.

## Wire envelope

The wire format is one UTF-8 JSON object with these exact keys:

```json
{
  "envelope_version": 1,
  "payload_b64": "<canonical base64 of exact signed JSON bytes>",
  "signatures": [
    {
      "key_id": "quillan-primary-2026",
      "algorithm": "ed25519",
      "signature_b64": "<base64 encoding of 64 signature bytes>"
    }
  ]
}
```

`payload_b64` preserves the **exact bytes** the publisher signs, not a JSON
object that another parser will reserialize differently. The future verifier
will verify those unmodified bytes; it must not normalize or reconstruct them.
Any canonicalization convention for release producers can be specified for
reproducible publication, but a consumer must not silently change signed bytes.

Limits: 192 KiB total envelope, 128 KiB decoded payload, 8 signatures, unique
key IDs, strict canonical base64, no duplicate JSON keys or unknown fields.
The parser accepts shape-correct synthetic 64-byte signatures intentionally;
**it never evaluates signature validity**. Embedded `kind`, `schema_version`,
and role-specific fields are included in the exact signed payload bytes.

## Three signed-payload kinds

Every payload includes `kind`, `schema_version=1`, positive monotonic `revision`,
and `issued_at` / `expires_at` in explicit UTC `YYYY-MM-DDTHH:MM:SSZ` format.
Parser rejects expiration before or equal to issuance. Runtime time validity is
**not evaluated by the parser**.

### `registry`

An eventual trusted-root-approved registry declares specific `component_id`,
`repository`, `distribution`, and delegated `signing_key_ids` for each known
Suite module. It separately delegates `integration_signing_key_ids`. Identical
normalized package names and duplicate component identities are rejected.
Merely belonging to the PDS GitHub organization does not authorize a module.

### `module_release`

Module-specific release metadata binds component ID, repository, distribution,
and at most 64 stable release claims: version, matching `v{version}` tag, exact
wheel filename, SHA-256 digest, `Requires-Python`, `Requires-Dist` strings,
console entry-point name/target, and explicit `revoked` boolean. Any
`requires_dist` claims must later be checked against official authenticated
wheel metadata, not trusted merely because parsing succeeded. All wheel and
dependency closure integrity checks belong to later slices.

A release document must be signed by an authorized key delegated **to that
exact registry component**; this delegation check does not exist yet.

### `integration`

A separately delegated integration authority signs exact artifact SHA-256
participants, feature identity, result (`passed` or `failed`), evidence digest,
Python minors and platforms. A qualified integration never implicitly qualifies
all future versions or the entire Suite. Module's standalone launcher remains
independent of this result.

## Security controls in Slice 2

- Strict key sets, schema/kind tags, allowed values, duplicate rejection.
- Bounded object sizes, arrays, key counts, and exact hashes/signature lengths.
- No path traversal in wheel filenames; no arbitrary console code targets.
- Conservative stable release versions (no development/prerelease labels).
- No untrusted module import, filesystem inspection, network, cache mutation,
  package installation, or change to the live Suite launcher.

## Explicit deferred security work

- Actual Ed25519 signature verification and trusted key provisioning.
- Root/delegation rotation, key compromise handling, publisher authorization.
- Monotonic locally protected sequence state and expiration checks.
- Safe mapping from verified catalog + installed receipt to policy preflight.
- Exact official wheel authentication and transitive package trust.
- Signed metadata publication automation and actual update/check commands.

Do not expose these parsed models as a production trust API before completing
those deferred steps. Unsigned/parser-only contents must never unlock a launch.
