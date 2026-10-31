# Issue #49 Slice 103 — Root-signed disposable Windows native-byte boundary

## Scope

Adds a **separate lab-only** root-signature protocol for the exact `Scripts/python.exe` and `Scripts/quillan.exe` bytes within `historical_suite_010_quillan_0106_FULL_DEPS_LAB`. The root-signed payload binds these two executable hashes/sizes, the known Quillan 0.10.6 wheel hash, signed registry and module envelope SHA-256 hashes, and the independently supplied pinned trust-policy SHA-256. Signature uses Ed25519 with protocol-specific context `pds-issue49-signed-disposable-native-v1\0` to prevent a catalog signature from authorizing native binaries.

Only the `publisher-root` key from the pinned policy is accepted; an explicitly reviewed record is necessary before signing. The record expires seven days after creation. The signer refuses changed executable bytes, changed release evidence, inconsistent key identities, malformed JSON, duplicate fields, missing executables, unexpected paths, and existing outputs. Signing writes only a new evidence envelope, not the application or venv.

`pds launch quillan --signed-lab-native-help` requires the signed-native envelope and all existing signed module inputs; it verifies the Quillan package, dependencies, generated console wrapper, and **both signed native byte digests**, then executes **only** `quillan --help` in the named disposable environment. No arbitrary arguments or teacher-menu launch are possible under this mode. Existing `--signed-lab-check`, `--signed-lab-help`, and the historical default launcher remain unchanged.

## Security classification

`native_binary_digest_attested: true` means only that a locally generated, pinned development root key has signed **exact bytes** at a point in time. It does **not** establish that the bytes came from Microsoft, Python.org, pip, or the application publisher; does not prove the Windows native launcher's Authenticode status; does not protect against a check-to-execution race; does not authenticate transitive third-party wheel provenance; does not provide a protected installation receipt, OS service boundary, rollback resistance, or production launch authorization. The code does not create or provision a production trust root. Do not use this result to enable ordinary interactive `pds launch`.

An independently secured publisher and OS-enforced installed-state service remain necessary for production. Local developer custody and backup of the root key is not that boundary.
