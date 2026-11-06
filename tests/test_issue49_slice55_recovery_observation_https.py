"""Slice 55: real mTLS client, pinned service signature, and bounded HTTP reply."""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_issue49_slice54_recovery_observation_server as previous
from cryptography.hazmat.primitives import serialization

import paper_data_suite.evergreen_recovery_observation_https as module
from paper_data_suite.evergreen_recovery_observation_https import (
    ProvisionedRecoveryObservationHttpsClient,
    RecoveryObservationHttpsError,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    issue_service_recovery_attestation,
)

NOW = datetime(2026, 10, 23, 19, tzinfo=UTC)
ORIGIN = "https://recovery.example.test"


@pytest.fixture
def ready(tmp_path: Path) -> dict[str, Any]:
    # The Slice-54 test fixture provisions actual certificate chains and a real
    # mTLS-capable host. Do not repeat, weaken or bypass certificate checking.
    tls = previous.tls.__wrapped__(tmp_path)
    case = previous.case.__wrapped__()
    ca = tmp_path / "ca.pem"
    service_key = (
        case["signing"]
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    options: dict[str, Any] = {
        "origin": ORIGIN,
        "ca_certificate": ca,
        "pinned_ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
        "client_certificate": tmp_path / "client.pem",
        "client_key": tmp_path / "client.key",
        "pinned_service_public_key": service_key,
        "timeout_seconds": 3.0,
    }
    return {"options": options, "tls": tls, "case": case, "tmp": tmp_path}


def _client(
    ready: dict[str, Any], **changes: Any
) -> ProvisionedRecoveryObservationHttpsClient:
    return ProvisionedRecoveryObservationHttpsClient(**{**ready["options"], **changes})


def _fetch_real(
    ready: dict[str, Any],
    *,
    client: ProvisionedRecoveryObservationHttpsClient | None = None,
) -> Any:
    server = previous._server(ready["case"], ready["tls"])
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        # This *test-only* redirection resolves the fixed test DNS origin to
        # localhost; the TLS certificate hostname is still verified by OpenSSL.
        with patch.object(
            module, "_endpoint", return_value=("localhost", server.server_port)
        ):
            return (client or _client(ready)).fetch(ready["case"]["request"], now=NOW)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_real_mtls_https_observation_is_signed_and_challenge_bound(
    ready: dict[str, Any],
) -> None:
    exchange = _fetch_real(ready)
    assert len(exchange.challenge) == 32
    assert exchange.signed_envelope.startswith(b"{")
    assert exchange.verified.installation_id == previous.INSTALL
    assert exchange.verified.transaction_id == "c" * 32
    assert exchange.verified.authority == "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
    assert exchange.status == "SIGNED_SERVICE_EXCHANGE_READ_ONLY"
    assert exchange.authority == "NO_LAUNCH_ROLLBACK_RECEIPT_OR_ACTIVATION_AUTHORITY"
    assert ready["case"]["calls"] == ["identify", "observe", "sign"]
    for operation in ("commit", "activate", "rollback", "launch", "cleanup"):
        assert not hasattr(exchange, operation)


def test_wrong_service_signing_key_refuses_after_real_tls(
    ready: dict[str, Any],
) -> None:
    bad = _client(ready, pinned_service_public_key=b"X" * 32)
    with pytest.raises(RecoveryObservationHttpsError, match="not trusted"):
        _fetch_real(ready, client=bad)
    assert ready["case"]["calls"] == ["identify", "observe", "sign"]


def test_tls_ca_digest_mismatch_refuses_before_network(ready: dict[str, Any]) -> None:
    bad = _client(ready, pinned_ca_sha256="0" * 64)
    with patch.object(
        module.http.client, "HTTPSConnection", side_effect=AssertionError("network")
    ):
        with pytest.raises(RecoveryObservationHttpsError, match="pin mismatch"):
            bad.fetch(ready["case"]["request"], now=NOW)


@pytest.mark.parametrize(
    "update",
    [
        {"origin": "http://recovery.example.test"},
        {"origin": "https://127.0.0.1"},
        {"origin": "https://user@recovery.example.test"},
        {"origin": "https://recovery.example.test/other"},
        {"origin": "https://recovery.example.test?next=1"},
        {"pinned_ca_sha256": "A" * 64},
        {"pinned_service_public_key": b"short"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 16.0},
        {"timeout_seconds": True},
        {"client_key": "not a Path"},
    ],
)
def test_invalid_provisioning_refuses(
    ready: dict[str, Any], update: dict[str, Any]
) -> None:
    with pytest.raises(RecoveryObservationHttpsError):
        _client(ready, **update)


@pytest.mark.parametrize(
    "now", [datetime(2026, 10, 23, 19), NOW.replace(microsecond=1)]
)
def test_bad_clock_refused_without_network(
    ready: dict[str, Any], now: datetime
) -> None:
    with patch.object(
        module.http.client, "HTTPSConnection", side_effect=AssertionError("network")
    ):
        with pytest.raises(RecoveryObservationHttpsError, match="whole-second"):
            _client(ready).fetch(ready["case"]["request"], now=now)


def test_missing_and_symlink_client_credentials_refuse_before_network(
    ready: dict[str, Any], tmp_path: Path
) -> None:
    missing = _client(ready, client_key=tmp_path / "missing.key")
    with patch.object(
        module.http.client, "HTTPSConnection", side_effect=AssertionError("network")
    ):
        with pytest.raises(RecoveryObservationHttpsError):
            missing.fetch(ready["case"]["request"], now=NOW)
    link = tmp_path / "linked-ca.pem"
    try:
        link.symlink_to(ready["options"]["ca_certificate"])
    except (OSError, NotImplementedError):
        pytest.skip("unprivileged symlink creation unavailable")
    with patch.object(
        module.http.client, "HTTPSConnection", side_effect=AssertionError("network")
    ):
        with pytest.raises(RecoveryObservationHttpsError):
            _client(ready, ca_certificate=link).fetch(ready["case"]["request"], now=NOW)


class FakeReply:
    def __init__(
        self, status: int, content: bytes, headers: list[tuple[str, str]]
    ) -> None:
        self.status = status
        self.content = content
        self.headers = headers

    def getheaders(self) -> list[tuple[str, str]]:
        return self.headers

    def read(self, maximum: int) -> bytes:
        return self.content[:maximum]


class FakeConnection:
    def __init__(self, reply_factory: Any, **kwargs: Any) -> None:
        self.factory = reply_factory
        self.kwargs = kwargs
        self.request_data: tuple[str, str, bytes, dict[str, str]] | None = None
        self.closed = False

    def request(
        self, method: str, route: str, body: bytes, headers: dict[str, str]
    ) -> None:
        self.request_data = (method, route, body, headers)

    def getresponse(self) -> FakeReply:
        assert self.request_data is not None
        return self.factory(self.request_data[2])

    def close(self) -> None:
        self.closed = True


def _simulate(
    ready: dict[str, Any],
    *,
    status: int = 200,
    changes: dict[str, list[str]] | None = None,
    altered: bytes | None = None,
    delta: timedelta = timedelta(0),
) -> tuple[FakeConnection, Any]:
    case = ready["case"]
    observed = case["state"]

    def reply(body: bytes) -> FakeReply:
        from paper_data_suite.evergreen_recovery_observation_http import _parse_request

        request, challenge = _parse_request(body)
        signed = issue_service_recovery_attestation(
            request,
            observed,
            challenge=challenge,
            observed_at=NOW + delta,
            sign=case["signing"].sign,
        )
        if altered is not None:
            signed = altered
        metadata = {
            "content-type": ["application/json"],
            "cache-control": ["no-store"],
            "connection": ["close"],
            "content-length": [str(len(signed))],
        }
        if changes:
            metadata.update(changes)
        return FakeReply(
            status,
            signed,
            [(key, item) for key, values in metadata.items() for item in values],
        )

    instance = FakeConnection(reply)
    with patch.object(module.http.client, "HTTPSConnection", return_value=instance):
        try:
            result: Any = _client(ready).fetch(case["request"], now=NOW)
        except RecoveryObservationHttpsError as error:
            result = error
    return instance, result


def test_one_post_no_redirect_no_proxy_and_connection_closed(
    ready: dict[str, Any],
) -> None:
    instance, result = _simulate(ready)
    assert not isinstance(result, BaseException)
    assert instance.closed
    assert instance.request_data is not None
    method, route, body, headers = instance.request_data
    assert (method, route) == ("POST", "/v1/recovery/service-observe")
    assert headers["Content-Length"] == str(len(body))
    assert headers["Connection"] == "close"
    assert instance.kwargs == {}  # Fake instance supplied directly by patch.


@pytest.mark.parametrize("code", [301, 302, 307, 308, 400, 403, 503])
def test_no_redirect_retry_or_error_response_acceptance(
    ready: dict[str, Any], code: int
) -> None:
    instance, error = _simulate(ready, status=code)
    assert isinstance(error, RecoveryObservationHttpsError)
    assert instance.closed


@pytest.mark.parametrize(
    "changes",
    [
        {"content-type": ["text/plain"]},
        {"content-type": ["application/json", "application/json"]},
        {"cache-control": []},
        {"cache-control": ["max-age=60"]},
        {"connection": ["keep-alive"]},
        {"transfer-encoding": ["chunked"]},
        {"content-encoding": ["gzip"]},
        {"content-length": []},
        {"content-length": ["0"]},
        {"content-length": ["8193"]},
        {"content-length": ["000100"]},
        {"content-length": ["4", "4"]},
    ],
)
def test_malformed_http_response_refuses(
    ready: dict[str, Any], changes: dict[str, list[str]]
) -> None:
    instance, error = _simulate(ready, changes=changes)
    assert isinstance(error, RecoveryObservationHttpsError)
    assert instance.closed


def test_bad_signature_and_mismatched_length_refuse(ready: dict[str, Any]) -> None:
    assert isinstance(
        _simulate(ready, altered=b"not signed")[1], RecoveryObservationHttpsError
    )
    assert isinstance(
        _simulate(ready, changes={"content-length": ["1"]})[1],
        RecoveryObservationHttpsError,
    )


def test_stale_signed_service_refuses(ready: dict[str, Any]) -> None:
    assert isinstance(
        _simulate(ready, delta=timedelta(seconds=-61))[1],
        RecoveryObservationHttpsError,
    )


def test_generator_is_internal_and_new_per_call(ready: dict[str, Any]) -> None:
    with patch.object(
        module.secrets, "token_bytes", side_effect=[b"A" * 32, b"B" * 32]
    ):
        first = _simulate(ready)[1]
        second = _simulate(ready)[1]
    assert first.challenge == b"A" * 32
    assert second.challenge == b"B" * 32
    assert first.signed_envelope != second.signed_envelope


def test_missing_randomness_refuses_without_request(ready: dict[str, Any]) -> None:
    with patch.object(module.secrets, "token_bytes", return_value=b"short"):
        with patch.object(
            module.http.client, "HTTPSConnection", side_effect=AssertionError("network")
        ):
            with pytest.raises(RecoveryObservationHttpsError, match="random"):
                _client(ready).fetch(ready["case"]["request"], now=NOW)
