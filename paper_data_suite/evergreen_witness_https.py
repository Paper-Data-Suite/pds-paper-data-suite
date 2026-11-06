"""Issue #49 Slice 35: opt-in, pinned HTTPS transport for an external witness.

The service MUST be provisioned independently of the teacher's software tree.
TLS authenticates a network peer and mTLS authenticates a client credential;
neither establishes independent server storage, witnessed activation, or
permission to launch. No implicit network access, redirects, proxies or retry.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import ssl
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

_MAX_CHALLENGE: Final = 1024
_MAX_REPLY: Final = 8192
_MAX_CA: Final = 128 * 1024
_PIN: Final = re.compile(r"[0-9a-f]{64}\Z")
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_ROUTE: Final = "/v1/receipt/head"


class WitnessHttpsError(ValueError):
    """External witness TLS provisioning, request, or response is unsafe."""


def _endpoint(value: str) -> tuple[str, int]:
    if type(value) is not str or len(value) > 255:
        raise WitnessHttpsError("invalid witness HTTPS endpoint")
    try:
        parsed = urlsplit(value)
        port = parsed.port or 443
        host = parsed.hostname
    except ValueError as error:
        raise WitnessHttpsError("invalid witness HTTPS endpoint") from error
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "@" in parsed.netloc
        or parsed.netloc.endswith(":")
        or not 1 <= port <= 65535
        or len(host) > 253
        or len(host.split(".")) < 2
        or any(_LABEL.fullmatch(piece) is None for piece in host.split("."))
        or host.lower() != host
        or re.fullmatch(r"[0-9.]+", host) is not None
        or value != f"https://{host}" + (f":{port}" if port != 443 else "")
    ):
        raise WitnessHttpsError("witness endpoint must be a fixed HTTPS DNS origin")
    return host, port


def _file(path: Path, maximum: int | None, label: str) -> bytes | None:
    if not isinstance(path, Path):
        raise WitnessHttpsError(f"missing {label}")
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
        ):
            raise WitnessHttpsError(f"unsafe {label} path")
        if maximum is not None:
            if not 1 <= info.st_size <= maximum:
                raise WitnessHttpsError(f"invalid {label} size")
            with path.open("rb") as stream:
                data = stream.read(maximum + 1)
            if len(data) != info.st_size:
                raise WitnessHttpsError(f"changed {label} while reading")
            return data
        if info.st_size < 1:
            raise WitnessHttpsError(f"empty {label}")
    except OSError as error:
        raise WitnessHttpsError(f"unavailable {label}") from error
    return None


@dataclass(frozen=True, slots=True)
class ProvisionedHttpsWitnessTransport:
    """Callable for ``query_checkpoint_witness``. Opt-in network only.

    A locally supplied config or a writable certificate file is NOT proof of
    independent provisioning. The caller must obtain the trust-anchor hash,
    client identity, and service deployment approval from an external authority.
    Server MUST authenticate the client and protect SQLite/key under another
    OS account/host. This object never makes such a deployment assertion.
    """

    origin: str
    ca_certificate: Path
    pinned_ca_sha256: str
    client_certificate: Path
    client_key: Path
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        _endpoint(self.origin)
        if (
            type(self.pinned_ca_sha256) is not str
            or _PIN.fullmatch(self.pinned_ca_sha256) is None
            or type(self.timeout_seconds) not in (float, int)
            or not 0 < self.timeout_seconds <= 15
            or any(
                not isinstance(value, Path)
                for value in (
                    self.ca_certificate,
                    self.client_certificate,
                    self.client_key,
                )
            )
        ):
            raise WitnessHttpsError("invalid independent witness transport settings")

    def __call__(self, challenge: bytes) -> bytes:
        """POST exactly one fresh challenge, with no proxy, redirects or retry."""
        if type(challenge) is not bytes or not 1 <= len(challenge) <= _MAX_CHALLENGE:
            raise WitnessHttpsError("invalid witness challenge size")
        host, port = _endpoint(self.origin)
        anchor = _file(self.ca_certificate, _MAX_CA, "TLS trust anchor")
        assert anchor is not None
        if hashlib.sha256(anchor).hexdigest() != self.pinned_ca_sha256:
            raise WitnessHttpsError("independent TLS trust anchor hash mismatch")
        _file(self.client_certificate, None, "mTLS certificate")
        _file(self.client_key, None, "mTLS private key")
        try:
            ca_pem = anchor.decode("ascii")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(cadata=ca_pem)
            context.load_cert_chain(
                certfile=str(self.client_certificate), keyfile=str(self.client_key)
            )
        except (OSError, ValueError, UnicodeDecodeError, ssl.SSLError) as error:
            raise WitnessHttpsError("invalid provisioned TLS credentials") from error
        connection = http.client.HTTPSConnection(
            host, port=port, timeout=float(self.timeout_seconds), context=context
        )
        try:
            connection.request(
                "POST",
                _ROUTE,
                body=challenge,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise WitnessHttpsError("witness response is not successful")
            content_types = [
                value.strip().lower()
                for key, value in response.getheaders()
                if key.lower() == "content-type"
            ]
            if content_types != ["application/json"]:
                raise WitnessHttpsError("unexpected witness response media type")
            contents = response.read(_MAX_REPLY + 1)
            if type(contents) is not bytes or not 1 <= len(contents) <= _MAX_REPLY:
                raise WitnessHttpsError("oversized or empty witness response")
            return contents
        except WitnessHttpsError:
            raise
        except (OSError, TimeoutError, ValueError, http.client.HTTPException) as error:
            raise WitnessHttpsError("checkpoint witness unavailable") from error
        finally:
            connection.close()


__all__ = ("ProvisionedHttpsWitnessTransport", "WitnessHttpsError")
