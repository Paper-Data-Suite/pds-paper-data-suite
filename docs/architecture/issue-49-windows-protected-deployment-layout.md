# Issue #49 — Slice 106: read-only protected deployment layout

## Directories (not created by this slice)

- Executable installation: `%ProgramFiles%\Paper Data Suite`.
- Protected installed-state root: `%ProgramData%\Paper Data Suite`.
- Receipt custody: `%ProgramData%\Paper Data Suite\active-receipts`.
- Independent service transaction state: `%ProgramData%\Paper Data Suite\service-state`.

This is a **proposed layout** and a read-only preflight, not a deployment. A future separately administered installer/service must provision actual directories, set explicit OS ACLs and owners, separately protect the service process and active receipt head, and prove that normal teachers cannot modify executable bytes or protected state. Classroom workspaces remain separate and untouched.

## Policy

1. The Program Files base and existing PDS application directory must satisfy the strict Slice 104–105 ownership/DACL checks.
2. ProgramData itself is audited with an ancestor policy: ordinary users may create *other* child names, but may not delete children, alter parent ACL/ownership, or exercise other dangerous rights. This exception is **never** inherited by the named PDS directory.
3. The actual PDS state directory and the `active-receipts` and `service-state` directories each require strict privileged ownership and no untrusted effective write grant. A missing path reports `PROTECTED_DEPLOYMENT_PROVISIONING_REQUIRED`, never approval. Existing symlinks/reparse points and non-directory targets refuse.
4. Even when all checked directory ACLs pass, the status is `PROTECTED_DEPLOYMENT_DIRECTORY_ACLS_OBSERVED_ONLY`, with `production_authority=false` and `active_receipt_authority=false`.
5. This audit does not validate service identity, locked open file handles, file-level receipts, Windows token effective rights, Authenticode, durable witness-head continuity, or race-free execution. It is not an authorization API.

The CLI resolves default locations from the current Windows `ProgramFiles` and `ProgramData` environment variables; those values alone are **not independently trusted**. A production service must use an independently established OS path identity and immutable installation state rather than promoting this diagnostic to a trust decision.

Exit codes: `0` directory ACLs observed only; `2` at least one directory missing (provisioning needed); `1` malformed, inaccessible, or insecure path. No writes, key access, package operation, service changes or launch occurs.
