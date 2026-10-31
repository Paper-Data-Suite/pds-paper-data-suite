# Issue #49 Slice 100 validation contract

- **Scope:** one new Python module, one focused test file, one architecture note and this validation note; additive only.
- **Baseline:** `7da18d3ba2c4b12c66259da371fec33f2c724158` on `49-evergreen-launch-and-supported-composition-upgrades`.
- **Positive tests:** deterministic reviewed policy/registry/module documents, encrypted private keys matching the approved public identities, root/delegated real Ed25519 signatures, and checked exact release identity.
- **Negative tests:** changed trust-policy digest, changed reviewed release, wrong encrypted signer, wrong password, forged public-key fingerprint, private signing key inside Git, role confusion and output overwrite.
- **Windows qualification:** Ruff import sorting/format/lint; strict mypy on new production module; targeted tests; all `tests/test_issue49_*.py` plus `tests/test_cli.py`; `pip check`.
- **Authority:** successful signing is local cryptographic evidence only, not proof of official publisher key authorization, independent trust provisioning, full dependency provenance, active receipt, installed health, integration acceptance or production launch permission.
- **Deployment:** none. The runner may commit and push only if all gates pass; it never changes the classroom workspace, user signing keys, installed modules or activated environment.
