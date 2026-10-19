"""Issue #49 Slice 34: transactional checkpoint witness service *building block*.

Host this with independent OS/service credentials, independently protected
SQLite storage, client authentication, and private-key custody.  Importing this
module into Suite, or putting its database beside the teacher installation,
DOES NOT make a checkpoint trustworthy. No launch or activation authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final, Protocol, cast

from paper_data_suite.evergreen_active_receipts import (
    ActiveReceiptError,
    UntrustedActiveReceipt,
    parse_untrusted_active_receipt,
)

_MAX_CHALLENGE: Final = 1024
_MAX_STATEMENT: Final = 4096
_INSTALL: Final = re.compile(r"[0-9a-f]{32}\Z")
_WITNESS: Final = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
_HEX: Final = re.compile(r"[0-9a-f]{64}\Z")
_TIME: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_MAX_GENERATION: Final = 2**53 - 1


class CheckpointStoreError(ValueError):
    """Storage, authorization, compare-and-swap, or witness protocol refused."""


class CheckpointAuthorizer(Protocol):
    """Service-supplied authentication/authorization, never client assertion."""

    def __call__(
        self, installation_id: str, operation: str, context: object, /
    ) -> bool: ...


class CheckpointSigner(Protocol):
    """Service-owned signer; the private key must not live in Suite."""

    def __call__(self, payload: bytes, /) -> bytes: ...


@dataclass(frozen=True, slots=True)
class CommittedCheckpoint:
    """Witness-local CAS result; not a trusted Suite receipt/launch token."""

    installation_id: str
    revision: int
    generation: int
    receipt_sha256: str
    previous_sha256: str | None


def _unique(rows: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in rows:
        if name in result:
            raise CheckpointStoreError("duplicate witness challenge key")
        result[name] = value
    return result


def _canonical(document: dict[str, object]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise CheckpointStoreError(f"invalid {label}")
    return value


def _instant(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CheckpointStoreError("invalid witness clock")
    current = now.astimezone(timezone.utc)
    if current.microsecond:
        raise CheckpointStoreError("witness clock must have whole seconds")
    return current


def _timestamp(value: object) -> datetime:
    raw = _identifier(value, _TIME, "challenge timestamp")
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise CheckpointStoreError("invalid challenge timestamp") from error


def _time_string(value: datetime) -> str:
    return _instant(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _challenge(raw: bytes, now: datetime) -> tuple[str, str]:
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_CHALLENGE:
        raise CheckpointStoreError("witness challenge size invalid")
    try:
        parsed: object = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except CheckpointStoreError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise CheckpointStoreError("invalid witness challenge encoding") from error
    if not isinstance(parsed, dict):
        raise CheckpointStoreError("challenge must be object")
    data = cast(dict[str, object], parsed)
    if _canonical(data) != raw or data.keys() != {
        "record_type",
        "schema_version",
        "installation_id",
        "issued_at",
        "nonce_b64",
    }:
        raise CheckpointStoreError("noncanonical or unexpected challenge fields")
    if (
        data["record_type"] != "pds_external_checkpoint_challenge"
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise CheckpointStoreError("wrong witness challenge schema")
    installation_id = _identifier(data["installation_id"], _INSTALL, "installation")
    nonce_b64 = data["nonce_b64"]
    if type(nonce_b64) is not str:
        raise CheckpointStoreError("invalid challenge nonce")
    try:
        nonce = base64.b64decode(nonce_b64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise CheckpointStoreError("invalid challenge nonce") from error
    if len(nonce) != 32 or base64.b64encode(nonce).decode("ascii") != nonce_b64:
        raise CheckpointStoreError("noncanonical challenge nonce")
    issued_at = _timestamp(data["issued_at"])
    if not timedelta(0) <= _instant(now) - issued_at <= timedelta(seconds=120):
        raise CheckpointStoreError("stale or future challenge")
    return installation_id, hashlib.sha256(nonce).hexdigest()


_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS witness_heads (
    installation_id TEXT PRIMARY KEY NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    receipt_sha256 TEXT NOT NULL,
    previous_generation INTEGER,
    previous_sha256 TEXT,
    CHECK ((previous_generation IS NULL) = (previous_sha256 IS NULL))
);
CREATE TABLE IF NOT EXISTS issued_challenges (
    installation_id TEXT NOT NULL,
    nonce_sha256 TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    PRIMARY KEY (installation_id, nonce_sha256)
);
"""


