# Suite #49 — Slice 116: pinned-trust and checkpoint *consistency*

## Prior results

Slice 115 (commit `3aa5db13c15a7ca0d172f56c0d6a46c8be89c950`)
passed 494 Windows regressions, 6 skips, plus 29 focused tests; its diagnostic
returned `INDEPENDENT_SIGNED_DEPENDENCY_LOCK_NOT_SUBMITTED` (exit 2).
The four protected PDS deployment directories and service remain absent.

## Narrow new boundary

`review_installer_trust_and_checkpoints` composes existing verified components:

1. Strictly parse the Slice-112/113 canonical untrusted installer intent.
2. Load the Ed25519 keyring through `load_digest_pinned_trust_policy` only
   after its exact bytes match an externally supplied SHA-256 pin.
3. Reverify the root-signed registry with an explicit prior revision/digest
   checkpoint and the root-signed dependency lock with **both** prior registry
   and lock checkpoints. Reject lower revisions or same-revision equivocation.
4. Require the registry, lock, trust fingerprint and requested root set to agree.
5. Run the Slice-115 complete signed-wheel/closed-dependency verification with
   the matching keyring. Reconcile the exact request, signed registry payload,
   signed lock digest/revision and PDS distribution identities.

These checks are **read-only** and do not create files, install packages,
register services, change ACLs, access classroom workspace data, publish
receipts or select/launch module versions. No new signed-artifact or installer
format is introduced. The function is designed for future independent call-side
custody; it cannot prove custody itself.

## Critical trust boundary

The **calling teacher Python process can forge** the supplied policy digest,
checkpoint dataclasses, clock, and every ordinary review result. A passing
consistency review therefore CANNOT establish an independently pinned root,
protected rollback continuity, administrator identity, recovery readiness,
release approval or authority to provision/activate. The earlier module-signing
checks are repeated by Slice 115, but their historical module checkpoints are
not durably proven here. A future protected process must independently obtain
root pins and monotonic checkpoints from administrator-controlled, OS-protected
storage; revalidate and durably commit state without race conditions; authenticate
the administrator and consent; and perform non-admin negative acceptance before
installation or activation authority can exist.

## Diagnostic

```powershell
.\.venv\Scripts\python.exe -m paper_data_suite.evergreen_windows_installer_trust_checkpoint_review
```

Expected exit code **2** and
`INDEPENDENT_TRUST_AND_CHECKPOINT_EVIDENCE_NOT_SUBMITTED`.
No path, pin, signature, approval, credential or `--apply` option is accepted.

## Qualification

Guard exact parent, remote, branch and clean tree. Add exactly three files;
run Ruff (including import sorting), strict mypy, Slices 104–116 regression,
signed release and dependency-lock regressions and `pip check`. Commit/push
only after successful qualification. Any failure leaves files untouched for
narrow, separately authorized repair; never use reset/clean/stash/retry.
