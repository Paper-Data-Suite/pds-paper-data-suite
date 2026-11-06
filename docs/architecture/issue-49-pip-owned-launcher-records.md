# Issue #49 — Slice 22: Pip-owned console scripts in installed RECORD

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `a61de79e97a2f1c3a7b8c0dd9aba419ef67fd95c`
**Scope:** Read-only installed-software inspection; no production runtime wiring.

## Compatibility finding

A real local, offline `pip install --no-index --no-compile --find-links ...`
trial on Python 3.13 wrote the generated console wrapper outside `site-packages`
and entered its path in the distribution's installed `RECORD` as
`../../../bin/prober`. On a Windows virtualenv, `Lib/site-packages` is two
levels below the environment root and `Scripts/demo.exe` is represented by
`../../Scripts/demo.exe`. Slice 21 rejected both forms because its shared
site `RECORD` parser (correctly) prohibits parent-directory components.

## Additive exception bound to authenticated ownership

The new `evergreen_pip_script_records.split_pip_record` partitions an
installed `RECORD` into internal site entries and specifically allowlisted
console-wrapper entries. The caller supplies the *only* permitted script names
from `inspect_staged_virtualenv`, which verifies exact console entry-point
ownership, public target, normal file type, and wrapper content against the
signed dependency-lock wheelhouse. No script path from `RECORD` is resolved,
normalized, or evaluated to obtain this allowlist.

`audit_staged_pip_layout` now binds each wheel's `RECORD` to its signed
prepared-record distribution identity. A script row may occur only in its
owner's `RECORD`. Its hash and size must match the already inspected file.
Duplicate rows, missing hashes, noncanonical SHA-256, different casing,
unauthorized scripts, backslashes, or arbitrary `..` references fail closed.
All other internal entries are passed through the existing strict
`_record_entries` implementation with no weaker path policy.

`require_launcher_records=True` requires an installed `RECORD` entry for
**every** inspected console wrapper owned by the wheel. It is intended for
future real-pip qualification. The default leaves prior synthetic stages
usable but refuses partial or unauthorized script listings. Both variants
remain non-authorizing observations. The audit now includes observed launcher
`RECORD` entries and their hashes in its deterministic inventory digest.

## What this does not establish

- A matching pip `RECORD` does not authenticate the Python interpreter or
  native Windows `.exe` code. The separately root-signed native evidence and
  delegated PDS publisher checks are still required.
- It does not qualify wheel `.data/scripts`, `direct_url.json`, native
  extensions, bytecode creation, alternate installers, or every Windows/ARM64
  packaging behavior. These remain fail-closed until separately reviewed.
- It does not construct an active-install receipt, switch environments, run
  pip, import candidate packages, access a classroom workspace, change
  `pds launch`, or grant module/interface permission.
- User-editable installer metadata cannot prove historical activation, and
  a one-time check is not a durable integrity or race-resistant guarantee.

Before production acceptance, run an isolated **real Windows pip
`--no-index --no-compile --find-links`** install with authenticated wheelhouse,
review generated script paths/metadata, and satisfy all other signed native,
publisher, runtime, Core and module-contract gates.
