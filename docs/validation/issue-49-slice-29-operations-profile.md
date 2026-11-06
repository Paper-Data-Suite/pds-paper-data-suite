# Slice 29 validation — Core operations profile probe

Four additive files only; no production launcher, bootstrap, or teacher workspace
changes. Synthetic trust keys and wheels never constitute production signing.

The focused tests cover: exact signed provider-identity binding; positive
validated-profile orchestration without readiness/attention invocation; absence
of optional providers; explicit execution opt-in; bounded timeout; refusal of
unsigned/mismatched identity; failure of provider factory; post-execution drift;
redacted failure; workspace isolation; and a genuine offline pip installation
whose valid signed provider cannot be accepted without installed `pds-core`
contract support.

Windows runner gates: exact branch/HEAD and clean working tree; payload SHA-256;
Ruff import sorting, formatting and lint; strict mypy of the new production
module; focused pytest for all Slice 1–29 tests; `python -m pip check`; exact
staged Git file scope and whitespace; then automatic commit/push only on pass.
Unprivileged Windows symlink tests may skip; their skip must be reported.

No acceptance result authorizes launch, module operations, installation switch,
or rollback. No production-native release signing material is provisioned.
