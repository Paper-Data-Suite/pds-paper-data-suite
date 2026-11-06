"""Slice 54: real loopback mTLS host for signed, read-only service status."""

from __future__ import annotations

import hashlib
import http.client
import socket
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
    ExternallyPinnedReceiptHead,
    make_untrusted_active_receipt,
)
from paper_data_suite.evergreen_journal_pip_preflight import ObservedJournalPipCandidate
from paper_data_suite.evergreen_recovery_observation_http import (
    make_service_recovery_observation_request,
)
from paper_data_suite.evergreen_recovery_observation_server import (
    RecoveryObservationServerError,
    create_recovery_observation_https_server,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
    serialize_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceState,
)

NOW = datetime(2026, 10, 23, 19, tzinfo=UTC)
INSTALL = "a" * 32
WITNESS = "independent_witness"
CHALLENGE = b"Z" * 32
ROUTE = "/v1/recovery/service-observe"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate(tx: str, stage: str) -> ObservedJournalPipCandidate:
    return ObservedJournalPipCandidate(
        tx,
        1,
        stage,
        stage + "-wheels",
        "3" * 64,
        "4" * 64,
        (("quillan", "5" * 64),),
        (("quillan", "quillan", "quillan.cli:main"),),
        ("pds-core",),
    )


@pytest.fixture
def case() -> dict[str, Any]:
    predecessor = make_untrusted_active_receipt(
        _candidate("b" * 32, "old/one"),
        prepared_record=b"prior-p",
        registry_envelope=b"prior-r",
        lock_envelope=b"prior-l",
        native_envelope=b"prior-n",
        generation=1,
        recorded_at=NOW - timedelta(minutes=2),
        previous=None,
    )
    successor = make_untrusted_active_receipt(
        _candidate("c" * 32, "new/two"),
        prepared_record=b"next-p",
        registry_envelope=b"next-r",
        lock_envelope=b"next-l",
        native_envelope=b"next-n",
        generation=2,
        recorded_at=NOW - timedelta(minutes=1),
        previous=ExternallyPinnedReceiptHead(1, _sha(predecessor)),
    )
    request = WitnessCommitRequest(INSTALL, WITNESS, 1, predecessor, successor)
    state = WitnessWriterQuiescenceState(
        INSTALL,
        _sha(serialize_witness_commit_request(request)),
        "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED",
        2,
        _sha(successor),
    )
    signing = ed25519.Ed25519PrivateKey.generate()
    calls: list[str] = []

    def identify(fingerprint: str) -> object | None:
        calls.append("identify")
        return "trusted-client" if fingerprint == _sha(b"placeholder") else None

    def observe(
        item: WitnessCommitRequest, context: object
    ) -> WitnessWriterQuiescenceState:
        calls.append("observe")
        assert item == request and context == "trusted-client"
        return state

    def sign(message: bytes) -> bytes:
        calls.append("sign")
        return signing.sign(message)

    return {
        "request": request,
        "body": make_service_recovery_observation_request(request, challenge=CHALLENGE),
        "state": state,
        "signing": signing,
        "calls": calls,
        "identify": identify,
        "observe": observe,
        "sign": sign,
    }


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


@pytest.fixture
def tls(tmp_path: Path) -> dict[str, Any]:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PDS-test-CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=2))
        .not_valid_after(NOW + timedelta(days=100))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_file = tmp_path / "ca.pem"
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    material: dict[str, tuple[Path, Path, bytes]] = {}
    for label in ("server", "client"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(NOW - timedelta(days=2))
            .not_valid_after(NOW + timedelta(days=100))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        cert_file = tmp_path / f"{label}.pem"
        key_file = tmp_path / f"{label}.key"
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        _write_key(key_file, key)
        material[label] = (
            cert_file,
            key_file,
            cert.public_bytes(serialization.Encoding.DER),
        )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.verify_mode = ssl.CERT_REQUIRED
    server_context.load_cert_chain(
        str(material["server"][0]), str(material["server"][1])
    )
    server_context.load_verify_locations(cafile=str(ca_file))
    client_context = ssl.create_default_context(cafile=str(ca_file))
    client_context.load_cert_chain(
        str(material["client"][0]), str(material["client"][1])
    )
    bare_client = ssl.create_default_context(cafile=str(ca_file))
    return {
        "server": server_context,
        "client": client_context,
        "without_client_cert": bare_client,
        "client_der": material["client"][2],
    }


def _server(case: dict[str, Any], tls: dict[str, Any], **overrides: Any) -> Any:
    def policy(digest: str) -> object | None:
        case["calls"].append("identify")
        if digest == _sha(tls["client_der"]):
            return "trusted-client"
        return None

    options: dict[str, Any] = {
        "bind": ("127.0.0.1", 0),
        "tls_context": tls["server"],
        "identify_client": policy,
        "observe": case["observe"],
        "sign": case["sign"],
        "clock": lambda: NOW,
    }
    return create_recovery_observation_https_server(**{**options, **overrides})


def _request(
    port: int,
    client: ssl.SSLContext,
    *,
    method: str = "POST",
    route: str = ROUTE,
    body: bytes = b"x",
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, Any]:
    connection = http.client.HTTPSConnection(
        "localhost", port, context=client, timeout=3
    )
    try:
        values = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Length": str(len(body)),
        }
        if headers is not None:
            values.update(headers)
        connection.request(method, route, body=body, headers=values)
        result = connection.getresponse()
        return result.status, result.read(), result.headers
    finally:
        connection.close()


