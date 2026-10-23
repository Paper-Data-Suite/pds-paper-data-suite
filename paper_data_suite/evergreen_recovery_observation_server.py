"""Issue #49 Slice 54: opt-in mTLS host for read-only service observations.

No listener starts on import. An independent service must protect the gate,
writer supervisor, signing key, policy, TLS credentials and clock. This module
provides an HTTPS adapter, NOT activation or global CAS writer isolation.
"""

from __future__ import annotations

import http.server
import ssl
from collections.abc import Callable
from datetime import datetime
from typing import cast

from paper_data_suite.evergreen_recovery_observation_http import (
    ClientIdentityPolicy,
    RecoverySigner,
    ServiceRecoveryObservationHttpResult,
    ServiceStateObserver,
    handle_service_recovery_observation,
)


class RecoveryObservationServerError(ValueError):
    """The service observation host cannot safely be provisioned."""


Clock = Callable[[], datetime]
_ROUTE = "/v1/recovery/service-observe"
_MAX_BODY = 48 * 1024
_MAX_HEADERS = 32


def _refusal(status: int) -> ServiceRecoveryObservationHttpResult:
    messages = {
        400: b'{"error":"bad_request"}',
        401: b'{"error":"client_authentication_required"}',
        404: b'{"error":"not_found"}',
        405: b'{"error":"method_not_allowed"}',
        413: b'{"error":"payload_too_large"}',
        503: b'{"error":"service_unavailable"}',
    }
    return ServiceRecoveryObservationHttpResult(status, messages[status])


class _RecoveryObservationHost(http.server.HTTPServer):
    """Single-threaded to support a service-owned SQLite gate connection."""

    def __init__(
        self,
        bind: tuple[str, int],
        context: ssl.SSLContext,
        identify_client: ClientIdentityPolicy,
        observe: ServiceStateObserver,
        sign: RecoverySigner,
        clock: Clock,
    ) -> None:
        self._recovery_tls = context
        self.recovery_identify = identify_client
        self.recovery_observe = observe
        self.recovery_sign = sign
        self.recovery_clock = clock
        super().__init__(bind, _RecoveryHandler, bind_and_activate=False)
        try:
            self.server_bind()
            self.server_activate()
        except Exception:
            self.server_close()
            raise

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        raw, address = self.socket.accept()
        try:
            raw.settimeout(5.0)
            authenticated = self._recovery_tls.wrap_socket(
                raw, server_side=True, do_handshake_on_connect=True
            )
            if not isinstance(address, tuple) or len(address) != 2:
                authenticated.close()
                raise RecoveryObservationServerError("invalid TLS peer address")
            return authenticated, (str(address[0]), int(address[1]))
        except Exception:
            raw.close()
            raise


class _RecoveryHandler(http.server.BaseHTTPRequestHandler):
    server_version = "PDS-Recovery"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        """Never log recovery requests, certificate identities or signatures."""
        return

    def _send(self, result: ServiceRecoveryObservationHttpResult) -> None:
        self.close_connection = True
        self.send_response(result.status)
        self.send_header("Content-Type", result.content_type)
        self.send_header("Content-Length", str(len(result.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if result.status == 405:
            self.send_header("Allow", "POST")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(result.body)

    def handle_expect_100(self) -> bool:
        self._send(_refusal(400))
        return False

    def do_GET(self) -> None:
        self._send(_refusal(405))

    def do_HEAD(self) -> None:
        self._send(_refusal(405))

    def do_PUT(self) -> None:
        self._send(_refusal(405))

    def do_DELETE(self) -> None:
        self._send(_refusal(405))

    def do_OPTIONS(self) -> None:
        self._send(_refusal(405))

    def do_PATCH(self) -> None:
        self._send(_refusal(405))

    def do_TRACE(self) -> None:
        self._send(_refusal(405))

    def do_CONNECT(self) -> None:
        self._send(_refusal(405))

    def do_POST(self) -> None:
        if self.path != _ROUTE:
            self._send(_refusal(404))
            return
        host = self.server
        if not isinstance(host, _RecoveryObservationHost):
            self._send(_refusal(503))
            return
        if not isinstance(self.connection, ssl.SSLSocket):
            self._send(_refusal(401))
            return
        fields = self.headers.items()
        lengths = self.headers.get_all("Content-Length", [])
        if (
            len(fields) > _MAX_HEADERS
            or len(lengths) != 1
            or not lengths[0].isascii()
            or not lengths[0].isdecimal()
        ):
            self._send(_refusal(400))
            return
        if len(lengths[0]) > 6:
            self._send(_refusal(413))
            return
        length = int(lengths[0])
        if lengths[0] != str(length):
            self._send(_refusal(400))
            return
        if length > _MAX_BODY:
            self._send(_refusal(413))
            return
        if length < 1 or self.headers.get("Transfer-Encoding") is not None:
            self._send(_refusal(400))
            return
        try:
            peer_der = self.connection.getpeercert(binary_form=True)
            body = self.rfile.read(length)
            if len(body) != length:
                self._send(_refusal(400))
                return
            result = handle_service_recovery_observation(
                method="POST",
                target=self.path,
                headers=tuple(fields),
                body=body,
                peer_der=peer_der,
                identify_client=host.recovery_identify,
                observe=host.recovery_observe,
                sign=host.recovery_sign,
                now=host.recovery_clock(),
            )
        except Exception:
            self._send(_refusal(503))
            return
        self._send(result)


def create_recovery_observation_https_server(
    *,
    bind: tuple[str, int],
    tls_context: ssl.SSLContext,
    identify_client: ClientIdentityPolicy,
    observe: ServiceStateObserver,
    sign: RecoverySigner,
    clock: Clock,
) -> http.server.HTTPServer:
    """Construct but never start a separately operated mTLS-only read server.

    The caller MUST set up TLS server credentials, a trusted client CA,
    protected Ed25519 signing, a real service gate and supervisor, and
    independently administered authorization BEFORE constructing this host.
    A teacher-account process is not an independent service trust boundary.
    """
    if (
        not isinstance(tls_context, ssl.SSLContext)
        or tls_context.protocol != ssl.PROTOCOL_TLS_SERVER
        or tls_context.verify_mode != ssl.CERT_REQUIRED
        or tls_context.minimum_version < ssl.TLSVersion.TLSv1_2
        or type(bind) is not tuple
        or len(bind) != 2
        or type(bind[0]) is not str
        or not bind[0]
        or type(bind[1]) is not int
        or not 0 <= bind[1] <= 65535
        or not callable(identify_client)
        or not callable(observe)
        or not callable(sign)
        or not callable(clock)
    ):
        raise RecoveryObservationServerError("independent mTLS provisioning invalid")
    try:
        return cast(
            http.server.HTTPServer,
            _RecoveryObservationHost(
                bind, tls_context, identify_client, observe, sign, clock
            ),
        )
    except (OSError, ssl.SSLError, ValueError) as error:
        raise RecoveryObservationServerError(
            "could not bind separately provisioned recovery service"
        ) from error


__all__ = (
    "Clock",
    "RecoveryObservationServerError",
    "create_recovery_observation_https_server",
)
