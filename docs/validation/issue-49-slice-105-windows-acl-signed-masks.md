# Issue #49 — Slice 105: Signed Windows ACL rights normalization

Slice 104 found `invalid DACL identity or rights` for the root `Program Files` directory. This is an inconclusive ACL audit, not a finding of insecure Windows permissions.

.NET FileSystemRights is a signed 32-bit flags enum. `GetAccessRules` can report generic READ or EXECUTE bits with a negative decimal value even when the underlying ACE is legitimate. The former verifier rejected every negative value and thereby gave a false refusal for such masks.

Slice 105 accepts JSON integers in the complete 32-bit unsigned mask range and its signed two's-complement representation (-2^31 through 2^32-1), converts the mask to 32 bits with `& 0xFFFFFFFF`, and then evaluates permissions. Out-of-bounds numbers, floats, booleans, strings, malformed DACL entries, untrusted owners, and write grants remain rejected. The write mask also now explicitly includes GENERIC_ALL (0x10000000) and GENERIC_WRITE (0x40000000), which were not handled by Slice 104. Deny ACEs still do not cancel an allow in this conservative audit.

This is a read-only path and ACL observation; it does not install a protected service, establish protected receipt custody, issue a launch token, or authorize a production environment. The user should rerun the Program Files and Downloads audits. Full Issue #49 regression was not rerun for this isolated ACL-parser correction; Ruff, strict mypy and the focused Slice 104–105 suites qualify it.
