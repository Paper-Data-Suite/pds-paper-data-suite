# Issue #49 — Slice 120: held Win32 checkpoint/journal read boundary

**Parent:** Slice 119 (`03744ce53ec1343431a1df4e1fb42b9a5cf37b9d`). **Scope:** bounded read-only Win32 file-handle acquisition for the fixed ProgramData application state path. No service, privileged installer, durable checkpoint writer, OS-backed high-water mark, approval, or launch authority.

## Concrete change from Slice 119

Slice 119 used `lstat`, ACL observation, then `Path.open`, creating an obvious path-swap window. Slice 120 adds a *separate* Win32 reader that calls `CreateFileW` with `FILE_FLAG_OPEN_REPARSE_POINT` and `FILE_FLAG_BACKUP_SEMANTICS`, holds handles for each of the three fixed path components (`ProgramData`, `Paper Data Suite`, `service-state`) and both record files, refuses reparse-point, hard-linked file, and unexpected directory attributes from `GetFileInformationByHandle`, uses `GetFileSizeEx` and bounded `ReadFile`, and closes every opened handle in reverse order. The file opens permit only `FILE_SHARE_READ`, refusing concurrent write/delete sharing while the handles are held; the read-only operation does not create files. Missing or unsafe states refuse rather than invent genesis bytes.

The two bytestrings are interpreted while their files are held, checked against the existing canonical Slice 117/118 schemas, hashed, and related as prepared-old, prepared-new, or replacement-claimed-new. Contradictions refuse. Returned results include only digest, generation, phase, and status; they contain no arbitrary paths, secrets, rosters or student information. The diagnostic CLI has no caller path, `--apply`, or approval argument.

## Explicit custody limits

- This is a **Python process invoking native Win32 handle APIs**, not an independently installed native privileged service. Windows environment variables, interpreter, DLL imports, and local Python code can be influenced by the invoking user.
- `FILE_SHARE_READ` reduces, but does not eliminate, all path/object races, hardlink attacks, ancestor path redirection or privileged actor mutations; this is no replacement for final trusted handle provenance and exclusive native service transaction locking.
- The file reads do not establish owner/DACL custody, service SID, token privileges, machine-pinned signing keys, protected monotonic checkpoints, or durable write/flush/replace semantics. Slice 119's ACL snapshot remains *separately* diagnostic, not promoted to authorization by this read.
- Only an independent native installer/service with OS-administered provenance and protected state could validate and enact a transaction. Receipt publication, activation, journal deletion, retry, and recovery remain forbidden in this module.

## Native enforcement work following this slice

Implement the independently deployable Windows component with an authenticated executable and token, OS-anchored non-reparse handles, effective service/ACL/security descriptor validation, a protected transaction mutex, and a machine-controlled root pin and rollback witness. Add crash-injection tests at durable journal, CAS, and receipt boundaries; negative acceptance from the ordinary teacher account. Only then may a service authenticate a new installation and publish an active receipt. No Python observation dataclass is an authorization token.

## Test plan

Focused tests exercise all three coherent journal/checkpoint pairs, inconsistent identity/phase/size refusals, duplicate and noncanonical JSON, Win32 `GetFileInformationByHandle` attribute handling, `CloseHandle` cleanup on refusal, read sharing constraints, rejecting non-Windows hosts, and CLI no-mutation. Cumulative tests include Slices 104–120, release signatures, wheelhouse and dependency-lock gates. A passing test of mocked Win32 APIs proves the local parsing/flow only; actual Windows handle behavior must still be qualified on supported Windows x64/ARM64 hosts.
