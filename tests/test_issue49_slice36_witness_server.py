"""Issue #49 Slice 36: mTLS head-read endpoint, no self-authorized headers."""

from __future__ import annotations

import hashlib
import http.client
import socket
import sqlite3
import ssl
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

from paper_data_suite.evergreen_active_receipts import (
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_checkpoint_witness import (
    issue_witness_challenge,
    verify_witness_statement,
)
from paper_data_suite.evergreen_journal_pip_preflight import (
    ObservedJournalPipCandidate,
)
from paper_data_suite.evergreen_witness_server import (
    WitnessServerError,
    create_witness_https_server,
    handle_witness_head,
)

NOW = datetime(2026, 10, 19, 19, 0, tzinfo=UTC)
INSTALL = "a" * 32
WITNESS = "independent_witness"


def _receipt() -> bytes:
    candidate = ObservedJournalPipCandidate(
        "b" * 32,
        1,
        "candidate/one",
        "wheels/one",
        "c" * 64,
        "d" * 64,
        (("quillan", "e" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )
    return make_untrusted_active_receipt(
        candidate,
        prepared_record=b"signed prepared",
        registry_envelope=b"root registry",
        lock_envelope=b"root lock",
        native_envelope=b"root native",
        generation=1,
        recorded_at=NOW,
        previous=None,
    )


@pytest.fixture
def store() -> tuple[MonotonicCheckpointStore, ed25519.Ed25519PrivateKey, bytes]:
    connection = sqlite3.connect(
        ":memory:", isolation_level=None, check_same_thread=False
    )
    key = ed25519.Ed25519PrivateKey.generate()

    def authorize(installation: str, operation: str, context: object) -> bool:
        return installation == INSTALL and (
            context == "admin"
            if operation in ("commit", "enroll")
            else context == "reader" and operation == "read"
        )

    instance = MonotonicCheckpointStore(
        connection, witness_id=WITNESS, authorize=authorize, sign=key.sign
    )
    receipt = _receipt()
    instance.commit_receipt(INSTALL, receipt, context="admin")
    return instance, key, receipt


def _headers(body: bytes) -> tuple[tuple[str, str], ...]:
    return (
        ("Content-Type", "application/json"),
        ("Accept", "application/json"),
        ("Content-Length", str(len(body))),
        ("Connection", "close"),
    )


def _call(
    store: MonotonicCheckpointStore,
    *,
    body: bytes | None = None,
    peer: bytes | None = b"verified-certificate-DER-fixture",
    identify: Any = None,
    headers: tuple[tuple[str, str], ...] | None = None,
    method: str = "POST",
    target: str = "/v1/receipt/head",
    now: datetime = NOW,
) -> Any:
    if body is None:
        body = issue_witness_challenge(installation_id=INSTALL, now=now).bytes
    if identify is None:

        def allow_reader(_fingerprint: str) -> str:
            return "reader"

        identify = allow_reader
    return handle_witness_head(
        method=method,
        target=target,
        headers=_headers(body) if headers is None else headers,
        body=body,
        peer_der=peer,
        identify_client=identify,
        store=store,
        now=now,
    )


def test_authenticated_head_response_matches_slice33_protocol(store: Any) -> None:
    instance, key, receipt = store
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
    observed: list[str] = []

    def authorized(fingerprint: str) -> str:
        observed.append(fingerprint)
        return "reader"

    response = _call(instance, body=challenge.bytes, identify=authorized)
    assert response.status == 200
    assert response.content_type == "application/json"
    assert observed == [hashlib.sha256(b"verified-certificate-DER-fixture").hexdigest()]
    assert verify_witness_statement(
        challenge=challenge,
        signed_reply=response.body,
        receipt_bytes=receipt,
        pinned_public_key=key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
        expected_witness_id=WITNESS,
        now=NOW,
    )


def test_header_identity_spoofing_rejected_before_policy(store: Any) -> None:
    instance, _, _ = store
    body = issue_witness_challenge(installation_id=INSTALL, now=NOW).bytes
    for header in (
        "X-Forwarded-Client-Cert",
        "X-SSL-Verify",
        "X-Client-Cert",
        "Forwarded",
    ):
        response = _call(
            instance,
            body=body,
            headers=_headers(body) + ((header, "fake-identity"),),
            identify=lambda _: pytest.fail("identity policy called"),
        )
        assert response.status == 400


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "HEAD", "PATCH"])
def test_only_post_permitted(store: Any, method: str) -> None:
    assert _call(store[0], method=method).status == 405


@pytest.mark.parametrize(
    "target",
    [
        "/",
        "/v1/receipt/head/",
        "/v1/receipt/head?a=1",
        "/v1/receipt/commit",
        "/v1/receipt/enroll",
    ],
)
def test_only_exact_head_route_permitted(store: Any, target: str) -> None:
    assert _call(store[0], target=target).status == 404


def test_missing_mtls_peer_denied_even_with_spoofed_headers(store: Any) -> None:
    assert _call(store[0], peer=None).status == 401


def test_unknown_mtls_certificate_denied(store: Any) -> None:
    assert _call(store[0], identify=lambda _: None).status == 403


def test_policy_failure_does_not_reveal_exception(store: Any) -> None:
    def broken(_: str) -> object:
        raise RuntimeError("secret authentication details")

    response = _call(store[0], identify=broken)
    assert response.status == 503
    assert b"secret" not in response.body


def test_store_authorization_is_still_required(store: Any) -> None:
    assert _call(store[0], identify=lambda _: "admin").status == 403


def test_reused_challenge_denied(store: Any) -> None:
    challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW).bytes
    assert _call(store[0], body=challenge).status == 200
    assert _call(store[0], body=challenge).status == 403


