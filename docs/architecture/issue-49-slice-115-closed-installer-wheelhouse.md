# Suite #49 — Slice 115: signed closed-wheelhouse match to installer intent

## Purpose

Slices 112–113 established byte-canonical, untrusted installation intent using
real Python wheel distribution identities. Slice 114 matched each claimed PDS
wheel to fresh publisher/registry signatures and exact wheel bytes. Neither
establishes transitive dependency completeness. Slice 115 composes those
checks with the existing root-authorized signed dependency-lock verifier and
closed-wheelhouse inspection; it introduces **no new signature algorithm**.

`review_installer_locked_wheelhouse()` reparses the untrusted installer intent,
requires a freshly verified root-signed dependency lock tied to the same
registry SHA-256, and calls the existing closed-wheelhouse verifier, which
rejects missing/extra wheels, incompatible Python/wheel tags, digest mismatches,
and incomplete active dependency closure. It requires the lock root set to
match the installer distributions, excludes hidden or duplicate PDS wheels,
and matches each requested signed PDS wheel to its exact locked path, version,
and digest. It then invokes the Slice-114 signed-wheel verifier afresh and
reconciles the resulting per-wheel digests and registry identity.

External dependency wheels are covered by the root-authorized full lock and
its closed-wheelhouse inspection; they are not granted independent publisher
status merely by being present. No arbitrary path, package index, live
interpreter, teacher workspace, or installed receipt is affected.

## Trust boundaries and outstanding work

A local caller can choose a `TrustedKeyring` and can supply untrusted clock,
lock bytes and catalog bytes. This slice **cannot** prove keyring provenance,
independent custody of the trust root, protected anti-rollback checkpoints,
Windows administrator identity/consent, installed executable custody, protected
state continuity, or SCM service/token isolation. Successful output has status
`SIGNED_CLOSED_WHEELHOUSE_MATCHES_UNTRUSTED_INSTALLER_INTENT_ONLY` and **no**
installation, service, receipt, activation or launch permission.

`python -m paper_data_suite.evergreen_windows_installer_locked_wheelhouse`
prints `INDEPENDENT_SIGNED_DEPENDENCY_LOCK_NOT_SUBMITTED`, exits 2 and takes
no installer inputs or `--apply` command. It does no mutations.

## Acceptance

Targeted Slice 115 tests cover lock-to-intent registry/root agreement, exact
locked filename/version/digest, extra/duplicate PDS rejection, cross-wheelhouse
candidate substitution, forged bridge authorities, malformed inputs and
underlying verifier failure. Qualification also runs Slices 104–115, the
cryptographic signed-wheel tests and prior signed-lock/wheelhouse tests.

For a future production installer, the independent administrator must separately
provision pinned publisher trust, validate persistent revision checkpoints,
verify OS security/token custody and consent, then reverify the entire bundle
under the protected installation transaction. No teacher CLI may self-grant
this authority. Historical Suite 0.1.0, Core classroom workspace, and already
installed Python modules remain untouched.
