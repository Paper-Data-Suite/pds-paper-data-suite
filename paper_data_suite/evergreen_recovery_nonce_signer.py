"""Issue #49 Slice 57: durable, service-owned one-use recovery signer.

A strictly bounded Slice-50 service observation may be signed only once per
installation/challenge. A consumed nonce stays consumed if signing fails or
this service crashes. This is an independently provisioned service-side guard,
not authority to activate, rollback, dispatch witness CAS, or commit a receipt.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Final, cast


class RecoveryNonceSignerError(ValueError):
    """The service cannot durably reserve or sign this recovery observation."""


_DOMAIN: Final = b"pds-evergreen-service-recovery-observation-v1\x00"
_STATUS: Final = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
_AUTHORITY: Final = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"
_MAX_STATEMENT: Final = 4096
_MAX_SKEW_SECONDS: Final = 5
_RETENTION_SECONDS: Final = 24 * 60 * 60
_FIELDS: Final = frozenset(
    {
        "installation_id",
        "transaction_id",
        "request_sha256",
        "predecessor_sha256",
        "successor_sha256",
        "witness_id",
        "witness_revision",
        "successor_generation",
        "service_status",
        "authority",
        "issued_at",
        "expires_at",
        "challenge_b64",
    }
)
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS recovery_service_nonce_claims (
    installation_id TEXT NOT NULL,
    challenge_sha256 TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    observed_second INTEGER NOT NULL,
    statement_sha256 TEXT NOT NULL,
    PRIMARY KEY (installation_id, challenge_sha256)
);
CREATE TABLE IF NOT EXISTS recovery_service_nonce_clock (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    latest_second INTEGER NOT NULL
);
"""


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryNonceSignerError("duplicate service observation field")
        result[key] = value
    return result


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hex(value: object, size: int) -> bool:
    return (
        type(value) is str
        and len(value) == size
        and all(char in "0123456789abcdef" for char in value)
    )


def _witness_name(value: object) -> bool:
    return (
        type(value) is str
        and 3 <= len(value) <= 64
        and value[0] in "abcdefghijklmnopqrstuvwxyz"
        and all(char in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value)
    )


def _positive_revision(value: object) -> bool:
    return type(value) is int and 1 <= value < 2**53 - 1


