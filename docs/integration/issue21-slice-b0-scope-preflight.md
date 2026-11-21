# Suite #21 — Slice B0: explicit read-only attention scope preflight

**Companion:** [Slice A released-provider audit](issue21-slice-a-released-attention-audit.md) · [Core #249](https://github.com/Paper-Data-Suite/pds-core/issues/249)

## Boundary delivered

`paper_data_suite.module_attention_selection.prepare_selected_attention_scope`
takes a **caller-supplied** absolute `Path`, a concrete active school-year
string, optional class identifier and a nonempty exact tuple of requested
approved owners (`scoreform`, `quillan`, `concord`). The call is read-only,
has no CLI registration, and does not import any producer. It returns a bounded
`AttentionScopePreflight` with a private `ModuleOperationsRequest` only on
`scope_validated`. The request is excluded from repr. No profile, callable,
publisher attestation, capability result or owner action is returned.

Positive preflight requires:

1. An explicit canonical absolute directory, not a filesystem root, missing
   path, relative path, traversal, symlink or junction redirect.
2. Core's **public** `inspect_workspace_root(explicit_root)` to confirm the
   exact existing directory, not a substituted configuration/default.
3. Current Core-selected root from public `resolve_workspace_root()` to be
   identical to the explicit selected root. A changed selection fails closed;
   this is a comparison only and never a fallback evaluation workspace.
4. Public `get_active_school_year(root)` to exactly equal the requested
   **open** year. The Core year-state parent/file and classes collection must
   not redirect through symlinks into another workspace.
5. If one class was requested, a present canonical Core class folder with no
   path redirect. No roster content, students, scans or Grade state is read.
6. Exact `ModuleOperationsRequest` validation by Core v1; only a unique,
   approved subset of owners is allowed, then returned in fixed Suite order.

The refusal codes are static: `invalid_selection`,
`workspace_unavailable`, `workspace_mismatch`,
`school_year_mismatch`, `class_unavailable`. No provider/private exception
strings, file paths, class identifiers or arbitrary user labels are rendered
from the refusal. Scope data is held in memory only.

**Security limitation:** This is a prerequisite, **not proof of the user's
identity, current-session consent, filesystem race freedom, official release
provenance, or provider admission**. No producer may be invoked solely because
`scope_validated` was returned. The future explicitly authorized caller must
reconfirm fresh scope just before invoking a Core-selected, provenance-
qualified provider. Core #249 must supply the public **exact-owner** profile
selector and a compatible published wheel before the live Suite #21 invocation
seam can be approved.

## Synthetic acceptance

`tests/test_issue21_slice_b0_scope_selection.py` uses Core's real workspace
and year creation APIs to set up **fictional** roots before calling the preflight
and checks:

- Correct current root, year, class and subset of owners.
- Non-mutation of the previously created synthetic workspace, including
  file names and SHA-256 digests.
- Missing/relative/root/invalid-path, missing/mismatched year, class absent,
  owner duplicates/unknowns/unapproved owner, and changed Core selection.
- Exception strings and private path/class fields do not leak through `repr`.
- No ScoreForm, Quillan or Concord module imports during scope preflight.
- Symlinked class redirects rejected when host permits symlink fixtures.

On a Windows machine with the Suite branch already checked out, run:

```powershell
$ErrorActionPreference = "Stop"
python -m pytest -q -ra `
  tests/test_issue21_slice_b0_scope_selection.py `
  tests/test_issue21_slice_a_contract_audit.py `
  tests/test_issue20_slice_a_projection.py `
  tests/test_issue20_slice_c_privacy.py

python -m ruff check `
  paper_data_suite/module_attention_selection.py `
  tests/test_issue21_slice_b0_scope_selection.py

python -m mypy paper_data_suite/module_attention_selection.py
```

The one strict `XFAIL` in Slice A remains the **Core 0.6.6 unsupported targeted
diagnostic**, not a passing native integration. Passing B0 tests proves
selected-context inspection behavior only. It does **not** prove actual
installed ScoreForm/Quillan/Concord attention callbacks or read-only producer
queries, publisher provenance, cross-owner failure isolation under installed
wheels, Windows ARM acceptance or a teacher dashboard.

## Next qualified boundaries

- **Core #249:** support exact-owner public profile acquisition without
  loading unrelated candidates; no second loader in Suite.
- **B1 (ScoreForm):** published Core + ScoreForm SHA-verified wheelhouse;
  admitted profile and real, independent `invoke_module_attention` callback
  against a freshly revalidated synthetic selected workspace; owner/class
  checks, safe static labels and genuine scan/Share Results facts.
- **B2–D:** Quillan/Concord independent release qualification, including
  per-producer partial-report, returned-paper and action-authority semantics.
- **E–F:** final three-producer clean installed composition, no-write digests,
  Windows/Ubuntu regression/CI and separately approved PR/merge.

No ordinary `pds` startup, `--help`, `pds launch` or Teacher Home path
imports this new module or invokes attention. Suite #49/#52 remain unchanged.
