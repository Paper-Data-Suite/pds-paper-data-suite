"""Issue #49 Slice 44: opt-in SERVICE-SIDE durable CAS attempt fencing.

Only an independently operated witness service may provision this ledger,
its authorizer and database. A pre-dispatch durable marker blocks automatic
retries even when an ACK is lost or the service crashes. A read of the prior
signed head is NEVER permission to rollback a potentially in-flight write.

No teacher CLI, production launcher, installed-software writes or witness HTTP
write route is added. A returned state is evidence of coordination ONLY.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_witness_commit_protocol import (
    IndependentCommitApproval,
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    commit_independently_approved_successor,
    inspect_uncertain_witness_commit,
    serialize_witness_commit_request,
)


class WitnessCasFenceError(ValueError):
    """Service-side durable CAS fencing or signed reconciliation was refused."""


class IndependentFenceAuthorizer(Protocol):
    """Independently provisioned service identity and operation authorization."""

    def __call__(
        self, installation_id: str, operation: str, context: object, /
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class WitnessCasFenceState:
    """Service-local observation, never a launch or rollback credential."""

    installation_id: str
    request_sha256: str
    predecessor_sha256: str
    successor_sha256: str
    expected_witness_revision: int
    status: str
    witnessed_revision: int | None = None
    witnessed_receipt_sha256: str | None = None
    authority: str = "NO_LAUNCH_OR_ROLLBACK_AUTHORITY"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS witness_cas_attempt_fences (
    installation_id TEXT PRIMARY KEY NOT NULL,
    request_sha256 TEXT NOT NULL,
    predecessor_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
       'PREPARED_NO_DISPATCH', 'CAS_MAY_HAVE_BEEN_DISPATCHED',
       'PRIOR_SIGNED_STILL_UNRESOLVED',
       'SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED'
    )),
    witnessed_revision INTEGER,
    witnessed_sha256 TEXT,
    CHECK ((witnessed_revision IS NULL) = (witnessed_sha256 IS NULL))
);
"""

