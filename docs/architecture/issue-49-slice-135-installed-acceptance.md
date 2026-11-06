# Suite #49 — Slice 135: installed-machine negative-acceptance rehearsal

**Parent:** `50b810fb0616cbca3b5c07eba0cd4b8f0df2686c`.

## Why this is a separate gate

Slices 121–134 established native x64 and ARM64 **read-only** observations on unprovisioned CI machines, not installed-service acceptance. This slice provides one bounded, fail-closed *rehearsal* of the actual installed-machine checks. It joins **five** existing diagnostics under the current Windows process token: ordinary-user SCM access denial, the same process's individual SCM right requests, service-object owner/DACL and SID metadata, running-image path/held-handle owner/DACL observations, and claimed publisher-pin custody.

The purpose is to make an eventual **ordinary** account's missing evidence unambiguously rejectable, rather than allowing independent log fragments to be cherry-picked as an installation approval. A UAC-filtered administrator is not ordinary, and the native teacher-denial probe must reject it. If even one dangerous SCM right is granted, if the provisional service is missing/not running, if evidence has inconsistent fields, or if the publisher-pin claim is absent, the **installed** rehearsal refuses with exit **1**.

## Manual operator use — read-only and non-authorizing

From a **separately established** ordinary Windows user session on a future installed test machine, first independently obtain/build the release diagnostics from reviewed, signed artifacts. Then run the module from the audited checkout with the explicit CMake build directory (containing its `Release` subdirectory):

```powershell
.\.venv\Scripts\python.exe -m paper_data_suite.evergreen_windows_installed_acceptance_rehearsal `
    --build-dir "C:\path\to\verified\native\build"
```

The module launches exactly five hardcoded diagnostic executable basenames, once each, with no arguments and without a shell. It bounds output length and execution time, rejects stderr, duplicate JSON keys, unexpected fields, unsupported exit codes, contradictory claims, and missing no-authority markers. It does not ask for an account password or accept a caller-selected service identity or publisher-pin file. Neither diagnostics nor their containing build directory are independently authenticated by this module; the operator must establish artifact provenance **outside** this command before interpreting observations.

A fully consistent observational case produces `INSTALLED_MACHINE_NEGATIVE_REHEARSAL_OBSERVED_UNATTESTED`, **exit 2**, and explicit false values for independent teacher identity attestation, administrator approval, publisher-pin verification, rollback protection, service identity verification, and installation authority. **Exit 2 is not a pass or an installer release gate.** Exit **0 is never emitted**. On hosted CI, no protected `PaperDataSuiteService` is provisioned, so actual installed-machine acceptance is not demonstrated. No installation, service creation, elevation, protected writes, user creation, impersonation, reset, or rollback occurs.

## What an independent administrator must still establish

A real, signed independently administered installer/service must establish and document: **(1)** reviewed fixed service identity and secure service-object DACL, **(2)** installed executable provenance/signature and protected file custody, **(3)** protected publisher trust root and anti-rollback witness held outside teacher control, **(4)** externally authenticated administrative approval and protected checkpoint/receipt transactions, and **(5)** ordinary-user negative acceptance on the installed machine, with verifiable operator identity and independent review. Such attestations cannot be synthesized from this process's JSON or from a teacher-writable output file.

The Python source contract is tested on Linux and Windows with synthetic native outputs; native Windows binaries were qualified separately in earlier slices. This slice deliberately **does not grant** service identity, pin, rollback, receipt, provisioning, or installation authority. Its completion is one more prerequisite for future independent installed-machine testing, **not** production deployment acceptance.
