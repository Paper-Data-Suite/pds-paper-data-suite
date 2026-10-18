# Issue #49, Slice 9 — Read-only staged virtualenv / console metadata

**Branch:** `49-evergreen-launch-and-supported-composition-upgrades`

**Status:** Additive read-only diagnostic infrastructure. **NOT a trusted installed
receipt, native executable authenticity check, update activation, or launcher
eligibility.** No production key provisioning or production launch change.

## Staged virtual environment boundary

`evergreen_staged_runtime.inspect_staged_virtualenv` accepts only an isolated
stage root, authenticated wheelhouse, prepared-not-installed composition bytes,
raw signed registry/lock envelopes, independently approved public-keyring, and
current time. It calls the Slice 7 prepared-record verifier, which revalidates
root signatures, revision requirements when supplied, exact locked wheel bytes,
active dependency closure and current host compatibility. This prevents a
caller-created `Verified*` dataclass or a mutable unsigned prepared record from
being used as the signing authority.

This routine checks a conventional Windows `Scripts` + `Lib/site-packages`
virtualenv layout or POSIX `bin` + `lib/pythonX.Y/site-packages`. The optional
`layout` parameter exists to exercise both layouts in synthetic tests and does
not change the authenticated *host* constraints on the signed lock.

It refuses the running Python environment, a stage inside or enclosing the
running environment, missing/wrong-type directories, link/reparse intermediate
staging directories, linked scripts, and `pyvenv.cfg` configurations with
`include-system-site-packages` other than explicit `false`. It does not invoke
staged Python, pip, modules, or launchers.

## Distribution and wrapper inspection

- The staged `.dist-info` directory names must match the **exact complete**
  locked distribution set; added/absent distributions fail.
- Critical installed `METADATA`, `WHEEL`, and `entry_points.txt` bytes must
  match their **reopened, rehashed** signed-wheel copies. For each critical
  installed file, the installed `RECORD` must also contain one matching
  SHA-256 and size row. A staged forged `RECORD` is not trusted by itself.
- Source wheel `console_scripts` establish expected launcher owner, script
  name and Python target; duplicates fail. Case-fold name collisions are
  rejected for Windows.
- The expected generated Windows `.exe` must look like an MZ executable with
  a single embedded `__main__.py` ZIP member. On POSIX, expected scripts need
  a shebang. The **AST** of the embedded wrapper must match the ordinary
  `distlib` import-and-call template exactly, with no additional instructions.
  Missing wrappers and unknown Windows `.exe` files fail.
- Staged `.pth`, `sitecustomize.py`, `usercustomize.py`, and `.egg-link`
  startup mechanisms are refused rather than treated as benign.
- All checks are read-only. Tests cover isolated Windows/Unix shaped fixtures,
  tampered signatures/wheels/metadata/RECORD/wrappers, foreign distributions,
  unowned executables, links, and active-environment refusal.

## Deliberate limitations

**Matching embedded `__main__.py` does not authenticate the surrounding
Windows PE binary.** A malicious executable can embed a benign-looking ZIP.
The stage's Python executable is also not authenticated here. Accordingly the
result has `native_executables_authenticated=False` and **no** `can_launch`
or `active_install` assertion. Neither wrapper AST equality nor a mutable
installed `RECORD` suffices to approve execution.

This is metadata inspection of a *restricted* stage. It does not yet validate
complete pip-generated installed layouts (`.data` scripts, all installed files,
`.pyc`, external native DLLs, extension loading), every possible pip launcher
variant, absolute interpreter relocation, cross-machine stages, binary code
signatures, or concurrent hostile filesystem replacement. Unsupported wrapper
patterns fail closed. The future installer must verify the actual generated
exe/interpreter/provenance and combine those with the byte-level Slice 8 audit
or its real-pip extension. No script is executed by this slice.

Local cache rollback protections are still only as strong as the trusted
external anchor; test synthetic signing keys are not approved production keys.
An offline verified active environment eventually needs a separate protected
receipt, atomic activation, recovery and independently scoped integration
qualification. Neither stage observations nor prepared records enable current
`pds launch` or updates. There are no workspace or student-data operations.
