# Issue #49 — Operator-only external witness acceptance (Slice 37)

Slice 37 provides a deliberately **opt-in, read-only operator smoke test** of
an independently configured witness endpoint. It composes the established
Slice 32 canonical receipt, Slice 33 fresh challenge and signed verifier,
Slice 34 monotonic store, Slice 35 pinned mTLS transport, and Slice 36 head-read
endpoint. Ordinary `pds launch`, `pds doctor`, and module discovery **do not**
call this interface. There is no new Suite dispatcher command or background job.

## Entry point

Run only after a separate operator has provided the witness service and both
out-of-band SHA-256 pins. There are **no shipped keys or example passwords**:

```text
python -m paper_data_suite.evergreen_witness_acceptance \
  --origin https://witness.example.org \
  --ca-file /independent/ca.pem \
  --ca-sha256 <sha256-of-exact-ca-file-from-operator> \
  --client-cert /provisioned/client.pem \
  --client-key /provisioned/client.key \
  --witness-key /independent/witness-ed25519-public-raw.bin \
  --witness-key-sha256 <sha256-of-raw-key-from-operator> \
  --witness-id independent_witness \
  --installation-id <32-lowercase-hex-installation-id> \
  --receipt /independent/active-receipt.json \
  --minimum-revision 1
```

The example placeholders are not valid credentials; the command must be
populated with a genuine deployment's separately approved identifiers. The
witness key file is the **32 raw public-key bytes** (not a PEM certificate).
A witness public-key digest supplied from the same untrusted files is not an
independent trust anchor. A minimum revision supplied from the same
replaceable local store cannot prevent rollback. Obtain values from an actual
outside authority or independently protected anti-rollback record.

The command rejects missing, symlinked/reparse, nonregular or oversized
public-key and receipt files, matches the key to the caller-supplied digest
*before* initiating network contact, and validates the exact signed response
against the local receipt, expected witness/installation identities, fresh
nonce and optional minimum revision. TLS uses Slice 35's fixed DNS HTTPS origin,
exact CA file digest, and client certificate. It makes one request; no retry,
redirect, proxy or wildcard endpoint. Only the service's head-read route is
contacted. It never sends the receipt to the server.

## Result and non-authority

Successful acceptance prints:

```text
SIGNED_HEAD_MATCHED_DEPLOYMENT_UNVERIFIED
Deployment independence: NOT VERIFIED
Installation integrity / production activation: NOT AUTHORIZED
```

The report contains a witness revision and the digest of the local receipt,
not a permission to launch. A malicious operator could provision a witness
under the teacher's account and provide matching pins. This protocol check
cannot prove protected database ACLs, independent signing-key custody,
service-account separation, offline availability, server-side commitment
approval, publisher-signed installed bytes, physical host hardening or
classroom update recovery. Do not put the service database, private signing
key, installed-state receipts, or signing trust material in OneDrive/workspace.

## Required subsequent gates

- Independently deploy and provision the witness server, service account,
  database ACLs, private signer, and client-certificate policy; independently
  audit those protections and issue a protected operator approval.
- Qualify actual released wheels and root-signed publisher/catalog metadata.
- Implement crash-consistent activation, protected predecessor retention,
  recovery, and a fresh installed-byte verifier with no writable-state trust.
- Only then wire independently verified per-module launch eligibility and
  scoped integration status into the teacher-facing `pds` commands.

The `WitnessAcceptanceObservation` intentionally has **no** `can_launch`,
`is_deployment_trusted`, checkpoint mutation, installation or activation API.
Its `status` is always `SIGNED_HEAD_MATCHED_DEPLOYMENT_UNVERIFIED`.
