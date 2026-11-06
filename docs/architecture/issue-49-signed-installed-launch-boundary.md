# Issue #49 — Slice 98: signed wheel → installed code observation

## Purpose

Implement a genuine, non-executing validation boundary that receives an externally pinned `TrustedKeyring`, **re-verifies raw signed registry/module release envelopes**, validates the exact signed wheel bytes through `verify_signed_release_wheel`, and checks that the distribution visible to the *running interpreter* has the expected code and metadata. This begins the transition from historical Suite-version gating to independently authenticated release eligibility without weakening normal `pds launch` in the meantime.

`inspect_signed_installed_launch_candidate` does **not** change `pds launch` yet. Changing the command to accept a newer release based only on `pip check`, user-supplied public keys, a GitHub asset hash, or a locally replaceable receipt would be an unauthorized bypass. There is currently **no provisioned production signing root** or protected installed-state head in this pilot. No signed official release envelopes were supplied by the wheel-intake experiment.

## Security assertions

- The module re-runs `verify_signed_release_wheel` on raw signed envelopes and the exact wheel. It never trusts a caller-supplied `VerifiedReleaseWheel` object.
- Component ID must be a known PDS module and agree exactly with the signed module identity.
- The interpreter's installed distribution name and version must match the signed wheel. The installed distribution's root must remain under the running `sys.prefix`.
- Exact original wheel member bytes (excluding `RECORD`, which pip regenerates) must agree with the wheel's signed-included `RECORD` hash and size **and** with the corresponding installed file. Missing, changed, symlinked/reparse-point, escaped, duplicate, oversized, and malformed files fail closed. Unknown `.data` layouts fail closed.
- The selected console script must have one and only one installation-wide owner and agree with the signed script name/target. The module's executable itself is **not** validated by this step.
- Non-optional `Requires-Dist` constraints must have matching currently installed distribution versions. Extra-only requirements are not imposed; supported platform markers are evaluated on the running interpreter. Version compatibility is **not** transitive artifact authentication.
- Returns a frozen `InstalledSignedLaunchObservation` with `NO_LAUNCH_ACTIVATION_UPDATE_OR_INTEGRATION_AUTHORITY`. No `can_launch` bit, executable path, subprocess call, import of module code, or writes are provided.

## Unresolved production gates

1. Provision and pin genuine production publisher root(s) independently of catalogs and CLI arguments; verify delegation, current revocation, and monotonic signed revision checkpoints.
2. Establish an OS-protected active installed-composition receipt/head whose authenticity cannot be forged by the same local actor replacing wheels. Reverify the full signed transitive lock and all installed distribution records.
3. Validate native executable provenance, generated Windows launcher wrappers, and public launch boundaries, including platform ARM64-specific acceptance.
4. Wire a *new* authenticated production path into `pds launch`, preserving the historical manifest as a separate immutable baseline; ensure independently verified launch does not falsely imply full integration qualification.
5. In a disposable complete-dependency installed-wheel test, show old Suite refusing Quillan 0.10.6 and newly provisioned Suite safely launching it; the earlier isolated historical lab did **not** install third-party dependencies or launch Quillan.

An untrusted caller can construct arbitrary Python objects or keys; this implementation must be called only by a higher-level verifier with independently protected trust provisioning. An observed match is evidence, **not permission**.
