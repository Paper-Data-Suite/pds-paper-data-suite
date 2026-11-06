# Issue #49 Slice 103 — Validation and acceptance

Expected parent: `60e8c9d1d7c3b47bf61a650fa48ad0e83789cbef` on `49-evergreen-launch-and-supported-composition-upgrades`.

Additive scope: `paper_data_suite/evergreen_signed_native_lab.py`, two Slice-103 pytest files, these two documentation files. Modified scope: `paper_data_suite/evergreen_signed_lab_launch.py`, `paper_data_suite/evergreen_signed_lab_cli.py`; no other files.

Tested locally against isolated stubbed external verifiers (NOT proof of Windows integration): 20 focused tests passed (13 native signature/byte tests, 7 CLI tests). Python syntax passed. Full Windows Ruff, strict mypy, complete Issue #49 and CLI regressions, dependency check, real signed-evidence issuance, and real native-gated Quillan help remain qualification gates.

Acceptance in a disposable Windows lab:

1. `python -m paper_data_suite.evergreen_signed_native_lab prepare ... --review-file <new file>` creates an unsigned native review; inspect exact native executable hashes and confirm the expected source of binaries before signing.
2. `... issue ... --review-file ... --root-private <existing development root PEM> --native-envelope <new file>` prompts for the development root passphrase; refuses drift since review; emits exact root-signed native evidence.
3. `pds launch quillan --signed-lab-native-help ... --native-envelope <signed file>` reauthenticates signed wheel, installed files, dependency closure, wrappers, and separately root-signed native bytes; only `quillan --help` may run.
4. Mutating either native executable, policy, signature, registry/module envelopes, or expiration must refuse; original `pds launch` historical path must remain unchanged.

Success indicator: `SIGNED_QUILLAN_0106_NATIVE_ATTESTED_HELP_EXECUTED_DISPOSABLE_LAB`.

Note: this only establishes **local root-signed native byte identity**, not vendor Authenticode authenticity, protected production launch authority, or process custody.