def _statement(message: bytes) -> tuple[str, str, str, int]:
    """Reject anything other than the exact existing Slice-50 signing domain."""
    if (
        type(message) is not bytes
        or not message.startswith(_DOMAIN)
        or not 1 <= len(message) - len(_DOMAIN) <= _MAX_STATEMENT
    ):
        raise RecoveryNonceSignerError("not a bounded recovery signing statement")
    raw = message[len(_DOMAIN) :]
    try:
        value: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except RecoveryNonceSignerError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise RecoveryNonceSignerError("invalid signed service statement") from error
    if not isinstance(value, dict):
        raise RecoveryNonceSignerError("invalid signed service statement shape")
    statement = cast(dict[str, object], value)
    if (
        statement.keys() != _FIELDS
        or any(
            not _hex(statement.get(key), length)
            for key, length in (
                ("installation_id", 32),
                ("transaction_id", 32),
                ("request_sha256", 64),
                ("predecessor_sha256", 64),
                ("successor_sha256", 64),
            )
        )
        or not _witness_name(statement.get("witness_id"))
        or not _positive_revision(statement.get("witness_revision"))
        or not _positive_revision(statement.get("successor_generation"))
        or json.dumps(
            statement, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        != raw
        or statement["service_status"] != _STATUS
        or statement["authority"] != _AUTHORITY
        or type(statement["challenge_b64"]) is not str
        or type(statement["issued_at"]) is not str
        or type(statement["expires_at"]) is not str
    ):
        raise RecoveryNonceSignerError("unexpected service signing contract")
    try:
        challenge = base64.b64decode(statement["challenge_b64"], validate=True)
        issued = datetime.strptime(
            statement["issued_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        expires = datetime.strptime(
            statement["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
    except (binascii.Error, ValueError) as error:
        raise RecoveryNonceSignerError("invalid signed nonce or timestamps") from error
    if (
        len(challenge) != 32
        or base64.b64encode(challenge).decode("ascii") != statement["challenge_b64"]
        or issued.strftime("%Y-%m-%dT%H:%M:%SZ") != statement["issued_at"]
        or expires.strftime("%Y-%m-%dT%H:%M:%SZ") != statement["expires_at"]
        or int((expires - issued).total_seconds()) != 60
        or (expires - issued).total_seconds() != 60
    ):
        raise RecoveryNonceSignerError("noncanonical or expired signing window")
    return (
        cast(str, statement["installation_id"]),
        _sha(challenge),
        cast(str, statement["request_sha256"]),
        int(issued.timestamp()),
    )


def _clock_second(now: datetime) -> int:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise RecoveryNonceSignerError("service-owned whole-second clock required")
    return int(now.astimezone(timezone.utc).timestamp())


class DurableRecoveryNonceSigner:
    """Opt-in signer for the existing Slice-54 mTLS recovery service.

    The database must be a *protected, persistent, independently owned* SQLite
    connection, shared by all service signer instances/workers. The service
    administrator must enforce filesystem ownership and protect the signing
    callback and clock; Python cannot prove those deployment properties.

    The mark is committed before the signing callback. A failed sign burns the
    nonce deliberately: automatic retry is unsafe and must not be added.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        sign: Callable[[bytes], bytes],
        clock: Callable[[], datetime],
    ) -> None:
        if (
            not isinstance(connection, sqlite3.Connection)
            or connection.in_transaction
            or not callable(sign)
            or not callable(clock)
        ):
            raise RecoveryNonceSignerError("invalid service nonce signer dependencies")
        self._db = connection
        self._sign = sign
        self._clock = clock
        try:
            main = self._db.execute("PRAGMA database_list").fetchall()
            if not any(
                name == "main" and type(path) is str and path for _, name, path in main
            ):
                raise RecoveryNonceSignerError("persistent service database required")
            mode_row = self._db.execute("PRAGMA journal_mode").fetchone()
            if mode_row is None or mode_row[0] not in (
                "delete",
                "truncate",
                "persist",
                "wal",
            ):
                raise RecoveryNonceSignerError("durable SQLite journal mode required")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
        except sqlite3.Error as error:
            raise RecoveryNonceSignerError(
                "service replay ledger cannot initialize"
            ) from error

    def __call__(self, message: bytes) -> bytes:
        installation_id, challenge_hash, request_hash, issued_second = _statement(
            message
        )
        try:
            current = _clock_second(self._clock())
        except RecoveryNonceSignerError:
            raise
        except Exception as error:
            raise RecoveryNonceSignerError("service clock unavailable") from error
        if not 0 <= current - issued_second <= _MAX_SKEW_SECONDS:
            raise RecoveryNonceSignerError("service observation clock drift")
        try:
            # A database-serialized reservation is shared across processes.
            # Never release a consumed nonce because signing failed.
            self._db.execute("BEGIN IMMEDIATE")
            prior = self._db.execute(
                "SELECT latest_second FROM recovery_service_nonce_clock "
                "WHERE singleton=1"
            ).fetchone()
            if prior is not None and current < prior[0]:
                raise RecoveryNonceSignerError("service clock moved backward")
            self._db.execute(
                "INSERT INTO recovery_service_nonce_claims VALUES (?,?,?,?,?)",
                (
                    installation_id,
                    challenge_hash,
                    request_hash,
                    current,
                    _sha(message),
                ),
            )
            # Expired observations cannot verify again. Retain an additional
            # day as bounded operational defense, without deleting fresh rows.
            self._db.execute(
                "DELETE FROM recovery_service_nonce_claims WHERE observed_second < ?",
                (current - _RETENTION_SECONDS,),
            )
            self._db.execute(
                "INSERT INTO recovery_service_nonce_clock(singleton, latest_second) "
                "VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET "
                "latest_second=excluded.latest_second",
                (current,),
            )
            self._db.execute("COMMIT")
        except Exception as error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(error, RecoveryNonceSignerError):
                raise
            if isinstance(error, sqlite3.IntegrityError):
                raise RecoveryNonceSignerError(
                    "service nonce already consumed"
                ) from error
            raise RecoveryNonceSignerError(
                "cannot durably reserve service nonce"
            ) from error
        try:
            signature = self._sign(message)
        except Exception as error:
            raise RecoveryNonceSignerError(
                "service signer failed; nonce consumed"
            ) from error
        if type(signature) is not bytes or len(signature) != 64:
            raise RecoveryNonceSignerError("invalid service signature; nonce consumed")
        return signature


__all__ = ("DurableRecoveryNonceSigner", "RecoveryNonceSignerError")
