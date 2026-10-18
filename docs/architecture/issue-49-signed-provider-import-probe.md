# Issue #49 — Slice 28: Explicit signed-provider importability

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`
**Base:** `477ccf5` (the runner checks the full immutable commit)
**Scope:** Additive opt-in acceptance infrastructure; no production launch/update wiring.

## Separate assertions

Slice 27 establishes that a named Core provider entry point is declared by an independently publisher-authenticated PDS wheel and agrees with the installed `entry_points.txt`. **Declared** is not **importable**, and **importable** is not **Core-contract compatible**. Slice 28 adds only the second observation, without turning either into launcher eligibility.

`probe_signed_provider_import` accepts a known, registered component and one of the three bounded Core entry-point groups: `paper_data_suite.modules`, `paper_data_suite.module_operations`, and `paper_data_suite.publication_producers`. It requires `allow_candidate_execution=True` and a separate classroom-workspace path; it cannot be invoked by automatic update discovery, ordinary `pds launch`, or offline doctor.

Before executing, the adapter:

1. Verifies the software and classroom roots do not overlap and confines the candidate/wheelhouse to the software directory.
2. Recomputes the Slice 27 publisher-bound provider declaration and full real-pip package/launcher-file integrity checks from raw signed metadata and exact wheel bytes.
3. Rechecks Slice 10 root-signed native interpreter/launcher bytes from an independently provisioned trusted keyring and signed inventory; the local installer cannot sign its own observed hashes.
4. Obtains the distribution name from the verified signed registry, never from arbitrary provider input.

For a declared provider, the bounded staged interpreter is invoked as `python -I -B -c <fixed code>` from a temporary software-only working directory. The fixed probe ensures the staged interpreter owns `sys.prefix`, resolves exactly one installed distribution-owned entry point with the expected name/group/target, imports the declared module, traverses the validated attribute path, and checks `callable`. **It never invokes the provider callable.** Subprocess output is suppressed, timeout is bounded, package indexes and Python user-site imports are disabled, and inherited environment is reduced. The installed site is reauthenticated after the subprocess even if the subprocess fails. Byte or identity drift prevents success.

For an absent optional provider the adapter records `NOT_DECLARED`, without spawning candidate Python, after still validating signed software/native evidence. A successful declared provider produces only `IMPORTABLE_NOT_CONTRACT_TESTED`. Neither status provides `can_launch`, `provider_ready`, `activated`, or feature integration authority.

## Limitations and future acceptance

Python imports execute module initialization code and can touch the filesystem/network using the current OS user's authority. `-I`, a temporary working directory, timeouts, and hash checks are **not an OS sandbox**. Do not run unknown producer code unattended or claim malicious same-user mutation is defeated. Hashes are moment-in-time checks; hardlinks/reparse behavior and protected state continuity still need production scrutiny. No native-signing authority is provisioned by this slice, and testing uses synthetic test keys and wheels. No classroom data is read by the coordinator, but a hostile imported module is not sandboxed.

Actual Core public contract qualification requires exercising named provider profiles with the *installed Core version* and checking typed/contract-versioned metadata and side effects in a separately authorized acceptance suite. Signed exact integration attestations remain independent, as does teacher-facing readiness. Production activation/rollback receipt authority, current-release provisioning, offline status, and evergreen launching remain forthcoming.
