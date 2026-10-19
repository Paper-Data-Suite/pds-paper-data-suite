"""Slice 35: independently pinned TLS transport, not a trusted deployment."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from paper_data_suite.evergreen_witness_https import (
    ProvisionedHttpsWitnessTransport,
    WitnessHttpsError,
)


class _Response:
    def __init__(
        self,
        *,
        status: int = 200,
        data: bytes = b'{"signed":"reply"}',
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.status = status
        self.data = data
        self.headers = (
            [("Content-Type", "application/json")] if headers is None else headers
        )

    def getheaders(self) -> list[tuple[str, str]]:
        return self.headers

    def read(self, count: int) -> bytes:
        return self.data[:count]


class _Connection:
    response: _Response = _Response()
    requests: list[tuple[str, str, bytes, dict[str, str]]] = []
    close_count: int = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def request(
        self, method: str, route: str, body: bytes, headers: dict[str, str]
    ) -> None:
        self.requests.append((method, route, body, headers))

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        type(self).close_count += 1


class _Context:
    minimum_version: object
    check_hostname: bool
    verify_mode: object
    anchor: str = ""
    client: tuple[str, str] = ("", "")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def load_verify_locations(self, *, cadata: str) -> None:
        self.anchor = cadata

    def load_cert_chain(self, *, certfile: str, keyfile: str) -> None:
        self.client = certfile, keyfile


@pytest.fixture
def transport(tmp_path: Path) -> ProvisionedHttpsWitnessTransport:
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n")
    client = tmp_path / "client.pem"
    client.write_text("client-cert")
    key = tmp_path / "client.key"
    key.write_text("client-private-key")
    return ProvisionedHttpsWitnessTransport(
        "https://witness.example.org",
        ca,
        hashlib.sha256(ca.read_bytes()).hexdigest(),
        client,
        key,
    )


def _mock_io() -> Any:
    return (
        patch("ssl.SSLContext", _Context),
        patch("http.client.HTTPSConnection", _Connection),
    )


def test_pinned_mutual_tls_post_has_no_proxy_redirect_or_extra_route(
    transport: ProvisionedHttpsWitnessTransport,
) -> None:
    _Connection.requests = []
    _Connection.close_count = 0
    _Connection.response = _Response()
    ssl_patch, connection_patch = _mock_io()
    with ssl_patch, connection_patch:
        assert transport(b"challenge") == b'{"signed":"reply"}'
    assert len(_Connection.requests) == 1
    method, route, body, headers = _Connection.requests[0]
    assert (method, route, body) == ("POST", "/v1/receipt/head", b"challenge")
    assert headers == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
    }
    assert _Connection.close_count == 1


@pytest.mark.parametrize(
    "origin",
    [
        "http://witness.example.org",
        "https://witness.example.org/path",
        "https://witness.example.org/?a=1",
        "https://user@witness.example.org",
        "https://witness.example.org#x",
        "https://localhost",
        "https://127.0.0.1",
        "https://witness.example.org:443",
        "https://witness.example.org/",
        "https://witness..example.org",
        "https://witness.example.org:",
        "https://witness.example.org:99999",
        "HTTPS://witness.example.org",
    ],
)
def test_reject_unsafe_origin(
    transport: ProvisionedHttpsWitnessTransport,
    origin: str,
) -> None:
    with pytest.raises(WitnessHttpsError, match="endpoint"):
        ProvisionedHttpsWitnessTransport(
            origin,
            transport.ca_certificate,
            transport.pinned_ca_sha256,
            transport.client_certificate,
            transport.client_key,
        )


def test_allow_fixed_nondefault_port(
    transport: ProvisionedHttpsWitnessTransport,
) -> None:
    candidate = ProvisionedHttpsWitnessTransport(
        "https://witness.example.org:8443",
        transport.ca_certificate,
        transport.pinned_ca_sha256,
        transport.client_certificate,
        transport.client_key,
    )
    ssl_patch, connection_patch = _mock_io()
    with ssl_patch, connection_patch:
        assert candidate(b"hello")


@pytest.mark.parametrize("challenge", [b"", b"a" * 1025, "not-bytes"])
def test_no_request_without_bounded_challenge(
    transport: ProvisionedHttpsWitnessTransport,
    challenge: Any,
) -> None:
    with patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
        with pytest.raises(WitnessHttpsError, match="challenge"):
            transport(challenge)


def test_corrupt_ca_fails_before_connect(
    transport: ProvisionedHttpsWitnessTransport,
) -> None:
    transport.ca_certificate.write_bytes(b"different CA")
    with patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
        with pytest.raises(WitnessHttpsError, match="hash mismatch"):
            transport(b"challenge")


def test_refuse_symlinked_ca(transport: ProvisionedHttpsWitnessTransport) -> None:
    ca = transport.ca_certificate
    original = ca.with_suffix(".old")
    ca.rename(original)
    try:
        ca.symlink_to(original)
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlinks unavailable")
    with patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
        with pytest.raises(WitnessHttpsError, match="unsafe"):
            transport(b"challenge")


@pytest.mark.parametrize("status", [201, 301, 302, 401, 404, 500])
def test_no_redirect_or_unexpected_status(
    transport: ProvisionedHttpsWitnessTransport,
    status: int,
) -> None:
    _Connection.response = _Response(status=status)
    ssl_patch, connection_patch = _mock_io()
    with ssl_patch, connection_patch:
        with pytest.raises(WitnessHttpsError, match="not successful"):
            transport(b"hello")


@pytest.mark.parametrize(
    "response",
    [
        _Response(data=b""),
        _Response(data=b"x" * 8193),
        _Response(headers=[]),
        _Response(headers=[("Content-Type", "text/html")]),
        _Response(headers=[("Content-Type", "application/json")] * 2),
    ],
)
def test_no_unbounded_or_nonjson_response(
    transport: ProvisionedHttpsWitnessTransport,
    response: _Response,
) -> None:
    _Connection.response = response
    ssl_patch, connection_patch = _mock_io()
    with ssl_patch, connection_patch:
        with pytest.raises(WitnessHttpsError, match="response"):
            transport(b"hello")


def test_bad_private_key_path_fails_before_connect(
    transport: ProvisionedHttpsWitnessTransport,
) -> None:
    transport.client_key.unlink()
    with patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
        with pytest.raises(WitnessHttpsError, match="unavailable mTLS"):
            transport(b"hello")


@pytest.mark.parametrize("timeout", [0, -1, 15.01, True, 100])
def test_bounded_timeout(
    transport: ProvisionedHttpsWitnessTransport,
    timeout: Any,
) -> None:
    with pytest.raises(WitnessHttpsError, match="settings"):
        ProvisionedHttpsWitnessTransport(
            transport.origin,
            transport.ca_certificate,
            transport.pinned_ca_sha256,
            transport.client_certificate,
            transport.client_key,
            timeout,
        )
