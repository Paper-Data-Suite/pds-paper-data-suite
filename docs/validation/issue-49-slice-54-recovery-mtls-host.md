# Slice 54 — Validation and refusal evidence

## New files

- `paper_data_suite/evergreen_recovery_observation_server.py`
- `tests/test_issue49_slice54_recovery_observation_server.py`
- This validation record and the Slice-54 architecture note.

## Focused verification

The new test file generates an isolated test CA, server certificate and client certificate, configures an actual mutual-TLS server on a loopback ephemeral port, and verifies a signed Slice-50 Ed25519 service observation through the Slice-53 wire contract. It checks `no-store`, close-on-response, Content-Length, exact method/route isolation and certificate-authenticated gate/signature invocation. Refusal tests exercise client-certificate absence, forged identity headers, noncanonical/chunked/oversize request framing, route and method changes, and insecure/missing TLS or injected callback dependencies. The server does not automatically enter an event loop.

The dedicated Windows application runner requires exact committed Slice 53 HEAD `af3d3415a18a2bb12e3fe4d56beabf5293f15eac`, matching `origin`, clean working tree, SHA-256 checked four-file bundle and exact-only staged changes. It executes Ruff sorting, formatter, lint, format check, strict mypy of the production file, the entire Slice 1–54 regression inventory, `pip check`, staged whitespace and Git scope tests, then commits/pushes only after successful gates.

## Explicit limitations

Loopback mTLS tests demonstrate transport framing and certificate enforcement, **not** trusted service deployment, protected signer/gate, actual writer termination, released-wheel/ARM64 behavior, crash-safe active receipt mutation or production activation. No teacher/student data or real installation bytes are touched. Future installed and external-service qualification is necessary. On Windows without unprivileged symlink capability, earlier platform-specific symlink tests may skip as already documented.
