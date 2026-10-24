"""Issue #49 Slice 55: independently pinned recovery-observation HTTPS client.

This opt-in, one-shot mTLS reader obtains a fresh challenge-bound signed service
statement. The exchange is evidence for further read-only recovery inspection,
not rollback, activation, receipt-commit, or launch authority. It does not
provision the remote service, its CA, key, supervisor or durable writer gate.
"""

from __future__ import annotations

import hashlib
import http.client
import secrets
import ssl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paper_data_suite.evergreen_recovery_observation_http import (
    ServiceRecoveryObservationHttpError,
    make_service_recovery_observation_request,
)
from paper_data_suite.evergreen_service_recovery_attestation import (
    RecoveryServiceAttestationError,
    VerifiedRecoveryServiceAttestation,
    verify_service_recovery_attestation,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest
from paper_data_suite.evergreen_witness_https import (
    WitnessHttpsError,
    _endpoint,
    _file,
)

_ROUTE = "/v1/recovery/service-observe"
_MAX_REPLY = 8192
_MAX_CA = 128 * 1024


class RecoveryObservationHttpsError(ValueError):
    """Cannot obtain an authenticated and bounded service observation."""


@dataclass(frozen=True, slots=True)
class SignedRecoveryServiceExchange:
    """Ephemeral transport bytes for Slice-52 inspection; never a clearance."""

    challenge: bytes
    signed_envelope: bytes
    verified: VerifiedRecoveryServiceAttestation
    status: str = "SIGNED_SERVICE_EXCHANGE_READ_ONLY"
    authority: str = "NO_LAUNCH_ROLLBACK_RECEIPT_OR_ACTIVATION_AUTHORITY"


@dataclass(frozen=True, slots=True)
class ProvisionedRecoveryObservationHttpsClient:
    """One-shot mTLS service reader with independent CA and Ed25519 key pins.

    The deployer MUST provision CA/certificate/key and service key independently
    of teacher-writable software state. Local files cannot establish service
    independence. A genuine signer still only attests a service observation.
    """

    origin: str
    ca_certificate: Path
    pinned_ca_sha256: str
    client_certificate: Path
    client_key: Path
    pinned_service_public_key: bytes
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        try:
            _endpoint(self.origin)
        except WitnessHttpsError as error:
            raise RecoveryObservationHttpsError(
                "invalid fixed recovery HTTPS origin"
            ) from error
        if (
            type(self.pinned_ca_sha256) is not str
            or len(self.pinned_ca_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.pinned_ca_sha256
            )
            or type(self.pinned_service_public_key) is not bytes
            or len(self.pinned_service_public_key) != 32
            or type(self.timeout_seconds) not in (int, float)
            or not 0 < self.timeout_seconds <= 15
            or any(
                not isinstance(path, Path)
                for path in (
                    self.ca_certificate,
                    self.client_certificate,
                    self.client_key,
                )
            )
        ):
            raise RecoveryObservationHttpsError(
                "invalid independently provisioned service trust configuration"
            )

    def fetch(
        self, request: WitnessCommitRequest, *, now: datetime
    ) -> SignedRecoveryServiceExchange:
        """Generate a fresh challenge, perform one verified POST, never retry.

        Returns signed transport evidence usable by Slice 52, which MUST still
        recheck the signed witness head and installed candidate bytes. This
        routine never calls a witness CAS endpoint or changes local state.
        """
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
        ):
            raise RecoveryObservationHttpsError("aware whole-second clock required")
        try:
            challenge = secrets.token_bytes(32)
            if type(challenge) is not bytes or len(challenge) != 32:
                raise RecoveryObservationHttpsError("random challenge unavailable")
            body = make_service_recovery_observation_request(
                request, challenge=challenge
            )
            host, port = _endpoint(self.origin)
            anchor = _file(self.ca_certificate, _MAX_CA, "TLS trust anchor")
            assert anchor is not None
            if hashlib.sha256(anchor).hexdigest() != self.pinned_ca_sha256:
                raise RecoveryObservationHttpsError("TLS trust anchor pin mismatch")
            _file(self.client_certificate, None, "mTLS certificate")
            _file(self.client_key, None, "mTLS private key")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(cadata=anchor.decode("ascii"))
            context.load_cert_chain(
                certfile=str(self.client_certificate), keyfile=str(self.client_key)
            )
        except (WitnessHttpsError, ServiceRecoveryObservationHttpError) as error:
            raise RecoveryObservationHttpsError(
                "service request or provisioned TLS material refused"
            ) from error
        except RecoveryObservationHttpsError:
            raise
        except (OSError, ValueError, UnicodeDecodeError, ssl.SSLError) as error:
            raise RecoveryObservationHttpsError(
                "invalid recovery TLS credentials or challenge"
            ) from error

        connection = http.client.HTTPSConnection(
            host, port=port, timeout=float(self.timeout_seconds), context=context
        )
        try:
            connection.request(
                "POST",
                _ROUTE,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Content-Length": str(len(body)),
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise RecoveryObservationHttpsError(
                    "recovery service returned no authenticated observation"
                )
            headers: dict[str, list[str]] = {}
            for name, value in response.getheaders():
                headers.setdefault(name.lower(), []).append(value)
            if (
                headers.get("content-type") != ["application/json"]
                or headers.get("cache-control") != ["no-store"]
                or headers.get("connection") != ["close"]
                or "transfer-encoding" in headers
                or "content-encoding" in headers
                or len(headers.get("content-length", [])) != 1
            ):
                raise RecoveryObservationHttpsError(
                    "untrusted, ambiguous or cacheable service HTTP response"
                )
            size_text = headers["content-length"][0]
            if (
                not size_text.isascii()
                or not size_text.isdecimal()
                or len(size_text) > 4
                or not 1 <= int(size_text) <= _MAX_REPLY
                or str(int(size_text)) != size_text
            ):
                raise RecoveryObservationHttpsError(
                    "invalid recovery observation response length"
                )
            signed = response.read(_MAX_REPLY + 1)
            if type(signed) is not bytes or len(signed) != int(size_text):
                raise RecoveryObservationHttpsError(
                    "incomplete or oversized signed service observation"
                )
            verified = verify_service_recovery_attestation(
                signed,
                request=request,
                challenge=challenge,
                pinned_service_public_key=self.pinned_service_public_key,
                now=now,
            )
            return SignedRecoveryServiceExchange(challenge, signed, verified)
        except RecoveryObservationHttpsError:
            raise
        except RecoveryServiceAttestationError as error:
            raise RecoveryObservationHttpsError(
                "signed service response is not trusted for this request"
            ) from error
        except (OSError, TimeoutError, ValueError, http.client.HTTPException) as error:
            raise RecoveryObservationHttpsError(
                "authenticated service observation unavailable"
            ) from error
        finally:
            connection.close()


__all__ = (
    "ProvisionedRecoveryObservationHttpsClient",
    "RecoveryObservationHttpsError",
    "SignedRecoveryServiceExchange",
)
