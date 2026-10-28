"""Issue #49 Slice 83: one-shot, independently operated local receipt dispatch.

A durable service-side dispatch claim is committed BEFORE invoking an externally
administered file writer exactly once. Lost acknowledgments, process crashes,
readback disagreements and all other uncertainty forbid any automatic retry.
No path is accepted from an untrusted request; the protected service owns its
pinned target, exclusive OS locks, file handles and durable replacement method.
The library itself does not provide privileged Windows filesystem custody.
Never clear a recovery capsule, mark installation active, or launch here.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final, Protocol

from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_finalization_fence import (
    IndependentFinalizationReader,
    PlanFinalizationFenceError,
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    LocalDeploymentIntentError,
    ProtectedLocalDeploymentIntent,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    IndependentLocalReceiptReader,
    LocalPrewriteUncertaintyError,
    ProtectedLocalPrewriteUncertainty,
    ProtectedLocalPrewriteUncertaintyLedger,
    _intent_hash,
    _readback_matches,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedPlanReceiptError,
    ProtectedServiceReceiptRecord,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    PlanPublicationPreclaimError,
    ProtectedPublicationPreclaim,
    _fresh_basis_matches,
)
from paper_data_suite.evergreen_witness_commit_protocol import (
    WitnessCommitRequest,
)

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_STATUS: Final = "LOCAL_RECEIPT_DISPATCH_CLAIMED_WRITE_OUTCOME_UNCERTAIN"
_AUTHORITY: Final = "NO_REDISPATCH_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_ARMED: Final = "LOCAL_PREWRITE_UNCERTAINTY_ARMED_NO_WRITER_DISPATCH"
_ARMED_AUTH: Final = "NO_RETRY_WRITE_CAPSULE_CLEAR_LAUNCH_SWITCH_ROLLBACK_OR_CAS"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_local_receipt_dispatch_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    predecessor_receipt_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    prewrite_marker_sha256 TEXT NOT NULL,
    recovery_capsule_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LOCAL_RECEIPT_DISPATCH_CLAIMED_WRITE_OUTCOME_UNCERTAIN'
    )
)
"""


class LocalReceiptDispatchError(ValueError):
    """Refuse changed inputs, duplicate dispatch or indeterminate file outcomes."""