def test_real_mtls_response_verifies_signed_service_statement(
    case: dict[str, Any], tls: dict[str, Any]
) -> None:
    server = _server(case, tls)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        status, payload, headers = _request(
            server.server_port, tls["client"], body=case["body"]
        )
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert headers["Connection"] == "close"
        assert headers["Content-Length"] == str(len(payload))
        verified = verify_service_recovery_attestation(
            payload,
            request=case["request"],
            challenge=CHALLENGE,
            pinned_service_public_key=case["signing"]
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
            now=NOW,
        )
        assert verified.installation_id == INSTALL
        assert verified.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
        assert case["calls"] == ["identify", "observe", "sign"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_verified_tls_without_client_certificate_cannot_sign(
    case: dict[str, Any], tls: dict[str, Any]
) -> None:
    server = _server(case, tls)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        with pytest.raises((ssl.SSLError, OSError, http.client.RemoteDisconnected)):
            _request(server.server_port, tls["without_client_cert"], body=case["body"])
        assert case["calls"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "method,route,expected",
    [
        ("GET", ROUTE, 405),
        ("PUT", ROUTE, 405),
        ("DELETE", ROUTE, 405),
        ("OPTIONS", ROUTE, 405),
        ("PATCH", ROUTE, 405),
        ("TRACE", ROUTE, 405),
        ("POST", "/v1/receipt/head", 404),
        ("POST", ROUTE + "?debug=1", 404),
    ],
)
def test_no_other_method_or_route(
    case: dict[str, Any],
    tls: dict[str, Any],
    method: str,
    route: str,
    expected: int,
) -> None:
    server = _server(case, tls)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        status, _, headers = _request(
            server.server_port, tls["client"], method=method, route=route
        )
        assert status == expected
        assert headers["Cache-Control"] == "no-store"
        assert case["calls"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "bad",
    [
        {"Content-Length": "0003"},
        {"Content-Length": str(50 * 1024)},
        {"Transfer-Encoding": "chunked"},
        {"X-Client-Cert": "forged"},
        {"Accept": "*/*"},
        {"Content-Type": "text/plain"},
    ],
)
def test_invalid_http_framing_or_identity_never_signs(
    case: dict[str, Any], tls: dict[str, Any], bad: dict[str, str]
) -> None:
    server = _server(case, tls)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        status, _, _ = _request(
            server.server_port, tls["client"], body=case["body"], headers=bad
        )
        assert status in (400, 413, 415)
        assert case["calls"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "change",
    [
        {"tls_context": object()},
        {"bind": ("127.0.0.1", True)},
        {"bind": ("127.0.0.1", -1)},
        {"bind": ("", 0)},
        {"identify_client": None},
        {"observe": None},
        {"sign": None},
        {"clock": None},
    ],
)
def test_factory_rejects_unsafe_dependencies(
    case: dict[str, Any], tls: dict[str, Any], change: dict[str, Any]
) -> None:
    with pytest.raises(RecoveryObservationServerError):
        _server(case, tls, **change)


def test_factory_rejects_tls_without_mandatory_client_authentication(
    case: dict[str, Any], tls: dict[str, Any]
) -> None:
    insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    insecure.verify_mode = ssl.CERT_NONE
    with pytest.raises(RecoveryObservationServerError):
        _server(case, tls, tls_context=insecure)
    insecure.verify_mode = ssl.CERT_OPTIONAL
    with pytest.raises(RecoveryObservationServerError):
        _server(case, tls, tls_context=insecure)


def test_constructed_host_has_no_automatic_background_listener(
    case: dict[str, Any], tls: dict[str, Any]
) -> None:
    server = _server(case, tls)
    try:
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=1):
            pass
        assert case["calls"] == []
    finally:
        server.server_close()
