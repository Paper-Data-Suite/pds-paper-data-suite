# Issue #49 Slice 51 validation — authenticated consumption, no activation

## Tests

The focused test uses canonical predecessor/successor receipts, a generated Ed25519 service signing key and the Slice-50 signature contract. It exercises:

- Valid challenge-bound signed service statement yielding a **non-authorizing** correlated operator handoff;
- wrong signing key, changed signature, invalid/mismatched challenge, stale or prematurely issued statement, different canonical witness request;
- conflicting local signed-head status, transaction, generation, revision, receipt digest or authority;
- physically requalified successor transaction, generation, revision, receipt digest, stage path, pip/native file hashes, status and authority;
- no caller-provided raw service state, no caller-injected convergence finding, no write/network/subprocess side effects, consistent repeated outputs.

The test uses constructed `ForwardRecoveryObservation` and `ObservedForwardSuccessorBytes` values; it **does not prove** physically signed-wheel provenance, service stop/join topology, independent key custody, current live witness state or safe production activation. Those require separately protected installed/physical acceptance.

## Expected Windows validation

- Ruff import check, Ruff formatting and lint;
- strict mypy of the new production module;
- all `tests/test_issue49_slice*.py` regression modules, including this slice;
- `pip check`, exact four-file staged scope, Git whitespace and remote/head guards;
- no commit or push if any gate fails.

No change to the teacher launcher, classroom files, legacy release manifest, or active receipt is permitted.
