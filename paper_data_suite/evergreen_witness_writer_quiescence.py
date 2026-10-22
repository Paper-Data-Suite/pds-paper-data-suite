"""Issue #49 Slice 45: opt-in service-side writer-quiescence handoff.

This is a cooperating, independently administered CAS-writer gate. Closure
precedes a supervisor's stopped-writer check and a fresh signed head query.
It cannot itself stop processes, protect keys or authorize rollback/launch.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from paper_data_suite.evergreen_checkpoint_store import MonotonicCheckpointStore
from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_witness_cas_fence import (
    WitnessCasFenceError,
    WitnessCasFenceLedger,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    IndependentCommitApproval,
    WitnessCommitProtocolError,
    WitnessCommitRequest,
    inspect_uncertain_witness_commit,
    serialize_witness_commit_request,
)


class WitnessWriterQuiescenceError(ValueError):
    """The service cannot establish this bounded CAS-writer observation."""


class IndependentWriterSupervisor(Protocol):
    """Service-owned check AFTER admission is closed; no client assertions.

    Implementations must ensure every CAS writer is controlled, stopped and
    joined, and cannot dispatch again. A test callback returning True does NOT
    establish that operational property. No lease expiry is accepted as proof.
    """

    def __call__(
        self, installation_id: str, request_sha256: str, context: object, /
    ) -> bool: ...


class IndependentQuiescenceAuthorizer(Protocol):
    """Authenticate the service actor outside request/local receipt bytes."""

    def __call__(
        self, installation_id: str, operation: str, context: object, /
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class WitnessWriterQuiescenceState:
    """Coordination metadata only: never a clearance or execution credential."""

    installation_id: str
    request_sha256: str
    status: str
    signed_revision: int | None = None
    signed_head_sha256: str | None = None
    authority: str = "NO_ROLLBACK_LAUNCH_OR_ACTIVATION_AUTHORITY"


_ADMITTED = "ADMITTED_NOT_DISPATCHED"
_DISPATCHED = "CAS_MAY_BE_IN_FLIGHT"
_STOPPING = "STOP_REQUESTED_NO_DISPATCH"
_STOPPING_SENT = "STOP_REQUESTED_MAY_BE_IN_FLIGHT"
_STOPPED_PRIOR = "SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED"
_STOPPED_NEXT = "SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED"
_TERMINAL = (_STOPPED_PRIOR, _STOPPED_NEXT)
_STATES = (_ADMITTED, _DISPATCHED, _STOPPING, _STOPPING_SENT, *_TERMINAL)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS witness_writer_quiescence (
    installation_id TEXT PRIMARY KEY NOT NULL,
    request_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'ADMITTED_NOT_DISPATCHED', 'CAS_MAY_BE_IN_FLIGHT',
        'STOP_REQUESTED_NO_DISPATCH', 'STOP_REQUESTED_MAY_BE_IN_FLIGHT',
        'SERVICE_ASSERTED_STOPPED_PRIOR_SIGNED_UNRESOLVED',
        'SERVICE_ASSERTED_STOPPED_SUCCESSOR_SIGNED_FORWARD_REQUIRED'
    )),
    signed_revision INTEGER,
    signed_sha256 TEXT,
    CHECK ((signed_revision IS NULL) = (signed_sha256 IS NULL))
);
"""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class WitnessWriterQuiescenceGate:
    """One-shot admission/closure for the SAME service-owned Slice-44 ledger.

    Every real CAS writer for the installation MUST use this gate, and the
    independently configured supervisor MUST be able to terminate/join ALL
    writers, including work claimed before shutdown. Direct store or ledger
    use bypasses the barrier: this Python class cannot claim global isolation.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        ledger: WitnessCasFenceLedger,
        authorize: IndependentQuiescenceAuthorizer,
    ) -> None:
        if (
            not isinstance(connection, sqlite3.Connection)
            or not isinstance(ledger, WitnessCasFenceLedger)
            or ledger._db is not connection
            or not callable(authorize)
            or connection.in_transaction
        ):
            raise WitnessWriterQuiescenceError(
                "gate must share independently operated CAS-fence connection"
            )
        self._db = connection
        self._ledger = ledger
        self._authorize = authorize
        try:
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
        except sqlite3.Error as error:
            raise WitnessWriterQuiescenceError(
                "cannot initialize writer gate"
            ) from error

    def _identity(self, request: WitnessCommitRequest) -> str:
        try:
            return _sha(serialize_witness_commit_request(request))
        except WitnessCommitProtocolError as error:
            raise WitnessWriterQuiescenceError("invalid CAS request") from error

    def _permit(
        self, request: WitnessCommitRequest, operation: str, context: object
    ) -> None:
        try:
            allowed = self._authorize(request.installation_id, operation, context)
        except Exception as error:
            raise WitnessWriterQuiescenceError(
                "service authentication unavailable"
            ) from error
        if allowed is not True:
            raise WitnessWriterQuiescenceError("service operation unauthorized")

    def _read(
        self, request: WitnessCommitRequest
    ) -> WitnessWriterQuiescenceState | None:
        request_hash = self._identity(request)
        try:
            row = self._db.execute(
                "SELECT request_sha256,state,signed_revision,signed_sha256 "
                "FROM witness_writer_quiescence WHERE installation_id=?",
                (request.installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise WitnessWriterQuiescenceError("cannot inspect writer gate") from error
        if row is None:
            return None
        digest, state, revision, signed = row
        if (
            digest != request_hash
            or state not in _STATES
            or (revision is None) != (signed is None)
            or (state not in _TERMINAL and revision is not None)
            or (state in _TERMINAL and revision is None)
            or (
                state == _STOPPED_PRIOR
                and (revision, signed)
                != (request.expected_witness_revision, request.predecessor_sha256)
            )
            or (
                state == _STOPPED_NEXT
                and (revision, signed)
                != (request.expected_witness_revision + 1, request.successor_sha256)
            )
        ):
            raise WitnessWriterQuiescenceError("corrupt or competing writer gate")
        return WitnessWriterQuiescenceState(
            request.installation_id, request_hash, state, revision, signed
        )

    def _transition(
        self,
        request: WitnessCommitRequest,
        *,
        previous: WitnessWriterQuiescenceState,
        state: str,
        revision: int | None = None,
        digest: str | None = None,
    ) -> WitnessWriterQuiescenceState:
        """Database-serialized compare-and-set; never change another snapshot."""
        try:
            self._db.execute("BEGIN IMMEDIATE")
            if self._read(request) != previous:
                raise WitnessWriterQuiescenceError("writer gate changed concurrently")
            result = self._db.execute(
                "UPDATE witness_writer_quiescence "
                "SET state=?,signed_revision=?,signed_sha256=? "
                "WHERE installation_id=? AND request_sha256=? AND state=?",
                (
                    state,
                    revision,
                    digest,
                    request.installation_id,
                    previous.request_sha256,
                    previous.status,
                ),
            )
            if result.rowcount != 1:
                raise WitnessWriterQuiescenceError("writer gate CAS lost")
            self._db.execute("COMMIT")
        except Exception as error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(error, WitnessWriterQuiescenceError):
                raise
            raise WitnessWriterQuiescenceError(
                "writer gate was not persisted"
            ) from error
        return WitnessWriterQuiescenceState(
            request.installation_id, previous.request_sha256, state, revision, digest
        )

    def admit(
        self, request: WitnessCommitRequest, *, service_context: object
    ) -> WitnessWriterQuiescenceState:
        """One admission only, after Slice-44 reservation; no dispatch yet."""
        request_hash = self._identity(request)
        self._permit(request, "admit", service_context)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            if self._read(request) is not None:
                raise WitnessWriterQuiescenceError("writer already admitted or closed")
            reserved = self._ledger.observe(request, service_context=service_context)
            if reserved is None or reserved.status != "PREPARED_NO_DISPATCH":
                raise WitnessWriterQuiescenceError(
                    "matching fence reservation required"
                )
            self._db.execute(
                "INSERT INTO witness_writer_quiescence VALUES (?,?,?,?,?)",
                (request.installation_id, request_hash, _ADMITTED, None, None),
            )
            self._db.execute("COMMIT")
        except Exception as error:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(error, WitnessWriterQuiescenceError):
                raise
            raise WitnessWriterQuiescenceError(
                "writer admission not persisted"
            ) from error
        return WitnessWriterQuiescenceState(
            request.installation_id, request_hash, _ADMITTED
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
    ) -> WitnessWriterQuiescenceState:
        """Persist possibly-running BEFORE calling Slice-44 single dispatch.

        A crash, callback failure, or lost acknowledgment cannot reopen the
        gate or cause dispatch retry. Service supervisor must join this worker.
        """
        self._permit(request, "dispatch", service_context)
        before = self._read(request)
        if before is None or before.status != _ADMITTED:
            raise WitnessWriterQuiescenceError("writer not admitted or stop requested")
        running = self._transition(request, previous=before, state=_DISPATCHED)
        try:
            self._ledger.dispatch_once(
                request,
                service_context=service_context,
                store=store,
                independently_approve=independently_approve,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
            )
        except WitnessCasFenceError as error:
            raise WitnessWriterQuiescenceError(
                "possibly dispatched CAS remains permanently fenced"
            ) from error
        return running

    def request_stop(
        self, request: WitnessCommitRequest, *, service_context: object
    ) -> WitnessWriterQuiescenceState:
        """Durably close admission before independently stopping any writer."""
        self._permit(request, "stop", service_context)
        before = self._read(request)
        if before is None:
            raise WitnessWriterQuiescenceError("no service writer admission")
        if before.status in (_STOPPING, _STOPPING_SENT, *_TERMINAL):
            return before
        # A direct call to the older ledger might already have dispatched. Its
        # status must never be understated as "no dispatch" by this gate.
        destination = _STOPPING_SENT
        if before.status == _ADMITTED:
            try:
                underlying = self._ledger.observe(
                    request, service_context=service_context
                )
            except WitnessCasFenceError as error:
                raise WitnessWriterQuiescenceError(
                    "underlying CAS state is unknown"
                ) from error
            if underlying is not None and underlying.status == "PREPARED_NO_DISPATCH":
                destination = _STOPPING
        return self._transition(request, previous=before, state=destination)

    def certify_stopped_and_observe(
        self,
        request: WitnessCommitRequest,
        *,
        service_context: object,
        independently_verify_stopped: IndependentWriterSupervisor,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> WitnessWriterQuiescenceState:
        """Store service-asserted stop plus exact signed head; NEVER rollback.

        The independently administered callback must enforce real writer
        shutdown/join across all service instances. Here it is a supplied
        policy, not evidence that the operating system actually obeyed it.
        """
        self._permit(request, "certify", service_context)
        before = self._read(request)
        if before is None or before.status not in (_STOPPING, _STOPPING_SENT):
            raise WitnessWriterQuiescenceError(
                "stop request must precede certification"
            )
        if not callable(independently_verify_stopped):
            raise WitnessWriterQuiescenceError("missing independent writer supervisor")
        try:
            stopped = independently_verify_stopped(
                request.installation_id, before.request_sha256, service_context
            )
        except Exception as error:
            raise WitnessWriterQuiescenceError(
                "writer stop was not verified"
            ) from error
        if stopped is not True:
            raise WitnessWriterQuiescenceError("CAS writer may still be in flight")
        try:
            signed = inspect_uncertain_witness_commit(
                request,
                witness_transport=witness_transport,
                pinned_public_key=pinned_public_key,
                now=now,
                minimum_witness_revision=request.expected_witness_revision,
            )
        except WitnessCommitProtocolError as error:
            raise WitnessWriterQuiescenceError(
                "signed head unknown; stop request remains durable"
            ) from error
        if signed.status == "SUCCESSOR_HEAD_CONFIRMED_FORWARD_RECOVERY_REQUIRED":
            next_state = _STOPPED_NEXT
        elif signed.status == "PRIOR_HEAD_VISIBLE_COMMIT_STILL_UNRESOLVED":
            next_state = _STOPPED_PRIOR
        else:
            raise WitnessWriterQuiescenceError("unknown signed-head classification")
        return self._transition(
            request,
            previous=before,
            state=next_state,
            revision=signed.witness_revision,
            digest=signed.receipt_sha256,
        )

    def observe(
        self, request: WitnessCommitRequest, *, service_context: object
    ) -> WitnessWriterQuiescenceState | None:
        """Service-local history, not a substitute for fresh signed witness head."""
        self._permit(request, "observe", service_context)
        return self._read(request)


__all__ = (
    "IndependentQuiescenceAuthorizer",
    "IndependentWriterSupervisor",
    "WitnessWriterQuiescenceError",
    "WitnessWriterQuiescenceGate",
    "WitnessWriterQuiescenceState",
)