_PREPARED = "PREPARED_NO_DISPATCH"
_MAY_HAVE_SENT = "CAS_MAY_HAVE_BEEN_DISPATCHED"
_PRIOR = "PRIOR_SIGNED_STILL_UNRESOLVED"
_SUCCESSOR = "SUCCESSOR_SIGNED_FORWARD_RECOVERY_REQUIRED"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class WitnessCasFenceLedger:
    """Independently operated SQLite attempt guard; caller supplies real isolation.

    The service MUST hold exclusive authority over the checkpoint writer, SQLite
    connection, service identity and deployment approval. This class cannot
    fence an unrelated process with direct access to MonotonicCheckpointStore.
    In particular, it never authorizes a rollback or launches an installation.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        authorize: IndependentFenceAuthorizer,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection) or not callable(authorize):
            raise WitnessCasFenceError("independent SQLite and authorizer required")
        if connection.in_transaction:
            raise WitnessCasFenceError("ledger connection already in a transaction")
        self._db = connection
        self._authorize = authorize
        try:
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
        except sqlite3.Error as error:
            raise WitnessCasFenceError("cannot initialize independent fence") from error

    def _permit(
        self, request: WitnessCommitRequest, operation: str, context: object
    ) -> None:
        try:
            permitted = self._authorize(request.installation_id, operation, context)
        except Exception as error:
            raise WitnessCasFenceError(
                "independent service authorization failed"
            ) from error
        if permitted is not True:
            raise WitnessCasFenceError("independent service authorization refused")

    def _identity(self, request: WitnessCommitRequest) -> tuple[str, str, str, int]:
        # The canonical serializer checks every receipt field and predecessor
        # link. A locally invented hash is not authenticated service approval.
        try:
            canonical = serialize_witness_commit_request(request)
        except WitnessCommitProtocolError as error:
            raise WitnessCasFenceError("invalid canonical witness request") from error
        return (
            _sha(canonical),
            request.predecessor_sha256,
            request.successor_sha256,
            request.expected_witness_revision,
        )

    def _read_locked(
        self, request: WitnessCommitRequest
    ) -> WitnessCasFenceState | None:
        row = self._db.execute(
            "SELECT request_sha256,predecessor_sha256,successor_sha256,"
            "expected_revision,state,witnessed_revision,witnessed_sha256 "
            "FROM witness_cas_attempt_fences WHERE installation_id=?",
            (request.installation_id,),
        ).fetchone()
        if row is None:
            return None
        expected = self._identity(request)
        if tuple(row[:4]) != expected:
            raise WitnessCasFenceError(
                "different or corrupt installation CAS reservation"
            )
        status = row[4]
        observed_rev, observed_hash = row[5], row[6]
        if (
            status not in (_PREPARED, _MAY_HAVE_SENT, _PRIOR, _SUCCESSOR)
            or (observed_rev is None) != (observed_hash is None)
            or (status in (_PREPARED, _MAY_HAVE_SENT) and observed_rev is not None)
            or (status in (_PRIOR, _SUCCESSOR) and observed_rev is None)
            or (
                status == _PRIOR
                and (observed_rev, observed_hash)
                != (request.expected_witness_revision, request.predecessor_sha256)
            )
            or (
                status == _SUCCESSOR
                and (observed_rev, observed_hash)
                != (
                    request.expected_witness_revision + 1,
                    request.successor_sha256,
                )
            )
        ):
            raise WitnessCasFenceError("corrupt or inconsistent fence record")
        return WitnessCasFenceState(
            request.installation_id,
            expected[0],
            expected[1],
            expected[2],
            expected[3],
            status,
            observed_rev,
            observed_hash,
        )

    def reserve(
        self, request: WitnessCommitRequest, *, service_context: object
    ) -> WitnessCasFenceState:
        """Durably reserve exact request; replay and other proposals are refused."""
        identity = self._identity(request)
        self._permit(request, "reserve", service_context)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            if self._read_locked(request) is not None:
                raise WitnessCasFenceError("witness CAS is already reserved")
            self._db.execute(
                "INSERT INTO witness_cas_attempt_fences VALUES (?,?,?,?,?,?,?,?)",
                (request.installation_id, *identity, _PREPARED, None, None),
            )
            self._db.execute("COMMIT")
        except Exception as error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(error, WitnessCasFenceError):
                raise
            raise WitnessCasFenceError("could not persist CAS reservation") from error
        return WitnessCasFenceState(
            request.installation_id,
            identity[0],
            identity[1],
            identity[2],
            identity[3],
            _PREPARED,
        )

    def _claim_once(
        self, request: WitnessCommitRequest, service_context: object
    ) -> WitnessCasFenceState:
        self._identity(request)
        self._permit(request, "dispatch", service_context)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            current = self._read_locked(request)
            if current is None or current.status != _PREPARED:
                raise WitnessCasFenceError(
                    "replay, missing reservation or CAS may be in flight"
                )
            updated = self._db.execute(
                "UPDATE witness_cas_attempt_fences SET state=? "
                "WHERE installation_id=? AND state=? AND request_sha256=?",
                (
                    _MAY_HAVE_SENT,
                    request.installation_id,
                    _PREPARED,
                    current.request_sha256,
                ),
            )
            if updated.rowcount != 1:
                raise WitnessCasFenceError("competing CAS attempt")
            self._db.execute("COMMIT")
        except Exception as error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(error, WitnessCasFenceError):
                raise
            raise WitnessCasFenceError(
                "could not persist possible CAS dispatch"
            ) from error
        identity = self._identity(request)
        return WitnessCasFenceState(
            request.installation_id,
            identity[0],
            identity[1],
            identity[2],
            identity[3],
            _MAY_HAVE_SENT,
        )

    def dispatch_once(
        self,
        request: WitnessCommitRequest,
        *,
        service_context: object,
        store: MonotonicCheckpointStore,
        independently_approve: IndependentCommitApproval,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> WitnessCasFenceState:
        """Persist possibly-sent state BEFORE invoking service CAS exactly once.

        Even if approval fails, the CAS raises, or the process stops, the
        attempt remains fenced and cannot be retried through this adapter.
        A successful return also remains unconfirmed until fresh signed readback.
        """
        if not isinstance(store, MonotonicCheckpointStore) or not callable(
            independently_approve
        ):
            raise WitnessCasFenceError("no separately administered CAS and approval")
        outcome = self._claim_once(request, service_context)
        try:
            commit_independently_approved_successor(
                request,
                store=store,
                service_context=service_context,
                independently_approve=independently_approve,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
            )
        except WitnessCommitProtocolError as error:
            raise WitnessCasFenceError(
                "CAS may have been sent; no retry or rollback without signed recovery"
            ) from error
        return outcome

    def inspect_signed_head(
        self,
        request: WitnessCommitRequest,
        *,
        service_context: object,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> WitnessCasFenceState:
        """Fresh signed readback, not a fence clearance or launch authorization.

        A prior head is STILL potentially in flight: never infer safe rollback.
        A successor head requires forward-only protected physical recovery.
        """
        self._permit(request, "inspect", service_context)
        initial = self._read_locked(request)
        if initial is None or initial.status == _PREPARED:
            raise WitnessCasFenceError("no CAS dispatch was durably recorded")
        try:
            observed = inspect_uncertain_witness_commit(
                request,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                minimum_witness_revision=request.expected_witness_revision,
            )
        except WitnessCommitProtocolError as error:
            raise WitnessCasFenceError(
                "signed witness head unavailable; possible CAS remains fenced"
            ) from error
        if observed.status == "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED":
            next_status = _SUCCESSOR
        elif observed.status == "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED":
            next_status = _PRIOR
        else:
            raise WitnessCasFenceError("unrecognized signed head")
        if initial.status == _SUCCESSOR and next_status != _SUCCESSOR:
            raise WitnessCasFenceError("witness head regressed from signed successor")
        try:
            self._db.execute("BEGIN IMMEDIATE")
            refreshed = self._read_locked(request)
            if refreshed != initial:
                raise WitnessCasFenceError("fence changed during remote signed read")
            self._db.execute(
                "UPDATE witness_cas_attempt_fences "
                "SET state=?,witnessed_revision=?,witnessed_sha256=? "
                "WHERE installation_id=? AND request_sha256=?",
                (
                    next_status,
                    observed.witness_revision,
                    observed.receipt_sha256,
                    request.installation_id,
                    initial.request_sha256,
                ),
            )
            self._db.execute("COMMIT")
        except Exception as error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(error, WitnessCasFenceError):
                raise
            raise WitnessCasFenceError(
                "could not persist signed head observation"
            ) from error
        identity = self._identity(request)
        return WitnessCasFenceState(
            request.installation_id,
            identity[0],
            identity[1],
            identity[2],
            identity[3],
            next_status,
            observed.witness_revision,
            observed.receipt_sha256,
        )

    def observe(
        self, request: WitnessCommitRequest, *, service_context: object
    ) -> WitnessCasFenceState | None:
        """Read service-owned state; local read is not signed remote evidence."""
        self._identity(request)
        self._permit(request, "observe", service_context)
        return self._read_locked(request)


__all__ = (
    "IndependentFenceAuthorizer",
    "WitnessCasFenceError",
    "WitnessCasFenceLedger",
    "WitnessCasFenceState",
)
