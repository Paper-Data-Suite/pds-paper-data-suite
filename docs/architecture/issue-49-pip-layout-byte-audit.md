# Issue #49 — Slice 21: Pip-style installed wheel byte audit

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `ea0604a` (runner checks the full SHA)
**Scope:** Additive, read-only software verification; no production wiring.

## Why this slice exists

Earlier verification treats wheel members as files under an unrelocated
`site-packages` root. Pip can install `.data/purelib` and `.data/platlib` wheel
members into the actual site-packages directory and rewrite the installed
`RECORD`. It can also add `INSTALLER` or `REQUESTED` to installed `.dist-info`.
Treating the original `RECORD` bytes as the installed truth would incorrectly
reject such a layout; trusting arbitrary generated records would be unsafe.

## Contract

`audit_staged_pip_layout` checks an isolated, read-only virtual environment:

1. Revalidates its signed dependency lock, wheelhouse, prepared transaction,
   virtualenv metadata and expected console launchers via existing verifiers.
2. Rehashes every source wheel before and after reading its archive members.
3. Maps wheel-root members and only the standard `.data/purelib` and
   `.data/platlib` schemes to the installed site-packages namespace.
4. Rejects any exact or case-conflicting Windows destination collisions,
   symlink/reparse files in the installed site, and unrecognized files.
5. Treats installed `RECORD` as an installer-generated accounting manifest:
   every wheel-owned file must be present with the exact digest and length,
   and the own `RECORD` row must be unhashed. No foreign rows are allowed.
6. Accepts only absent or precise pip-generated `INSTALLER` (`pip\n`) and
   `REQUESTED` (empty bytes) records. If present, these must also be correctly
   accounted for in `RECORD`.
7. Produces a deterministic SHA-256 inventory observation. Nothing writes to
   the staged software, installs wheels, executes programs or touches teacher
   workspace files.

**Explicitly unsupported:** `.data/scripts`, `.data/data`, `.data/headers`,
compiled `__pycache__`, unowned install metadata (`direct_url.json`, etc.),
installers other than the narrow pip forms above, native binary provenance,
and a candidate not independently qualified through the publisher boundary.
Failing closed on these cases is intentional rather than a claim that all
possible real-pip installs have already been qualified.

## Safety and limitations

This audit matches **bytes at the time of inspection**, not permission to run
code. A root-signed lock authenticates dependencies, not independently signed
PDS module release provenance; those publisher checks remain mandatory.
Interpreter and generated executable authentication still rely on the native
evidence gate. A `RECORD` hash, even a perfect one, is not a protected active
installation receipt. File-hash passes do not eliminate same-user concurrent
mutation, Windows hardlink races, or untrusted installer-origin risk.

The suite uses synthetic signed wheels and pip-shaped Windows/POSIX virtualenvs.
A separate real Windows pip `--no-compile` installed-wheel acceptance trial
is required before treating this layout as fully qualified for production.
No changes to `pds launch`, update discovery, bootstrap, doctor or installation
activation are introduced here.
