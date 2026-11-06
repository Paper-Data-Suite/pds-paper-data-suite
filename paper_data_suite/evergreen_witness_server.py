"""Issue #49 Slice 36: opt-in mTLS-only witness head-read HTTP endpoint.

An independently operated service must supply the TLS server credentials,
client CA, certificate policy, signer and protected SQLite database. No server
is started by importing this module or by a Suite CLI command. The service
never exposes write/enrollment endpoints or grants launch authority.
"""

from __future__ import annotations

import hashlib
import http.server
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from paper_data_suite.evergreen_checkpoint_store import (
    CheckpointStoreError,
    MonotonicCheckpointStore,
)

_MAX_BODY: Final = 1024
_MAX_FINGERPRINT: Final = re.compile(r"[0-9a-f]{64}\Z")
_ROUTE: Final = "/v1/receipt/head"


class WitnessServerError(ValueError):
    """TLS server or verified-client authentication is not provisioned safely."""


# The service maps the SHA-256 DER fingerprint of a *verified TLS peer* to a
# service-owned authorization context. It must never read a claimed fingerprint
# from a request header, query parameter, or request JSON.
ClientPolicy = Callable[[str], object | None]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class WitnessHttpResult:
    status: int
    body: bytes
    content_type: str = "application/json"


def _error(status: int) -> WitnessHttpResult:
    # No exception details or database contents leave the independent service.
    labels = {
        400: b'{"error":"bad_request"}',
        401: b'{"error":"client_authentication_required"}',
        403: b'{"error":"forbidden"}',
        404: b'{"error":"not_found"}',
        405: b'{"error":"method_not_allowed"}',
        413: b'{"error":"payload_too_large"}',
        415: b'{"error":"unsupported_media_type"}',
        503: b'{"error":"witness_unavailable"}',
    }
    return WitnessHttpResult(status, labels[status])


def handle_witness_head(
    *,
    method: str,
    target: str,
    headers: tuple[tuple[str, str], ...],
    body: bytes,
    peer_der: bytes | None,
    identify_client: ClientPolicy,
    store: MonotonicCheckpointStore,
    now: datetime,
) -> WitnessHttpResult:
    """One HTTP request over a previously *verified* mTLS socket.

    The caller must obtain peer_der ONLY from SSLSocket.getpeercert(True)
    after TLS authenticates the peer. Supplying caller-created DER or a forged
    ClientPolicy result does not establish an independently protected service.
    """
    if method != "POST":
        return _error(405)
    if target != _ROUTE:
        return _error(404)
    if type(body) is not bytes:
        return _error(400)
    if len(body) > _MAX_BODY:
        return _error(413)
    if not body:
        return _error(400)
    if type(headers) is not tuple or len(headers) > 32:
        return _error(400)
    observed: dict[str, str] = {}
    for pair in headers:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
            or len(pair[0]) > 64
            or len(pair[1]) > 256
        ):
            return _error(400)
        key, value = pair
        key = key.lower()
        if key in observed or any(ord(char) < 33 or ord(char) > 126 for char in key):
            return _error(400)
        observed[key] = value
    # Explicitly forbid client-identity assertions and ambiguous HTTP framing.
    if any(
        name.startswith(("x-forwarded-", "x-ssl-", "x-client-"))
        or name in ("transfer-encoding", "forwarded", "proxy-authorization")
        for name in observed
    ):
        return _error(400)
    if observed.get("content-type") != "application/json":
        return _error(415)
    if observed.get("accept") != "application/json":
        return _error(400)
    size = observed.get("content-length")
    if (
        size is None
        or not size.isascii()
        or not size.isdecimal()
        or str(len(body)) != size
    ):
        return _error(400)
    if type(peer_der) is not bytes or not peer_der or len(peer_der) > 64 * 1024:
        return _error(401)
    fingerprint = hashlib.sha256(peer_der).hexdigest()
    if _MAX_FINGERPRINT.fullmatch(fingerprint) is None:
        return _error(401)
    try:
        context = identify_client(fingerprint)
    except Exception:
        return _error(503)
    if context is None:
        return _error(403)
    if not isinstance(now, datetime) or now.tzinfo is None:
        return _error(503)
    try:
        result = store.answer_challenge(
            body,
            context=context,
            now=now.astimezone(timezone.utc).replace(microsecond=0),
        )
    except CheckpointStoreError:
        return _error(403)
    except Exception:
        return _error(503)
    if type(result) is not bytes or not 1 <= len(result) <= 8192:
        return _error(503)
    return WitnessHttpResult(200, result)


