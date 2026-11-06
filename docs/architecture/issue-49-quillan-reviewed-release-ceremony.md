# Issue #49 — Slice 100: Reviewed Quillan 0.10.6 issuance ceremony

This slice adds an **explicit, offline, locally signed release-claim workflow** after the Slice 99 encrypted-key publisher primitive. It does **not** bootstrap production trust or permit launching, installation, switching, receipt mutation, or accepting new dependencies.

## Exact initial artifact

Only `quillan-0.10.6-py3-none-any.whl` is eligible, pinned to SHA-256 `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` (observed GitHub release asset). `prepare` reads the wheel's `METADATA` to populate its `Requires-Python` and ordered `Requires-Dist` values, then produces strict unsigned documents. No module imports or console commands execute. The SHA-256 observation alone does **not** establish an official publisher signing authority.

## Key ceremony prerequisites

Operators explicitly create **three separate** encrypted Ed25519 keys with the existing Slice 99 `evergreen_offline_publisher_cli keygen` command, each with a distinct passphrase, outside every Git checkout and classroom workspace:

- `publisher-root`: signs the initial registry. Its trusted public-key policy must be independently reviewed and pinned before it can become production authority.
- `quillan-publisher`: signs the Quillan release delegated by the registry.
- `suite-integration`: registered for future integration attestations; **not used** to sign the Quillan release.

The `prepare` command consumes only public identities, checks public-key bytes against fingerprints, and creates a **new** review directory containing `trust-policy.json`, `registry-payload.json`, `quillan-payload.json` and `review.json`. The exact payloads, delegated repository, wheel digest, runtime declarations, signed roles and validity window must be reviewed before issuance.

The `issue` command requires an explicit 64-digit trust-policy SHA-256 pin provided separately. It re-derives the claims from the same wheel and public identities; rejects changed payloads and private keys that differ from the reviewed public keys; asks for the root and module signing passwords; signs the exact reviewed payloads; and uses the existing `verify_registry_document` and `verify_signed_release_wheel` to independently check delegation, release metadata and wheel contents. It writes `registry-envelope.json`, `quillan-envelope.json` and `issuance-result.json` only if the re-verification succeeds. It refuses to overwrite any existing output file.

## Authority restrictions

A locally generated root/policy is **not automatically a trusted PDS root**. Project/publisher ownership approval, independent root/policy provisioning, monotonic metadata checkpoint custody, signed transitive dependency lock, protected installed-composition receipt, OS-native executable custody, and launcher authorization remain separate requirements. No code in this slice modifies `pds launch`, reads a classroom workspace, activates staged software, or publishes a signed release over the network. No private key belongs in Git, a release wheel, or a support log. Outputs from `prepare` and `issue` are local evidence; they may be safely discarded without changing installed software.

## CLI

```text
python -m paper_data_suite.evergreen_quillan_issuance prepare \
  --wheel <exact-wheel> --root-public <root-public.json> \
  --quillan-public <quillan-public.json> \
  --integration-public <integration-public.json> \
  --directory <new-review-dir>

python -m paper_data_suite.evergreen_quillan_issuance issue \
  --wheel <exact-wheel> --directory <review-dir> \
  --trust-sha256 <independently-reviewed-policy-SHA256> \
  --root-private <encrypted-root.pem> \
  --quillan-private <encrypted-quillan.pem>
```

No change to the immutable Suite v0.1.0 compatibility manifest is made.
