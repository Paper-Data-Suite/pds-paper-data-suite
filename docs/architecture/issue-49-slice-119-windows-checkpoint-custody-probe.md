# Issue #49 — Slice 119: Windows checkpoint custody inventory (read-only)

**Parent:** Slice 118 commit `786246332e657d00651318bcf98fb921119af3e2`.

This slice adds a genuine OS-backed **observation** of proposed checkpoint and journal files, rather than accepting all path/ACL data from a caller. The default command is fixed-path, read-only, bounded, and fail-closed. It does **not** implement a privileged Windows installer, provide safe handles, approve the local user, or establish a protected monotonic counter. Production services must **not** consume its return objects as authorization credentials.

## Fixed proposed path inventory

On Windows, `python -m paper_data_suite.evergreen_windows_installer_checkpoint_custody_probe` observes:

- `%ProgramData%` as a candidate OS base (the value comes from the process environment and is NOT a secure OS anchor)
- `%ProgramData%\Paper Data Suite`
- `%ProgramData%\Paper Data Suite\service-state`
- `service-state\installer-checkpoint-v1.json`
- `service-state\installer-intent-journal-v1.json`

These file names are a *proposed bootstrap wire contract*, not claims that existing software has already deployed the files. The CLI does **not** accept arbitrary path or `--apply` arguments. It never opens classroom workspace data, writes files, invokes SCM, initializes genesis, deletes/retries a transaction, elevates, changes ACLs, or activates a release.

For each existing node, the probe rejects symlinks/reparse points and unexpected filesystem types using `lstat`. It queries existing Windows ACL policies through the Slice 104/106 Windows PowerShell-backed ACL observers: `ProgramData` receives the conservative state-parent policy; PDS child directories and the two files receive strict ordinary-user write refusal. ACL failures are refusal, not permission to fix ACLs automatically.

Only after both file nodes pass the ACL/type observation does the probe read at most **4,097 bytes per file**, refusing sizes beyond 4,096. It validates canonical checkpoint and journal JSON using the existing Slice 117/118 parsers and computes SHA-256 digests. The response never discloses raw checkpoint, journal, transaction ID, request contents, or classroom information. File reads are still subject to time-of-check/time-of-use races: Python path operations are **not equivalent** to locked native OS handles.

## Outcomes

| Inventory | Diagnostic status/relationship | Privileged interpretation |
| --- | --- | --- |
| Missing app or service-state directory | `PROTECTED_CHECKPOINT_PROVISIONING_REQUIRED` | Independent admin must provision and recheck ACLs; no implicit install |
| Both checkpoint and journal absent | `PROTECTED_CHECKPOINT_GENESIS_NOT_ESTABLISHED` | Never infer legitimate genesis from missing bytes |
| Only one file present | `PROTECTED_CHECKPOINT_INCOMPLETE_REFUSE_RECOVERY` | Quarantine for independent recovery |
| Canonical checkpoint generation 0, `INTENT_PREPARED` matches previous digest | `PREPARED_PREVIOUS_STATE_OBSERVED` | May be interrupted; native CAS preconditions still absent |
| Generation 1, journal still `INTENT_PREPARED`, matching exact transaction/hash | `REPLACEMENT_WITH_UNFINALIZED_JOURNAL_OBSERVED` | Independent durable postcondition needed |
| Generation 1, journal `CHECKPOINT_REPLACED_CLAIMED`, matching transaction/hash | `REPLACEMENT_CLAIMED_COMMIT_UNVERIFIED` | No receipt, approval, or launch without independent commit attestation |
| Any contradictory, noncanonical, oversized or ACL-unsafe evidence | **REFUSED**, exit `1` | Never repair silently, never rewrite files |

Any successful observation, including a missing-file status, exits **2** to distinguish the **unverified** diagnostic from a usable production installation. Every returned authority flag is false. An absent or successful status is never a permit to create a service or active receipt.

## Native Windows implementation requirements still outstanding

1. **Secure path origin:** obtain OS-known paths from trusted Windows APIs instead of user-controllable `%ProgramData%`; reparse-safe root-relative handles with no traversal into arbitrary volumes.
2. **Native access checks:** open every parent and file with stable handles and validate actual effective DACL/owner/token privileges after opening; the current PowerShell ACL snapshot can be raced and cannot prove negative effective access for all principals.
3. **Privileged identity:** independently signed/bootstrap-installed binary and Windows service account/SID/SCM DACL established under an authenticated administrative transaction. Teacher-run Python cannot install itself into that role.
4. **Durable CAS and independent antirollback:** exclusive lock, separately protected ledger, journal fsync/flush, atomic replace guarantees, monotonic checkpoint, post-write verification and crash replay. A DACL-protected JSON file alone is not antirollback.
5. **Negative acceptance:** run as ordinary teacher: attempt safe creation/replacement/delete, service reconfiguration and impersonation checks against a *sandboxed* installation, without risking protected real data. Prove refusal before release.
6. **Installation acceptance:** bind verified OS-owned checkpoint state to official signed wheel inventory, runtime and active receipt before activation, and demonstrate recovery under simulated crashes and actual Windows ARM64/x64 path constraints.

## Tests and qualification

The focused regression covers three coherent interruption states, absent/incomplete parents and files, unsafe file types, symbolic links, overlarge/corrupt inputs, transaction mismatch, unsafe ACL grants at parent/app/state/file levels, invalid inputs and non-authorizing CLI behavior. Explicit, short `pytest.mark.parametrize` IDs prevent oversized Windows `PYTEST_CURRENT_TEST` environment variables. Runner enforces three **additive-only** paths and exact Slice 118 Git parent; runs Ruff, strict mypy, cumulative Slice 104–119/signed-wheel tests, `pip check`, then guarded commit and push. No `git reset`, stash, clean, force push or rollback.