@pytest.mark.parametrize(
    "content_type",
    ["application/json; charset=utf-8", "text/plain", "APPLICATION/JSON", ""],
)
def test_only_exact_media_type(store: Any, content_type: str) -> None:
    body = issue_witness_challenge(installation_id=INSTALL, now=NOW).bytes
    headers = tuple(
        (k, content_type if k == "Content-Type" else v) for k, v in _headers(body)
    )
    assert _call(store[0], body=body, headers=headers).status == 415


def test_duplicate_length_rejected(store: Any) -> None:
    body = issue_witness_challenge(installation_id=INSTALL, now=NOW).bytes
    assert (
        _call(
            store[0],
            body=body,
            headers=_headers(body) + (("content-length", str(len(body))),),
        ).status
        == 400
    )


@pytest.mark.parametrize(
    "extra", [("Transfer-Encoding", "chunked"), ("Proxy-Authorization", "Basic aaaa")]
)
def test_ambiguous_framing_rejected(store: Any, extra: tuple[str, str]) -> None:
    body = issue_witness_challenge(installation_id=INSTALL, now=NOW).bytes
    assert _call(store[0], body=body, headers=_headers(body) + (extra,)).status == 400


@pytest.mark.parametrize("body", [b"", b"x" * 1025, b"bad-json"])
def test_bounded_noncanonical_challenge_rejected(store: Any, body: bytes) -> None:
    assert _call(store[0], body=body).status != 200


def test_no_implicit_server_or_signing_key_exports() -> None:
    import paper_data_suite.evergreen_witness_server as module

    assert not hasattr(module, "SIGNING_KEY")
    assert not hasattr(module, "server")
    assert not hasattr(module, "run_server")


