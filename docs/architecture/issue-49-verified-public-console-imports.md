# Issue #49 Slice 18 — Byte-checked candidate public-console import acceptance

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `d24d036e556b52d5c1cf346f1bdd552938e7dc8c`
**Status:** Opt-in staging observation, not production installation or launch authorization.

## Boundary and rationale

Slice 17 exercises the staged interpreter and `pip check` but does not test
whether approved console entry-point targets are importable. It also does not
compare every installed Python source file with the locked wheel. An import
probe without that check could execute altered code despite intact distribution
metadata and interpreter bytes.

`evergreen_public_contract_acceptance.accept_verified_candidate_public_contracts`
is a deliberately explicit opt-in staging acceptance action. It requires an
unarmed `candidate_verified` Slice 11 journal and exact matching raw evidence.
It takes cooperating journal and candidate-selection locks, refuses unfinished
recovery, and rechecks signed wheel/native evidence against the journal.

Before executing a candidate, `_site_inventory` checks the entire restricted
purelib `site-packages` file set against the source wheels authenticated by
the root-signed closed dependency lock, validates file hashes and sizes,
and checks each installed `RECORD` for exact ownership and verified entries.
Unknown, changed, extra, missing, symlinked and Windows-reparse files are
rejected. The source wheel is independently rehashed during expectation parsing.
The installed source-file audit uses the *actual* virtualenv's site-packages
location; Slice 8's legacy `stage/site-packages` layout is not assumed.

For each installed console entry point owned by a dependency-lock *root*, a
fixed non-user-supplied script runs `python -I -B -c` using the verified staged
interpreter. It checks `sys.prefix`, isolated interpreter settings, distribution
metadata ownership, exact public console name/target, importability, that the
imported module's file lies inside the staged site-packages, and that the
expected attribute is callable. It **does not call the entry-point function**.
Both the native inventory and complete code inventory are checked again after
probing; the journal and recovery marker must be unchanged. Failed imports,
nonzero subprocess status, timeouts, and changed stage bytes fail closed.

## Important limitations

- This deliberately **executes candidate Python import-time code** with the
  current user's privileges. `-I`, temporary working directories, sanitized
  environment variables, and subprocess timeouts are **not an OS sandbox**.
  Only a trusted, independently approved candidate may be deliberately probed.
- The present signed dependency lock does not by itself establish *delegated
  per-module PDS release provenance*. The full production trust chain must
  authenticate publisher-signed exact PDS release wheels before any teacher
  installation or launch authorization. This slice cannot upgrade that trust.
- This is importability of the wheel-declared **console target**, not a check
  that running a CLI is safe, a public provider API functions, a Core interface
  is compatible, or a mixed-module workflow is qualified.
- Strict purelib-layout support is intentional. Wheel `.data` schemes,
  compiled extension dependencies requiring external DLLs, installer-generated
  code/files, and other genuine pip-install layouts remain unqualified. The
  verifier fails closed rather than inventing acceptance for these layouts.
- Native binary hashing does not prove the safety of Windows DLL loading,
  filesystem ownership, absence of hardlinks, nor protection against hostile
  same-user concurrent modifications. Even repeated pre/post checks are not
  transactional isolation. Platform execution authority and persistent
  active-installation integrity require additional controls.
- The observation contains no launch permission, active receipt, activation
  flag, signing key, student data, command-output transcript, or classroom
  workspace path export. It does not modify the live launcher, update the
  active software pointer, write installation receipts, or perform network I/O.

## Next verified boundaries

1. Real Windows x64/ARM64 wheel/install-layout acceptance, including generated
   launcher templates, `.data` layout, system-dependent DLL references and
   independently published executable provenance.
2. Explicit named public PDS provider-contract acceptance distinct from console
   importability, with versioned Core routing/reader/operations contracts.
3. Authenticated per-module release artifact linking, historical active-state
   continuity, safe launch authority, and teacher-visible, approved updates.
