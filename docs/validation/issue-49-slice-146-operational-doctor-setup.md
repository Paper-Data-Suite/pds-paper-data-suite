# Suite #49 — Slice 146: operational doctor and compatible Core setup

## Scope

- Switch the **normal** `pds doctor` command to runtime installed-package observations from Slice 144, including approved Core, ScoreForm, Quillan, Concord, Meridian, Vitrine, and Portia distributions.
- Keep `collect_doctor_diagnostics` and all historical exact-release collectors intact for their existing qualification and regression tests. The new operational entry point is `collect_version_tolerant_doctor_diagnostics`.
- Report actual versions and separate **local compatibility**, **not historically integration-tested**, **incompatible/missing**, and **provenance unverified**. A version match alone does not authenticate official wheel bytes or certify any cross-module integration.
- Retain read-only `pip check`, Python, marker, public Core contract, workspace, module-operations provider, and paper-rasterization checks. A well-formed historical environment marker referring to an older composition becomes a warning in this manual-wheel workflow, **not** an assertion that it matches the current install. Invalid/unreadable markers remain failures.
- Permit a newer compatible Core version in the shared workspace loader used by `pds setup` and `pds workspace`. Production service loading requires Core's active metadata and dependencies to be compatible and still validates public callable interfaces. A valid Core version alone is not sufficient for successful setup.
- Preserve `pds setup` planning, exact `APPLY` approval, fresh preflight, Core-owned persistence, and all student-data safeguards. No software installation or package replacement is introduced.

## Explicit limits

- A local wheel installation may be **launch-compatible** while its official release provenance remains **unverified**; do not represent local metadata checks as publisher authentication.
- Core and producer provider checks may surface unavailable capabilities. Such checks do not change the independent module launcher decisions.
- The old release-tooling version pins are historical distribution evidence, not requirements for a manually installed healthy teacher environment.
- `pds setup` is classroom setup, **not** automatic package installation. Installing wheels remains a deliberate external action.
- No update catalog, signing ceremony, privilege boundary, student-data write, workspace selection, or automatic migration is part of this slice.

## Qualification plan

Run targeted suites for Slice 144/145/146, operational doctor, workspace setup, guided classroom setup, and CLI dispatch. Run Ruff and mypy only on modified/new source. The next slice (#147) performs installed-wheel positive/negative and broader teacher-journey acceptance at a release boundary.
