# Suite #20 Slice B — Deterministic filtering and bounded, privacy-safe text

**Issue:** [Suite #20](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/20)
**Dependency:** #20 Slice A's `paper_data_suite.module_attention_projection` and its
public, nonexecuting `project_module_attention(...)` output
**Core baseline:** published Core v0.6.6 module-operations v1
**This slice:** add a pure filter/display adapter and focused synthetic tests.

## Inputs and nonauthorization

`filter_attention_projection(projection, *, module_id=None, class_id=None,
code=None, per_module_limit=5)` accepts only an **already produced** Slice A
`AttentionProjection`. It checks approved module identities and coherent
coverage again, maps each of six module rows to a safe `AttentionDisplayRow`,
and contains no provider factory/attention callback, file I/O, command,
network, cache, launch or Core write. `format_attention_display(display)` only
renders the bounded, immutable display result to plain text. These functions
are a consumer presentation seam, **not** a way to evaluate an actual module.

No source workspace, student record, Notes text, raw owner string, class/work
reference, action ID, exception message or unreviewed provider label/notice
is copied to the formatted text. All six module headings are compiled from
the approved Suite registry. The only owner-supplied data shown is the
**validated numeric count**, including the distinction between an absent
count (`count not supplied`) and explicit zero (`owner count: 0`).

The display intentionally uses the generic phrase **Module attention item**;
producer-specific reviewed, safe category names/notice vocabulary require
#20 Slice C and #21/#22 actual provider qualification. The category `code`
remains a hidden filter and sort key, not an automatically published label.
No owner-action or `ModuleWorkRef` is rendered or executed.

## Deterministic filtering

- Fixed approved owner order: ScoreForm, Quillan, Concord, Meridian, Vitrine,
  Portia. A `module_id` filter marks nonselected rows, but does not remove or
  pretend to evaluate them. The six-owner coverage remains tied to the source
  projection and is **never recomputed from filtered matches**.
- Exact `module_id`, `class_id`, and owner `code` filters only. Invalid filters
  fail with bounded static codes; the submitted filter values are never echoed.
- If the projection is already class-scoped, a filter for a different class
  fails with `attention_scope_mismatch` rather than broadening the source.
  A finding with no explicit `class_id` is **excluded** from an exact
  class-filtered view: its class must not be inferred from the UI selection.
- Within a module, matching items are ordered by `(class_id or "", code,
  original_position)` and shown up to `per_module_limit`, an integer 1–16.
  Overflow is counted and disclosed as **additional matching items not shown**.
  Nonmatching filters do not turn `evaluated_items` into `evaluated_empty`.
- Every view preserves evaluation state and indicates unqualified, absent,
  unavailable, invalid and failed owners as **unknown**, not zero. Evaluated
  empty applies only to the scope for which Core was invoked.

No category-based severity ranking, aggregate counts, total student estimates,
producer-private deduplication or universal urgency claim is permitted by the
Core v1 contract. The display reminds readers that counts are owner supplied
and not additive across modules.

## Consumer example (pure; no producer evaluation)

```python
from paper_data_suite.module_attention_rendering import (
    filter_attention_projection,
    format_attention_display,
)

# `projection` must already be produced by the explicitly scoped Slice A API.
view = filter_attention_projection(
    projection,
    module_id="scoreform",
    class_id="class_a",
    code="review",
    per_module_limit=5,
)
print(format_attention_display(view))
```

The output will mention that module/class/category filters are active but will
never print the raw class/code filter values or unreviewed provider wording.
All six module rows remain visible, with nonselected rows explicitly marked.

## Tests / qualification boundaries

`tests/test_issue20_slice_b_rendering.py` covers all-six rows, missing vs
zero, evaluated empty vs unavailable, partial coverage, exact filters and
classless items, deterministic order and count preservation, bounded overflow,
invalid arguments, forged projection/display identity, raw private label,
notice, work and action sentinels, and nonexecution. The source-only zip
includes **only** the new module, new tests and this document.

The local implementation smoke uses a **disposable Core/Suite contract-shape
shim**, not published Core/producer wheels; it is not release evidence.
The guarded Windows qualification runner requires exact clean remote and local
Slice A parent, verifies new source-member SHA-256 digests, runs Ruff, strict
mypy, compilation, and Slice A/B plus #16/#52 regression tests before a
conditional commit/push. A clean installed-Core wheel and teacher-journey
qualification still belong to #20 Slice D and issues #21–#23/#27 respectively.

**Not delivered in Slice B:** owner-reviewed category/notice labels and
adversarial source qualification (#20 C), actual ScoreForm/Quillan/Concord/
Meridian/Vitrine/Portia attention callback execution (#21/#22), interactive
Attention Needed menu or owner-action routing (#23), and live teacher data.
