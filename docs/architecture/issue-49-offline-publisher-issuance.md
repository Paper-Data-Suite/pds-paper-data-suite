# Issue #49 — Slice 99: Offline publisher issuance

Slice 99 provides the first genuine **non-synthetic Ed25519 issuer** for the already-implemented signed registry/module/dependency catalog verification format. It is a cryptographic issuance primitive, not a production signing ceremony, installer, trust bootstrap, or launch authorization.

- Publisher material is generated using a cryptographically random Ed25519 private key and encrypted PKCS#8 serialization. A public key and SHA-256 fingerprint can be recorded separately.
- The signing function signs **exact** JSON payload bytes and emits the existing `envelope_version: 1` format, so existing verification and delegation rules remain authoritative.
- Issuance rejects malformed JSON, duplicate JSON fields, unrecognized document kind, weak passphrases for generated keys, and unsupported schema versions.
- Caller must separately protect key custody and explicitly approve the signed claim, pin the public root independently, enforce delegated key scopes and monotonic revisions, publish matching signed artifacts, authenticate the full transitive wheel lock, and establish an independently protected active receipt.
- No private keys, synthetic test keys, or operational trust anchors are shipped in the repository.
- A standalone opt-in `python -m paper_data_suite.evergreen_offline_publisher_cli keygen` command generates an encrypted key only at explicit fresh, non-repository paths; `sign` emits a reviewed envelope at a new output path. These commands do not install anything or provision a trusted production signing root. `pds launch` remains unchanged; it still enforces the historical baseline until the external trust and activation boundaries are genuinely provisioned.

The first intended signing ceremony is an independently provisioned root plus delegated Quillan publisher key. Later releases can then be authenticated without a new Suite wheel. Signing an official release must be a deliberate external step; matching GitHub hashes alone does not grant official publisher authority.

Key files and passphrases must be kept on separately secured offline storage with independently reviewed OS access controls; the tool does not establish Windows ACL/hardware custody automatically. Explicitly signed catalog bytes are not trustworthy until a separate trusted root and delegation policy verifies them.
