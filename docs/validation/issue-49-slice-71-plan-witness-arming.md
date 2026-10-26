# Issue #49 — Slice 71 Acceptance and Regression

## Intended acceptance

- One explicit and valid request for an existing `candidate_verified` revision-1 journal triggers the existing locked two-sided witness armer, and **only that armer** may transition the journal to `activation_intent` revision 2.
- Prior active receipt SHA-256 must agree with the earlier witnessed observation, while the journal's *previous-slot observation hash* must equal the separately provided `prior.observation_record` digest.
- Exact candidate, signed plan and staged native-pip evidence must be revalidated before the armer is entered. The armer itself revalidates both current installations and queries a fresh signed witness **under locks**; its own tests protect this behavior.
- The returned object indicates inert journal/recovery state, never installation, active receipt, witness CAS, startup or execution authority. No classroom files are touched.
- Any malformed consent, missing prior evidence, stale journal revision, missing or overlapping stage/wheelhouse, changed signed lock/native/pip provenance, witness refusal or postwrite discrepancy refuses safely. Postwrite discrepancies leave the record for explicit reconciliation rather than automatic rollback.

## Tests

`tests/test_issue49_slice71_plan_activation_intent.py` covers the allowed transition; 15 invalid early inputs; five altered candidate-reference fields; six stale/forged journal cases; six stage-observation alterations; original auditor and witness refusal; wrong predecessor receipt; wrong previous observation hash; overlapping paths; postwrite ambiguity; and replay refusal.

The standalone tests use injected observers to exercise ordering and refusal without a real witness. They **do not establish a deployable signed root or a real end-to-end remote witness**. The existing Slice 39 tests are also run by the full Issue #49 regression sweep. Ruff, `mypy --strict`, all `test_issue49_slice*.py` modules and legacy CLI tests, and `pip check` are required before commit.

On Windows ARM64, previous tests skipped due to unavailable unprivileged symlink privileges remain environmental skips. Do not treat them as passing. This slice makes no changes to production activation/selection code, any trust roots, workspace data or launch configuration.
