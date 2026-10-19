# Issue #49 Slice 35 — Pinned HTTPS witness transport validation

- Parent commit: `2e1f6114c4951be1aa942dbf328b8e0d7de48556`.
- Scope: one additive transport module, one additive pytest module, two Markdown
  files; no CLI or production launcher modifications.
- Transport: canonical HTTPS-only DNS origin; one fixed POST route, bounded
  timeout and JSON response; independently pinned CA content, strict TLS peer
  and hostname verification, explicit mTLS client credential, no redirects,
  no proxy and no retry.
- Local tests: 37 Slice 35 checks; 115 passing across Slices 32–35 using
  an isolated reconstructed test tree. Connection/TLS behavior is mock-driven;
  no production witness server, TLS credential, or network handshake qualified.
- Windows gate: Ruff, strict mypy, every issue #49 Slice 1–35 test file,
  dependency consistency, staged whitespace and scope, then commit/push.
- Deployment precondition **not met** by this slice: an independently operated
  witness host/account, authenticated enrollment and caller identities,
  externally pinned keys and approved storage ACLs.
- Neither a successful HTTPS request nor a signed head authorizes activation,
  recovery, or production module execution.