class _WitnessHttpServer(http.server.HTTPServer):
    """Single-threaded to respect dedicated SQLite connection ownership."""

    def __init__(
        self,
        address: tuple[str, int],
        context: ssl.SSLContext,
        store: MonotonicCheckpointStore,
        identify_client: ClientPolicy,
        clock: Clock,
    ) -> None:
        self.witness_store = store
        self.witness_policy = identify_client
        self.witness_clock = clock
        self._witness_tls = context
        super().__init__(address, _WitnessHandler, bind_and_activate=False)
        try:
            # Bind a plain listening socket, but wrap EVERY accepted socket
            # before the HTTP handler sees it. Setting a timeout BEFORE the
            # handshake prevents one unauthenticated peer from blocking this
            # single-threaded, SQLite-bound service indefinitely.
            self.server_bind()
            self.server_activate()
        except Exception:
            self.server_close()
            raise

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        raw, address = self.socket.accept()
        try:
            raw.settimeout(5.0)
            authenticated = self._witness_tls.wrap_socket(
                raw, server_side=True, do_handshake_on_connect=True
            )
            if not isinstance(address, tuple) or len(address) != 2:
                raise WitnessServerError("unsupported witness peer address")
            return authenticated, (str(address[0]), int(address[1]))
        except Exception:
            raw.close()
            raise


class _WitnessHandler(http.server.BaseHTTPRequestHandler):
    server_version = "PDS-Witness"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # Deliberately do not log challenge bytes, identities or caller headers.
        return

    def _send(self, result: WitnessHttpResult) -> None:
        self.close_connection = True
        self.send_response(result.status)
        self.send_header("Content-Type", result.content_type)
        self.send_header("Content-Length", str(len(result.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if result.status == 405:
            self.send_header("Allow", "POST")
        self.end_headers()
        self.wfile.write(result.body)

    def do_GET(self) -> None:
        self._send(_error(405))

    def do_HEAD(self) -> None:
        self._send(_error(405))

    def do_PUT(self) -> None:
        self._send(_error(405))

    def do_DELETE(self) -> None:
        self._send(_error(405))

    def do_POST(self) -> None:
        server = self.server
        if not isinstance(server, _WitnessHttpServer):
            self._send(_error(503))
            return
        if self.path != _ROUTE:
            self._send(_error(404))
            return
        if not isinstance(self.connection, ssl.SSLSocket):
            self._send(_error(401))
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            self._send(_error(400))
            return
        length = int(lengths[0])
        if length < 1 or length > _MAX_BODY:
            self._send(_error(413 if length > _MAX_BODY else 400))
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._send(_error(400))
            return
        try:
            peer = self.connection.getpeercert(binary_form=True)
            body = self.rfile.read(length)
            if len(body) != length:
                self._send(_error(400))
                return
            response = handle_witness_head(
                method="POST",
                target=self.path,
                headers=tuple(self.headers.items()),
                body=body,
                peer_der=peer,
                identify_client=server.witness_policy,
                store=server.witness_store,
                now=server.witness_clock(),
            )
        except Exception:
            self._send(_error(503))
            return
        self._send(response)


def create_witness_https_server(
    *,
    bind: tuple[str, int],
    tls_context: ssl.SSLContext,
    store: MonotonicCheckpointStore,
    identify_client: ClientPolicy,
    clock: Clock,
) -> http.server.HTTPServer:
    """Explicitly build, but do not start serving, an mTLS-only read endpoint.

    Production MUST run this in a separately administered service account/host
    with protected SQLite, TLS and witness signing key. Binding inside the
    teacher's login never establishes independence. The factory accepts an
    already-provisioned TLS server context; it does not load private keys.
    """
    if (
        not isinstance(tls_context, ssl.SSLContext)
        or tls_context.protocol != ssl.PROTOCOL_TLS_SERVER
        or tls_context.verify_mode != ssl.CERT_REQUIRED
        or tls_context.minimum_version < ssl.TLSVersion.TLSv1_2
        or not isinstance(store, MonotonicCheckpointStore)
        or not callable(identify_client)
        or not callable(clock)
        or type(bind) is not tuple
        or len(bind) != 2
        or type(bind[0]) is not str
        or not bind[0]
        or type(bind[1]) is not int
        or not 0 <= bind[1] <= 65535
    ):
        raise WitnessServerError("independent mTLS server provisioning invalid")
    try:
        return _WitnessHttpServer(bind, tls_context, store, identify_client, clock)
    except (OSError, ssl.SSLError, ValueError) as error:
        raise WitnessServerError(
            "could not bind independently provisioned witness"
        ) from error


__all__ = (
    "ClientPolicy",
    "WitnessHttpResult",
    "WitnessServerError",
    "create_witness_https_server",
    "handle_witness_head",
)
