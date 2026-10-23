"""Issue #49 Slice 53: bounded opt-in service recovery HTTP request handler.

The host MUST authenticate mTLS, obtain peer DER from its verified socket,
protect service signer/state, and supply a real gate observer. This pure handler
neither starts a server nor grants CAS, rollback, activation or launch rights.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, cast

from paper_data_suite.evergreen_service_recovery_attestation import (
    RecoveryServiceAttestationError,
    issue_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    parse_witness_commit_request,
)
from paper_data_suite.evergreen_witness_writer_quiescence import (
    WitnessWriterQuiescenceError,
    WitnessWriterQuiescenceState,
)


class ServiceRecoveryObservationHttpError(ValueError):
    """An opt-in service recovery request is malformed or unsupported."""


class ServiceStateObserver(Protocol):
    """Injected *service-owned* gate observer; no caller-state deserialization.

    Production must delegate to ``WitnessWriterQuiescenceGate.observe`` after
    independent admission, authorizer and process-isolation checks.
    """

    def __call__(
        self, request: WitnessCommitRequest, context: object, /
    ) -> WitnessWriterQuiescenceState | None: ...


ClientIdentityPolicy = Callable[[str], object | None]
RecoverySigner = Callable[[bytes], bytes]


@dataclass(frozen=True, slots=True)
class ServiceRecoveryObservationHttpResult:
    """HTTP payload only: the host sets no-store and closes each response."""

    status: int
    body: bytes
    content_type: str = "application/json"


_ROUTE: Final = "/v1/recovery/service-observe"
_REQUEST_TYPE: Final = "pds_evergreen_service_recovery_read_request"
_MAX_BODY: Final = 48 * 1024
_MAX_REQUEST: Final = 32 * 1024
_MAX_PEER_CERT: Final = 64 * 1024
_MAX_HEADERS: Final = 32
_ERRORS: Final[dict[int, bytes]] = {
    400: b'{"error":"bad_request"}',
    401: b'{"error":"client_authentication_required"}',
    403: b'{"error":"forbidden"}',
    404: b'{"error":"not_found"}',
    405: b'{"error":"method_not_allowed"}',
    413: b'{"error":"payload_too_large"}',
    415: b'{"error":"unsupported_media_type"}',
    503: b'{"error":"service_unavailable"}',
}


def _error(status: int) -> ServiceRecoveryObservationHttpResult:
    return ServiceRecoveryObservationHttpResult(status, _ERRORS[status])


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for name, value in pairs:
        if name in obj:
            raise ServiceRecoveryObservationHttpError("duplicate member")
        obj[name] = value
    return obj


def _canonical(obj: dict[str, object]) -> bytes:
    return json.dumps(
        obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True
    ).encode("ascii")


def _decode(raw: object, limit: int) -> bytes:
    if type(raw) is not str or not 1 <= len(raw) <= 4 * ((limit + 2) // 3):
        raise ServiceRecoveryObservationHttpError("invalid base64 field")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ServiceRecoveryObservationHttpError("invalid base64 data") from error
    if (
        not 1 <= len(decoded) <= limit
        or base64.b64encode(decoded).decode("ascii") != raw
    ):
        raise ServiceRecoveryObservationHttpError("noncanonical base64 data")
    return decoded


def make_service_recovery_observation_request(
    request: WitnessCommitRequest, *, challenge: bytes
) -> bytes:
    """Serialize client transport bytes; THIS is not a trusted request."""
    from paper_data_suite.evergreen_witness_commit_protocol import (
        serialize_witness_commit_request,
    )

    if type(challenge) is not bytes or len(challenge) != 32:
        raise ServiceRecoveryObservationHttpError("32-byte challenge required")
    try:
        serialized = serialize_witness_commit_request(request)
    except WitnessCommitProtocolError as error:
        raise ServiceRecoveryObservationHttpError(
            "invalid witnessed request"
        ) from error
    if len(serialized) > _MAX_REQUEST:
        raise ServiceRecoveryObservationHttpError("witness request too large")
    body = _canonical(
        {
            "record_type": _REQUEST_TYPE,
            "schema_version": 1,
            "challenge_b64": base64.b64encode(challenge).decode("ascii"),
            "witness_request_b64": base64.b64encode(serialized).decode("ascii"),
        }
    )
    if not 1 <= len(body) <= _MAX_BODY:
        raise ServiceRecoveryObservationHttpError("request body too large")
    return body


def _parse_request(raw: bytes) -> tuple[WitnessCommitRequest, bytes]:
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_BODY:
        raise ServiceRecoveryObservationHttpError("request size invalid")
    try:
        parsed: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except ServiceRecoveryObservationHttpError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ServiceRecoveryObservationHttpError("malformed JSON") from error
    if not isinstance(parsed, dict):
        raise ServiceRecoveryObservationHttpError("not an object")
    document = cast(dict[str, object], parsed)
    if (
        document.keys()
        != {
            "record_type",
            "schema_version",
            "challenge_b64",
            "witness_request_b64",
        }
        or document["record_type"] != _REQUEST_TYPE
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
        or _canonical(document) != raw
    ):
        raise ServiceRecoveryObservationHttpError("noncanonical request schema")
    nonce = _decode(document["challenge_b64"], 32)
    if len(nonce) != 32:
        raise ServiceRecoveryObservationHttpError("wrong challenge size")
    witness_bytes = _decode(document["witness_request_b64"], _MAX_REQUEST)
    try:
        request = parse_witness_commit_request(witness_bytes)
    except WitnessCommitProtocolError as error:
        raise ServiceRecoveryObservationHttpError("invalid witness proposal") from error
    return request, nonce


def _headers_valid(
    headers: tuple[tuple[str, str], ...], body: bytes
) -> tuple[int | None, dict[str, str]]:
    if type(headers) is not tuple or len(headers) > _MAX_HEADERS:
        return 400, {}
    fields: dict[str, str] = {}
    for header in headers:
        if (
            type(header) is not tuple
            or len(header) != 2
            or type(header[0]) is not str
            or type(header[1]) is not str
            or not 1 <= len(header[0]) <= 64
            or len(header[1]) > 256
        ):
            return 400, {}
        key, value = header
        name = key.lower()
        if (
            not all("!" <= char <= "~" for char in key)
            or name in fields
            or name.startswith(("x-forwarded-", "x-ssl-", "x-client-"))
            or name in ("forwarded", "transfer-encoding", "proxy-authorization")
        ):
            return 400, {}
        fields[name] = value
    if fields.get("content-type") != "application/json":
        return 415, fields
    if fields.get("accept") != "application/json":
        return 400, fields
    size = fields.get("content-length")
    if size is None or not size.isascii() or not size.isdecimal():
        return 400, fields
    if size != str(len(body)):
        return 400, fields
    return None, fields


def handle_service_recovery_observation(
    *,
    method: str,
    target: str,
    headers: tuple[tuple[str, str], ...],
    body: bytes,
    peer_der: bytes | None,
    identify_client: ClientIdentityPolicy,
    observe: ServiceStateObserver,
    sign: RecoverySigner,
    now: datetime,
) -> ServiceRecoveryObservationHttpResult:
    """Respond only to a verified-mTLS caller with a signed *observation*.

    The host MUST take ``peer_der`` from its authenticated TLS socket, not an
    HTTP field, and protect its service gate, DB and Ed25519 signer. The signer
    signs no raw request bytes: only the domain-separated Slice-50 statement.
    No witness write, package action, or local recovery cleanup occurs here.
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
    status, _ = _headers_valid(headers, body)
    if status is not None:
        return _error(status)
    if type(peer_der) is not bytes or not 1 <= len(peer_der) <= _MAX_PEER_CERT:
        return _error(401)
    if not callable(identify_client) or not callable(observe) or not callable(sign):
        return _error(503)
    try:
        context = identify_client(hashlib.sha256(peer_der).hexdigest())
    except Exception:
        return _error(503)
    if context is None:
        return _error(403)
    try:
        request, challenge = _parse_request(body)
    except ServiceRecoveryObservationHttpError:
        return _error(400)
    try:
        state = observe(request, context)
    except WitnessWriterQuiescenceError:
        return _error(403)
    except Exception:
        return _error(503)
    if state is None:
        return _error(403)
    try:
        result = issue_service_recovery_attestation(
            request, state, challenge=challenge, observed_at=now, sign=sign
        )
    except RecoveryServiceAttestationError:
        return _error(503)
    except Exception:
        return _error(503)
    if type(result) is not bytes or not 1 <= len(result) <= 8192:
        return _error(503)
    return ServiceRecoveryObservationHttpResult(200, result)


__all__ = (
    "ClientIdentityPolicy",
    "RecoverySigner",
    "ServiceRecoveryObservationHttpError",
    "ServiceRecoveryObservationHttpResult",
    "ServiceStateObserver",
    "handle_service_recovery_observation",
    "make_service_recovery_observation_request",
)
