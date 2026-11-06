# Issue #49 Slice 102: Actual Suite CLI lab integration

Suite's existing `pds launch <component>` remains pinned to its historical release-compatibility manifest. Slice 102 adds an explicit, visibly nonproduction laboratory alternative **to the same CLI command**. It does not authorize arbitrary versions or production launch, replace a protected installation head, create native-code custody, or authenticate third-party binary provenance.

Two mutually exclusive modes are added to `pds launch quillan`:

- `--signed-lab-check`: read-only signed evidence and installed-code check.
- `--signed-lab-help`: repeat the check, then run **only** `quillan --help` in the named disposable laboratory.

Both require all six evidence inputs (`--lab-venv`, `--wheel`, `--trust-policy`, `--trust-sha256`, `--registry`, `--module`). `pds launch quillan` without the flags retains the historical refusal; partial evidence without opt-in fails without fallback. Other component IDs, conflicting flags, arbitrary child arguments, or missing evidence fail closed. All execution gates, dependency checks and lab environment restrictions reside in Slice 101 (`evergreen_signed_lab_launch`), which is called with explicit reconstructed argv.

The new pathway authenticates signed Quillan wheel evidence with a **caller supplied policy pin** in a disposable lab, but this pin is not a production provisioning authority. Production requires an independently provisioned immutable/persistently protected root, monotonic signed catalog revision tracking, complete transitive artifact authentication, installed bytes and launcher executable custody, and a protected active installation record before the historical production launch restriction can be replaced.

No mutable teacher settings or classroom workspace are touched by the new path. It does not write a recent-component preference or provision a signing key. Production `pds launch` acceptance is explicitly **not** asserted by this slice.