class MonotonicCheckpointStore:
    """Server-side SQLite CAS and signing; requires independent deployment.

    Supply a service-exclusive SQLite connection configured for durable writes.
    SQL transaction locks serialize competing writers, including across processes.
    No filesystem path, caller-supplied signing key, or local activation authority
    is accepted here. The host must retain secure control of its DB and signer.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        witness_id: str,
        authorize: CheckpointAuthorizer,
        sign: CheckpointSigner,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise CheckpointStoreError("externally provisioned SQLite required")
        self.witness_id = _identifier(witness_id, _WITNESS, "witness ID")
        if not callable(authorize) or not callable(sign):
            raise CheckpointStoreError("missing independent authentication or signer")
        self._conn = connection
        self._authorize = authorize
        self._sign = sign
        try:
            # The connection must be dedicated to this service, in autocommit
            # mode; FULL does not protect against hostile DB file replacement.
            if self._conn.in_transaction:
                raise CheckpointStoreError("connection already inside a transaction")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as error:
            raise CheckpointStoreError(
                "witness database initialization failed"
            ) from error

    def _permit(self, installation_id: str, operation: str, context: object) -> None:
        try:
            result = self._authorize(installation_id, operation, context)
        except Exception as error:
            raise CheckpointStoreError(
                "independent client authorization failed"
            ) from error
        if result is not True:
            raise CheckpointStoreError("operation denied by service authenticator")

    @staticmethod
    def _parse_receipt(
        installation_id: str, receipt_bytes: bytes
    ) -> tuple[UntrustedActiveReceipt, str]:
        try:
            parsed = parse_untrusted_active_receipt(receipt_bytes)
        except ActiveReceiptError as error:
            raise CheckpointStoreError("noncanonical receipt rejected") from error
        digest = hashlib.sha256(receipt_bytes).hexdigest()
        _identifier(installation_id, _INSTALL, "installation")
        return parsed, digest

    @staticmethod
    def _row(row: tuple[object, ...] | None) -> CommittedCheckpoint | None:
        if row is None:
            return None
        installation, revision, generation, digest, prev_gen, prev_sha = row
        if (
            type(installation) is not str
            or type(revision) is not int
            or type(generation) is not int
            or type(digest) is not str
            or not _HEX.fullmatch(digest)
            or not 1 <= revision <= _MAX_GENERATION
            or not 1 <= generation <= _MAX_GENERATION
            or (
                (generation == 1 and (prev_gen is not None or prev_sha is not None))
                or (
                    generation > 1
                    and (type(prev_gen) is not int or prev_gen != generation - 1)
                )
            )
        ):
            raise CheckpointStoreError("corrupt checkpoint state")
        if prev_sha is not None and (
            type(prev_sha) is not str or not _HEX.fullmatch(prev_sha)
        ):
            raise CheckpointStoreError("corrupt checkpoint predecessor")
        return CommittedCheckpoint(installation, revision, generation, digest, prev_sha)

    def commit_receipt(
        self,
        installation_id: str,
        receipt_bytes: bytes,
        *,
        context: object,
    ) -> CommittedCheckpoint:
        """Admin-authorized genesis or strict successor CAS, durably recorded.

        Caller MUST independently verify publisher/native/pip evidence and
        authenticate a consented activation before calling. This CAS alone
        authenticates neither the candidate nor installed state.
        """
        installation = _identifier(installation_id, _INSTALL, "installation")
        parsed, digest = self._parse_receipt(installation, receipt_bytes)
        self._permit(installation, "commit", context)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT installation_id,revision,generation,receipt_sha256,"
                "previous_generation,previous_sha256 FROM witness_heads "
                "WHERE installation_id = ?",
                (installation,),
            ).fetchone()
            existing = self._row(row)
            if existing is None:
                if parsed.generation != 1 or parsed.previous_receipt_sha256 is not None:
                    raise CheckpointStoreError("genesis must start at generation one")
                # Genesis must be separately approved by the service operator.
                self._permit(installation, "enroll", context)
                self._conn.execute(
                    "INSERT INTO witness_heads VALUES (?,?,?,?,?,?)",
                    (installation, 1, 1, digest, None, None),
                )
                revision = 1
            else:
                if (
                    existing.generation >= _MAX_GENERATION
                    or existing.revision >= _MAX_GENERATION
                    or parsed.generation != existing.generation + 1
                    or parsed.previous_receipt_sha256 != existing.receipt_sha256
                ):
                    raise CheckpointStoreError("receipt CAS predecessor mismatch")
                revision = existing.revision + 1
                cursor = self._conn.execute(
                    "UPDATE witness_heads SET revision=?, generation=?, "
                    "receipt_sha256=?, previous_generation=?, previous_sha256=? "
                    "WHERE installation_id=? AND revision=? AND receipt_sha256=?",
                    (
                        revision,
                        parsed.generation,
                        digest,
                        existing.generation,
                        existing.receipt_sha256,
                        installation,
                        existing.revision,
                        existing.receipt_sha256,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CheckpointStoreError("racing checkpoint update")
            self._conn.execute("COMMIT")
        except Exception as error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            if isinstance(error, CheckpointStoreError):
                raise
            raise CheckpointStoreError("checkpoint write did not commit") from error
        return CommittedCheckpoint(
            installation,
            revision,
            parsed.generation,
            digest,
            parsed.previous_receipt_sha256,
        )

    def answer_challenge(
        self, challenge_bytes: bytes, *, context: object, now: datetime
    ) -> bytes:
        """Read a checkpoint and emit a fresh Slice-33-compatible signed reply.

        Read-only from Suite's perspective. No network API is implemented here.
        A replayed nonce is rejected by the independent witness database.
        """
        clock = _instant(now)
        installation, nonce_sha = _challenge(challenge_bytes, clock)
        self._permit(installation, "read", context)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            # A challenge issued before this retention window is already stale.
            self._conn.execute(
                "DELETE FROM issued_challenges WHERE issued_at < ?",
                (_time_string(clock - timedelta(seconds=300)),),
            )
            if (
                self._conn.execute(
                    "SELECT 1 FROM issued_challenges WHERE installation_id=? "
                    "AND nonce_sha256=?",
                    (installation, nonce_sha),
                ).fetchone()
                is not None
            ):
                raise CheckpointStoreError("replayed witness challenge")
            row = self._conn.execute(
                "SELECT installation_id,revision,generation,receipt_sha256,"
                "previous_generation,previous_sha256 FROM witness_heads "
                "WHERE installation_id=?",
                (installation,),
            ).fetchone()
            checkpoint = self._row(row)
            if checkpoint is None:
                raise CheckpointStoreError("unknown witness installation")
            self._conn.execute(
                "INSERT INTO issued_challenges VALUES (?,?,?)",
                (installation, nonce_sha, _time_string(clock)),
            )
            self._conn.execute("COMMIT")
        except Exception as error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            if isinstance(error, CheckpointStoreError):
                raise
            raise CheckpointStoreError("failed to read durable checkpoint") from error
        data: dict[str, object] = {
            "record_type": "pds_external_checkpoint_statement",
            "schema_version": 1,
            "witness_id": self.witness_id,
            "installation_id": installation,
            "challenge_sha256": hashlib.sha256(challenge_bytes).hexdigest(),
            "witness_revision": checkpoint.revision,
            "head_generation": checkpoint.generation,
            "head_sha256": checkpoint.receipt_sha256,
            "predecessor_generation": (
                checkpoint.generation - 1 if checkpoint.previous_sha256 else None
            ),
            "predecessor_sha256": checkpoint.previous_sha256,
            "issued_at": _time_string(clock),
            "expires_at": _time_string(clock + timedelta(seconds=60)),
        }
        payload = _canonical(data)
        if len(payload) > _MAX_STATEMENT:
            raise CheckpointStoreError("checkpoint response too large")
        try:
            signature = self._sign(payload)
        except Exception as error:
            raise CheckpointStoreError("witness signer unavailable") from error
        if type(signature) is not bytes or len(signature) != 64:
            raise CheckpointStoreError("invalid external signing result")
        return _canonical(
            {
                "payload_b64": base64.b64encode(payload).decode("ascii"),
                "signature_b64": base64.b64encode(signature).decode("ascii"),
            }
        )


__all__ = (
    "CheckpointAuthorizer",
    "CheckpointSigner",
    "CheckpointStoreError",
    "CommittedCheckpoint",
    "MonotonicCheckpointStore",
)
