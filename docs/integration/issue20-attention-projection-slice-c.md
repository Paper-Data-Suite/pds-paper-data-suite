# Suite #20 Slice C — Explicit category-label policy and defensive ownership

**Issue:** [#20](https://github.com/Paper-Data-Suite/pds-paper-data-suite/issues/20)

**Exact source parent:** `3cfa9ad2d16da81b6589300a0ac578d4406764a9`.
**Published Core reference:** `pds-core` 0.6.6, module-operations v1.

## Approved label boundary

Core structurally validates `ModuleAttentionSummary.label` and notice text, but
cannot guarantee text is safe for a shared teacher-home attention view. Slice A
already discards both fields; Slice B shows the generic `Module attention item`.
Slice C introduces `module_attention_label_policy` with an **immutable,
source-reviewed exact `(owner_id, code)` allowlist**. As of this slice **no
producer-specific label has completed the #21/#22 owner/release/privacy
review**, so the allowlist is deliberately empty. Every category still displays
the generic static label. Actual labels may be introduced later only with
reviewed per-provider vocabulary, exact installed composition and adversarial
privacy regression evidence; neither user-supplied filter codes nor provider
report text may populate this table.

The display object now carries `category_label`, but accepts only labels from
the source-reviewed policy at render time. Replacing a display item with private
text fails with `invalid_attention_display`, not a partial user-facing report.
The stored owner code remains an inert exact filter and sort key, **never
printed** by the renderer. No priority/urgency inference is performed.

## Source and owner checks

The renderer must not trust that a frozen dataclass has stayed unmodified since
Slice A. It rechecks nested row and item types, verified owner identity, counts,
report state, declared profile evidence, requested class scope, and Core's
published work/action validators. Foreign owner actions and work references,
class mismatch, forged evaluated states, and malformed collections fail closed
per rendering attempt with **fixed, private-data-free error codes**.

These checks are **defense in depth for presentation**: they cannot attest that
an already obtained invocation result was actually produced for the stated
workspace/class at a particular time. Caller authorization, fresh scope and
request/result association remain mandatory for #21/#22 and action-time
revalidation belongs to #23. Owner actions remain inert.

## Non-goals and acceptance

No real provider is imported or invoked; no Core workspace is opened, no
student record/Notes body is copied, no network/process/write is performed.
Slice C does not create the #23 dashboard or assert any provider is installed,
authorized, approved for release, or returning semantically safe attention.

`tests/test_issue20_slice_c_privacy.py` exercises source-unreviewed vocabulary,
private label/action/work/class/category sentinels, forged owner/class scopes,
bogus display objects, profile-state tampering, malicious exceptions, and fixed
output/error strings. Run together with the previous A/B regression matrix,
Suite #16, current Teacher Home and ordinary packaging tests. The separate
clean official-Core/Suite installed smoke and final matrix are due under Slice D.