class IndependentReceiptFileWriter(Protocol):
    """Privileged service-only writer, NEVER an untrusted client callback.

    The service must hold the SAME exclusive process/OS locks across its
    independent preflight, durable claim, write and readback. It must use a
    service-pinned destination, reject reparse links and unsafe parent paths,
    compare the predecessor *at the handle*, durably stage exact successor
    bytes, fsync/FlushFileBuffers, safely replace using platform primitives,
    and preserve the separate pending recovery capsule. This protocol alone
    cannot enforce these properties or authenticate callback provenance.
    """

    def __call__(
        self,
        request: WitnessCommitRequest,
        target_identity_sha256: str,
        service_context: object,
        /,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProtectedLocalReceiptDispatchClaim:
    """Durable once-per-installation possibility of a dispatched file write."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    predecessor_receipt_sha256: str
    target_identity_sha256: str
    prewrite_marker_sha256: str
    recovery_capsule_sha256: str
    status: str = _STATUS
    authority: str = _AUTHORITY


@dataclass(frozen=True, slots=True)
class LocalReceiptDispatchReadback:
    """Diagnostic only; success still requires independent convergence later."""

    installation_id: str
    transaction_id: str
    successor_sha256: str
    status: str = "LOCAL_SUCCESSOR_VISIBLE_CAPSULE_RETAINED_RECOVERY_REQUIRED"
    authority: str = _AUTHORITY


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _marker_hash(marker: ProtectedLocalPrewriteUncertainty) -> str:
    import json

    return _sha(
        json.dumps(
            {f.name: getattr(marker, f.name) for f in fields(marker)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_marker(
    marker: ProtectedLocalPrewriteUncertainty,
    reservation: ProtectedFinalizationReservation,
    record: ProtectedServiceReceiptRecord,
    intent: ProtectedLocalDeploymentIntent,
    request: WitnessCommitRequest,
) -> bool:
    if not isinstance(marker, ProtectedLocalPrewriteUncertainty):
        return False
    for f in fields(marker):
        value = getattr(marker, f.name)
        kind = int if f.name in ("successor_generation", "witness_revision") else str
        if type(value) is not kind:
            return False
        if f.name.endswith("_sha256") and (
            not isinstance(value, str) or _SHA.fullmatch(value) is None
        ):
            return False
    return (
        marker.status == _ARMED
        and marker.authority == _ARMED_AUTH
        and marker.installation_id == request.installation_id
        and marker.transaction_id == reservation.transaction_id
        and marker.request_sha256 == reservation.request_sha256
        and marker.successor_sha256 == request.successor_sha256
        and marker.successor_generation == reservation.successor_generation
        and marker.witness_revision == reservation.witness_revision
        and marker.local_deployment_intent_sha256 == _intent_hash(intent)
        and marker.protected_receipt_record_sha256
        == intent.protected_receipt_record_sha256
        and marker.predecessor_receipt_sha256 == request.predecessor_sha256
        and marker.target_identity_sha256 == intent.target_identity_sha256
        and marker.recovery_capsule_sha256 == intent.recovery_capsule_sha256
        and marker.local_snapshot_sha256 == intent.local_snapshot_sha256
    )


class ProtectedLocalReceiptDispatcher:
    """Service-controlled, one-call dispatch; no retry, clear or launch API."""

    def __init__(self, prewrite: ProtectedLocalPrewriteUncertaintyLedger) -> None:
        if (
            not isinstance(prewrite, ProtectedLocalPrewriteUncertaintyLedger)
            or not isinstance(prewrite._db, sqlite3.Connection)
            or prewrite._db is not prewrite._planner._db
            or prewrite._db is not prewrite._planner._writer._db
            or prewrite._db.in_transaction
        ):
            raise LocalReceiptDispatchError("same protected service database required")
        self._prewrite = prewrite
        self._db = prewrite._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LocalReceiptDispatchError(
                "protected dispatch storage unavailable"
            ) from error

    def _authorize(self, install: str, op: str, context: object) -> None:
        try:
            self._prewrite._authorize(install, op, context)
        except LocalPrewriteUncertaintyError as error:
            raise LocalReceiptDispatchError(
                "independent dispatch authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLocalReceiptDispatchClaim | None:
        """Read-only, authorized durable inspection after uncertain outcomes."""
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LocalReceiptDispatchError("invalid installation identity")
        self._authorize(
            installation_id, "observe_local_receipt_dispatch", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_local_receipt_dispatch_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LocalReceiptDispatchError("dispatch claim unreadable") from error
        if row is None:
            return None
        try:
            item = ProtectedLocalReceiptDispatchClaim(*row)
        except (TypeError, ValueError) as error:
            raise LocalReceiptDispatchError("dispatch claim malformed") from error
        if (
            item.installation_id != installation_id
            or type(item.transaction_id) is not str
            or _TX.fullmatch(item.transaction_id) is None
            or any(
                type(getattr(item, f.name)) is not str
                or _SHA.fullmatch(getattr(item, f.name)) is None
                for f in fields(item)
                if f.name.endswith("_sha256")
            )
            or item.status != _STATUS
            or item.authority != _AUTHORITY
        ):
            raise LocalReceiptDispatchError("durable dispatch claim corrupt")
        return item

    def dispatch_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        *,
        service_context: object,
        independently_read_evidence: IndependentFinalizationReader,
        independently_read_local_receipt: IndependentLocalReceiptReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
        service_owned_write: IndependentReceiptFileWriter,
    ) -> LocalReceiptDispatchReadback:
        """Claim once BEFORE calling the external protected writer exactly once.

        A successful callback and readback is NOT local activation. Any
        exception, crash or disagreement is an *uncertain* operation and
        requires read-only independent reconciliation, NEVER another call.
        """
        request = self._prewrite._basis(
            request_bytes, reservation, preclaim, record, intent
        )
        if not _exact_marker(marker, reservation, record, intent, request):
            raise LocalReceiptDispatchError("invalid non-authorizing prewrite marker")
        self._prewrite._validate_runtime(
            independently_read_evidence=independently_read_evidence,
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
        )
        if (
            not callable(independently_read_local_receipt)
            or not callable(service_owned_write)
            or self._db.in_transaction
        ):
            raise LocalReceiptDispatchError("protected service inputs missing")
        self._authorize(
            request.installation_id, "dispatch_local_receipt_once", service_context
        )
        claim = ProtectedLocalReceiptDispatchClaim(
            request.installation_id,
            reservation.transaction_id,
            reservation.request_sha256,
            request.successor_sha256,
            request.predecessor_sha256,
            intent.target_identity_sha256,
            _marker_hash(marker),
            intent.recovery_capsule_sha256,
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._prewrite._durable_basis(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    service_context=service_context,
                )
                actual = self._prewrite.observe(
                    request.installation_id, service_context=service_context
                )
                if type(actual) is not type(marker) or actual != marker:
                    raise LocalReceiptDispatchError(
                        "durable prewrite uncertainty marker changed or absent"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_local_receipt_dispatch_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LocalReceiptDispatchError(
                        "dispatch already claimed; no repeat or automatic retry"
                    )
                try:
                    evidence = independently_read_evidence(request, service_context)
                    physical = independently_read_local_receipt(
                        request, service_context
                    )
                except Exception as error:
                    raise LocalReceiptDispatchError(
                        "independent pre-write physical read unavailable"
                    ) from error
                if (
                    not _fresh_basis_matches(evidence, reservation)
                    or not _readback_matches(physical, request, reservation, intent)
                    or physical.active_receipt_bytes != request.previous_receipt_bytes
                ):
                    raise LocalReceiptDispatchError(
                        "predecessor, candidate, target or pending capsule changed"
                    )
                self._prewrite._signed(
                    request, reservation, witness_transport, pinned_public_key, now
                )
                self._db.execute(
                    "INSERT INTO plan_local_receipt_dispatch_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        claim.installation_id,
                        claim.transaction_id,
                        claim.request_sha256,
                        claim.successor_sha256,
                        claim.predecessor_receipt_sha256,
                        claim.target_identity_sha256,
                        claim.prewrite_marker_sha256,
                        claim.recovery_capsule_sha256,
                        claim.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LocalReceiptDispatchError:
            raise
        except (
            sqlite3.Error,
            PlanFinalizationFenceError,
            PlanPublicationPreclaimError,
            ProtectedPlanReceiptError,
            LocalDeploymentIntentError,
            LocalPrewriteUncertaintyError,
        ) as error:
            raise LocalReceiptDispatchError(
                "dispatch COMMIT may be uncertain; read-only inspection required"
            ) from error
        # The claim is now durable; from this point there is NO automatic retry.
        # External service must keep a SINGLE protected filesystem critical
        # section across this call and all associated independent observations.
        try:
            service_owned_write(request, intent.target_identity_sha256, service_context)
        except Exception as error:
            raise LocalReceiptDispatchError(
                "local write outcome uncertain; no redispatch permitted"
            ) from error
        try:
            evidence = independently_read_evidence(request, service_context)
            physical = independently_read_local_receipt(request, service_context)
            self._prewrite._signed(
                request, reservation, witness_transport, pinned_public_key, now
            )
        except Exception as error:
            raise LocalReceiptDispatchError(
                "post-write verification unavailable; no redispatch permitted"
            ) from error
        if (
            not _fresh_basis_matches(evidence, reservation)
            or not _readback_matches(physical, request, reservation, intent)
            or physical.active_receipt_bytes != request.successor_receipt_bytes
        ):
            raise LocalReceiptDispatchError(
                "post-write receipt/capsule changed; protected reconciliation required"
            )
        return LocalReceiptDispatchReadback(
            request.installation_id,
            reservation.transaction_id,
            request.successor_sha256,
        )


__all__ = (
    "IndependentReceiptFileWriter",
    "LocalReceiptDispatchError",
    "LocalReceiptDispatchReadback",
    "ProtectedLocalReceiptDispatchClaim",
    "ProtectedLocalReceiptDispatcher",
)
