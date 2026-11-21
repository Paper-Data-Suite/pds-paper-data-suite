# Suite #20 Slice A — Pure Core v1 attention projection

**Scope:** source API, synthetic Core v1 mapping and negative tests only. The
interactive Attention Needed menu, producer evaluation, UI sorting/filtering,
label policy and renderer remain **out of this slice** (#20 B/C, then #21–#23).

## Input / authority boundary

`paper_data_suite.module_attention_projection.project_module_attention` accepts
an **explicitly supplied** `ModuleOperationsMetadataInventory` (#16), optional
`ModuleOperationsProfileInventory` (#16), a Core `ModuleOperationsRequest`, and
already-produced Core `ModuleOperationsInvocationResult` values.

The projection does not inspect entry points, run profile factories, invoke
readiness or attention callbacks, read a workspace, launch a module or persist
results. The caller must establish the authorization of any evaluation before
supplying those results. This API provides **no execution or authorization**.

The six owners are derived from the approved Suite component registry rather
than provider-asserted names; `core` is not an attention-producing owner. A
separate typed `AttentionModuleRow` exists even for unavailable owners. Counts
are taken verbatim from the Core summary: `None` means **not supplied** and
`0` means an owner-supplied zero. The projection does **not** calculate totals
or rank urgency; Core v1 has no generic urgency/severity field.

## State mapping

| Source / result | Projected state | Evaluated? |
| --- | --- | --- |
| Core metadata inspection failed | `metadata_unavailable` | No |
| Approved module has no metadata declaration | `not_declared` | No |
| Metadata identity invalid/ambiguous or wrong owner | `metadata_unqualified` | No |
| Metadata okay but profile not supplied | `profile_not_checked` | No |
| Profile missing, unavailable, invalid or wrong owner | `profile_unqualified` | No |
| Valid profile declares no attention | `capability_absent` | No |
| Valid profile, attention declared, no result | `not_evaluated` | No |
| Core `module_operations.evaluation_unavailable` | `evaluation_unavailable` | No |
| Core `module_operations.provider_failed` | `provider_failed` | No |
| Core invalid result/contradiction/duplicate/foreign owner | `result_invalid` | No |
| Core `evaluated`, no summaries | `evaluated_empty` | Yes, **this scope only** |
| Core `evaluated` with at least one summary | `evaluated_items` | Yes, **this scope only** |

`coverage` is `complete` only if **all six approved modules** evaluated, `partial`
if any (but not all) evaluated and `none_evaluated` otherwise. `partial` is
never equivalent to an overall all-clear. A duplicate result fails closed **for
that module only**; an unknown owner cannot add an approval. Source/profile
state does not confer release-provenance or installed-producer certification.

Core's published v1 `validate_module_operations_invocation_result` and
`validate_module_attention_report(... expected_module_id=...)` are applied
again. A class-specific request rejects mismatched class or `ModuleWorkRef`
class. The action is validated against the exact approved owner and remains
**inert**. A raw source `ModuleAttentionSummary.label`, notice `summary`,
Core `result.message` or exception detail is never copied into this projection.
Internal `code`, context and action fields are hidden from `repr`, because
Core structural safety is not teacher-facing privacy approval.

## Slice B/C handoff

A later label-policy and formatter must use **approved, owner-reviewed**
category/notice labels or generic names; it must never blindly print the
stored owner code, `work_ref`, action ID or raw provider strings. The future
filter/formatter must retain the separate six-module coverage and cannot
synthesize urgency, cross-module counts or automatic owner actions.

Example of a **pure** caller (Core producer evaluation is **not** performed here):

```python
view = project_module_attention(
    metadata_inventory=metadata_from_issue16,
    profile_inventory=explicit_profile_diagnosis_or_none,
    request=explicit_core_request,
    invocation_results=already_obtained_core_attention_results,
)
assert len(view.modules) == 6
```

## Qualification boundary

Slice A synthetic tests are not evidence of genuine ScoreForm, Quillan,
Concord, Meridian, Vitrine or Portia attention results, a published Suite
wheel, a live teacher workspace, or #23 Teacher Home integration. Source
qualification: exact branch, focused pytest, Ruff and strict mypy. Clean
installed-wheel smoke, docs/matrix adoption and full PR CI are reserved for
subsequent slices and review gates. Core v0.6.6 remains the public v1 baseline.
