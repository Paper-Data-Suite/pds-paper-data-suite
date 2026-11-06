# Issue #49 / Slice 71 — Plan-Bound Witnessed Activation-Intent Arming

## Boundary

This slice connects Slice 70's `candidate_verified` plan journal to the existing Slice 39 **witness-gated activation-intent armer**. It does not introduce a second state machine, signing service, witness route, permission mechanism, launcher, or mutable active-selection operation. There is exactly one intended durable mutation: the existing update journal transitions from `candidate_verified` revision 1 to `activation_intent` revision 2. An interrupted or ambiguous armed state **requires explicit recovery**, never automatic promotion.

`arm_plan_bound_witness_activation_intent` requires an exact Slice 65–70 chain (`CatalogSnapshot`, transient witness-selected predecessor observation, installed candidate result, recorded plan-candidate journal reference, all original signed bytes, exact target request) and a **separate** predecessor evidence chain (prior observation, prior module envelopes, active receipt bytes). It refuses any missing or wrong explicit consent token, unexpected path, installed version/lock/pip/native drift, missing or stale journal, previous-head mismatch, and replay.

## Order of operations

1. Validate opt-in intent, bounded source types, host timestamp, trusted-keyring object, witness inputs, and the recorded candidate's identity.
2. Verify that the previous receipt bytes digest agrees with the earlier witnessed receipt hash; this is a *continuity check*, not new remote authentication.
3. Resolve software and classroom roots through existing reparse-aware safety services, ensuring that the transaction-specific stage and wheelhouse remain distinct and within the software root.
4. Require the persisted journal to be `candidate_verified` revision 1 and match all four input-document SHA-256 digests and the **previous-slot observation record** digest.
5. Reauthenticate exact planned wheelhouse, delegated PDS publishers, staged pip files and root-signed native evidence using `inspect_plan_bound_staged_candidate`.
6. Call the **existing** `arm_witness_bound_activation_intent`, which holds selection and journal locks together, reauthenticates the predecessor and candidate physical bytes, checks a fresh signed independent witness head, repeats its audits, and writes only the inert activation-intent journal transition.
7. Read back and reconcile revision, phase, predecessor hash, staged identity, witness revision, and pip inventory. If a post-write check fails, report ambiguity: **do not undo, retry, switch, or mark success**.

The journal field `expected_previous_receipt_sha256` is a legacy name. For this armer, it must contain `sha256(prior.observation_record)`, **not** `sha256(previous_receipt_bytes)`. Slice 70's `previous_receipt_sha256` parameter must have been populated with this observation-record hash. The older selected receipt bytes are validated separately by the independent signed witness at arming time.

## Trust and authorization limits

The caller supplies an independently pinned root trust policy, witness public key, witness identity and service transport. Ordinary Python dataclasses and a locally replaceable journal cannot confer protected, permanent installed state. The existing armer uses **cooperating** locks; hostile same-user writers remain an operating-system deployment concern. The earlier transient witness read may be stale; the locked armer repeats it, and `minimum_witness_revision` prevents regression beneath the Slice 70 observed baseline.

The returned `PlanWitnessActivationIntent` is for reporting **only**. It never authorizes selection switching, witness CAS, new receipt publication, launcher execution, rollback, or classroom workspace writes. Separately authorized forward commit, activation, and uncertain-outcome recovery are required. No new default `pds update` side effects or CLI activation option is added.

## Relationship to existing components

- Slice 67 (`evergreen_plan_staged_candidate`): exact plan-to-installed-byte audit.
- Slice 68–69: isolated install and externally reviewable *unsigned* native request.
- Slice 70 (`evergreen_plan_candidate_intent`): native signature verification and durable `candidate_verified` journal.
- Slice 39 (`evergreen_witness_activation_intent`): existing locked, two-sided, remotely witnessed transition to `activation_intent`.
- Witness CAS fencing and slot recovery remain separate; this slice does not presume their authority or completeness.