def _certificate(
    subject_key: rsa.RSAPrivateKey,
    subject: str,
    issuer_key: rsa.RSAPrivateKey,
    issuer: x509.Name,
    *,
    ca: bool = False,
    server: bool = False,
) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    wall_clock = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(wall_clock - timedelta(days=1))
        .not_valid_after(wall_clock + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("witness.example.org")]),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def _keyfile(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


@pytest.fixture
def tls_contexts(tmp_path: Path) -> tuple[ssl.SSLContext, ssl.SSLContext, bytes]:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Independent Test CA")]
    )
    ca_cert = _certificate(ca_key, "Independent Test CA", ca_key, ca_name, ca=True)
    ca = tmp_path / "ca.pem"
    ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_cert = _certificate(
        server_key, "witness.example.org", ca_key, ca_name, server=True
    )
    cert = tmp_path / "server.pem"
    cert.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    keyfile = tmp_path / "server.key"
    _keyfile(keyfile, server_key)
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client_cert = _certificate(client_key, "independent-client", ca_key, ca_name)
    client = tmp_path / "client.pem"
    client.write_bytes(client_cert.public_bytes(serialization.Encoding.PEM))
    client_keyfile = tmp_path / "client.key"
    _keyfile(client_keyfile, client_key)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    server_ctx.verify_mode = ssl.CERT_REQUIRED
    server_ctx.load_cert_chain(str(cert), str(keyfile))
    server_ctx.load_verify_locations(cafile=str(ca))
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    client_ctx.load_verify_locations(cafile=str(ca))
    client_ctx.load_cert_chain(str(client), str(client_keyfile))
    return server_ctx, client_ctx, client_cert.public_bytes(serialization.Encoding.DER)


def test_factory_refuses_clientless_tls_context(store: Any, tls_contexts: Any) -> None:
    server_ctx, _, _ = tls_contexts
    server_ctx.verify_mode = ssl.CERT_NONE
    with pytest.raises(WitnessServerError, match="provisioning"):
        create_witness_https_server(
            bind=("127.0.0.1", 0),
            tls_context=server_ctx,
            store=store[0],
            identify_client=lambda _: "reader",
            clock=lambda: NOW,
        )


def test_factory_requires_server_tls_context(store: Any) -> None:
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with pytest.raises(WitnessServerError, match="provisioning"):
        create_witness_https_server(
            bind=("127.0.0.1", 0),
            tls_context=client_ctx,
            store=store[0],
            identify_client=lambda _: "reader",
            clock=lambda: NOW,
        )


def test_factory_requires_tls_12_or_newer(store: Any, tls_contexts: Any) -> None:
    server_ctx, _, _ = tls_contexts
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        server_ctx.minimum_version = ssl.TLSVersion.TLSv1_1
    with pytest.raises(WitnessServerError, match="provisioning"):
        create_witness_https_server(
            bind=("127.0.0.1", 0),
            tls_context=server_ctx,
            store=store[0],
            identify_client=lambda _: "reader",
            clock=lambda: NOW,
        )


def test_real_loopback_mtls_head_read_and_no_commit_route(
    store: Any, tls_contexts: Any
) -> None:
    instance, signer, receipt = store
    server_ctx, client_ctx, client_der = tls_contexts
    fingerprint = hashlib.sha256(client_der).hexdigest()
    observed: list[str] = []

    def policy(sha256: str) -> object | None:
        observed.append(sha256)
        return "reader" if sha256 == fingerprint else None

    server = create_witness_https_server(
        bind=("127.0.0.1", 0),
        tls_context=server_ctx,
        store=instance,
        identify_client=policy,
        clock=lambda: NOW,
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        challenge = issue_witness_challenge(installation_id=INSTALL, now=NOW)
        raw = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
        with client_ctx.wrap_socket(raw, server_hostname="witness.example.org") as sock:
            request = (
                b"POST /v1/receipt/head HTTP/1.1\r\nHost: witness.example.org\r\n"
                b"Accept: application/json\r\n"
                b"Content-Type: application/json\r\n"
                b"Connection: close\r\n"
                + f"Content-Length: {len(challenge.bytes)}\r\n\r\n".encode()
                + challenge.bytes
            )
            sock.sendall(request)
            response = http.client.HTTPResponse(sock)
            response.begin()
            content = response.read()
            assert response.status == 200
            assert response.getheader("Cache-Control") == "no-store"
            assert observed == [fingerprint]
            assert verify_witness_statement(
                challenge=challenge,
                signed_reply=content,
                receipt_bytes=receipt,
                pinned_public_key=signer.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                ),
                expected_witness_id=WITNESS,
                now=NOW,
            )
        raw2 = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
        with client_ctx.wrap_socket(
            raw2, server_hostname="witness.example.org"
        ) as sock:
            sock.sendall(
                b"POST /v1/receipt/commit HTTP/1.1\r\n"
                b"Host: witness.example.org\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            response = http.client.HTTPResponse(sock)
            response.begin()
            assert response.status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
