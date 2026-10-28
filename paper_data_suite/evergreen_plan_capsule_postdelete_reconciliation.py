"""Issue #49 Slice 88: independently reconcile uncertain capsule deletion.

No deletion is performed or redispatched here. A physically independent reader
and OS-owned delete-termination attestor must agree on absence before a one-shot
protected completion certificate can be recorded. Certification cannot launch,
rollback, switch slots, clear other artifacts, or authorize further witness CAS.

Python dataclasses and callbacks are NOT security boundaries: operating-system
service isolation, irreversible operation accounting, and directory durability
are separately required for production.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final, Protocol

from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_capsule_clearance_preflight import (
    ProtectedCapsuleClearancePreflight,
)
from paper_data_suite.evergreen_plan_capsule_delete_dispatch import (
    _AUTH as _DELETE_AUTH,
)
from paper_data_suite.evergreen_plan_capsule_delete_dispatch import (
    _STATUS as _DELETE_STATUS,
)
from paper_data_suite.evergreen_plan_capsule_delete_dispatch import (
    CapsuleDeleteDispatchError,
    IndependentCapsuleDeleteReadback,
    IndependentCapsuleDeleteReader,
    ProtectedCapsuleDeleteDispatchClaim,
    ProtectedCapsuleDeleteDispatcher,
    _exact_marker,
    _marker_hash,
)
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    ProtectedCapsulePredeleteUncertainty,
    _exact_preflight,
    _preflight_hash,
)
from paper_data_suite.evergreen_plan_finalization_fence import (
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_local_convergence import (
    LocalConvergenceError,
    ProtectedLocalConvergenceRecord,
)
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    ProtectedLocalDeploymentIntent,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    LocalPrewriteUncertaintyError,
    ProtectedLocalPrewriteUncertainty,
)
from paper_data_suite.evergreen_plan_local_receipt_dispatch import (
    ProtectedLocalReceiptDispatchClaim,
)
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedServiceReceiptRecord,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    ProtectedPublicationPreclaim,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_ABSENT: Final = "CAPSULE_ABSENT_PENDING_PROTECTED_CERTIFICATION"
_PRESENT: Final = "CAPSULE_PRESENT_NO_DELETE_RETRY_AUTHORITY"
_UNKNOWN: Final = "CAPSULE_UNKNOWN_QUARANTINE_REQUIRED"
_RECORDED: Final = "CAPSULE_POSTDELETE_RECONCILED_NO_LAUNCH_AUTHORITY"
_NO_AUTH: Final = "NO_REDELETE_RETRY_LAUNCH_ROLLBACK_SWITCH_OR_CAS_AUTHORITY"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_capsule_postdelete_reconciliation_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    delete_claim_sha256 TEXT NOT NULL,
    capsule_identity_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    absence_evidence_sha256 TEXT NOT NULL,
    writer_termination_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'CAPSULE_POSTDELETE_RECONCILED_NO_LAUNCH_AUTHORITY'
    )
)
"""


class CapsulePostdeleteReconciliationError(ValueError):
    """Refuse noncanonical evidence, uncertain termination, or replay."""


@dataclass(frozen=True, slots=True)
class IndependentDeleteTerminationEvidence:
    """OS-service-owned termination proof, not authentication by construction.

    Service must account for every operation issued under the exact durable
    claim, ensure none can resume, and keep exclusive OS fencing across both
    observations, signed witness inspection and protected COMMIT.
    """

    installation_id: str
    transaction_id: str
    delete_claim_sha256: str
    capsule_identity_sha256: str
    deletion_fence_sha256: str
    deletion_termination_sha256: str
    all_prior_delete_operations_terminated: bool
    exclusive_directory_fence_held: bool
    no_unaccounted_deleter_or_writer_in_flight: bool
    directory_durability_independently_verified: bool
    active_successor_physically_reaudited: bool


class IndependentDeleteTerminationReader(Protocol):
    """Installed service reader; untrusted application callbacks are forbidden."""

    def __call__(
        self, request: WitnessCommitRequest, service_context: object, /
    ) -> IndependentDeleteTerminationEvidence: ...


@dataclass(frozen=True, slots=True)
class ProtectedPostdeleteRecoveryObservation:
    """Ephemeral diagnosis. Even a missing capsule does not allow launch."""

    installation_id: str
    transaction_id: str
    observed_capsule_sha256: str | None
    successor_sha256: str
    status: str
    authority: str = _NO_AUTH


@dataclass(frozen=True, slots=True)
class ProtectedCapsulePostdeleteCertificate:
    """Durable completion *evidence*, not a launch or cleanup capability."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    delete_claim_sha256: str
    capsule_identity_sha256: str
    target_identity_sha256: str
    absence_evidence_sha256: str
    writer_termination_evidence_sha256: str
    status: str = _RECORDED
    authority: str = _NO_AUTH


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _claim_hash(item: ProtectedCapsuleDeleteDispatchClaim) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(item, f.name) for f in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_claim(
    claim: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    preflight: ProtectedCapsuleClearancePreflight,
    predelete_marker: ProtectedCapsulePredeleteUncertainty,
) -> bool:
    if not isinstance(claim, ProtectedCapsuleDeleteDispatchClaim):
        return False
    for f in fields(claim):
        value = getattr(claim, f.name)
        expected = (
            int if f.name in ("successor_generation", "witness_revision") else str
        )
        if type(value) is not expected:
            return False
        if f.name.endswith("_sha256") and (
            not isinstance(value, str) or _SHA.fullmatch(value) is None
        ):
            return False
    return (
        claim.status == _DELETE_STATUS
        and claim.authority == _DELETE_AUTH
        and claim.installation_id == request.installation_id
        and claim.transaction_id == reservation.transaction_id
        and claim.request_sha256 == reservation.request_sha256
        and claim.successor_sha256 == request.successor_sha256
        and claim.successor_generation == reservation.successor_generation
        and claim.witness_revision == reservation.witness_revision
        and claim.predelete_marker_sha256 == _marker_hash(predelete_marker)
        and claim.clearance_preflight_sha256 == _preflight_hash(preflight)
        and claim.recovery_capsule_sha256 == reservation.recovery_capsule_sha256
        and claim.capsule_identity_sha256 == preflight.capsule_identity_sha256
        and claim.target_identity_sha256 == intent.target_identity_sha256
        and claim.independent_fence_sha256 == preflight.independent_fence_sha256
    )


def _exact_termination(
    evidence: object,
    request: WitnessCommitRequest,
    claim: ProtectedCapsuleDeleteDispatchClaim,
) -> bool:
    if not isinstance(evidence, IndependentDeleteTerminationEvidence):
        return False
    for f in fields(evidence):
        value = getattr(evidence, f.name)
        if f.name in (
            "all_prior_delete_operations_terminated",
            "exclusive_directory_fence_held",
            "no_unaccounted_deleter_or_writer_in_flight",
            "directory_durability_independently_verified",
            "active_successor_physically_reaudited",
        ):
            if type(value) is not bool or value is not True:
                return False
        elif type(value) is not str:
            return False
    return (
        evidence.installation_id == request.installation_id
        and evidence.transaction_id == claim.transaction_id
        and evidence.delete_claim_sha256 == _claim_hash(claim)
        and evidence.capsule_identity_sha256 == claim.capsule_identity_sha256
        and _SHA.fullmatch(evidence.deletion_fence_sha256) is not None
        and _SHA.fullmatch(evidence.deletion_termination_sha256) is not None
    )


def _classify_postdelete(
    sample: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    claim: ProtectedCapsuleDeleteDispatchClaim,
) -> tuple[str, str | None]:
    if not isinstance(sample, IndependentCapsuleDeleteReadback):
        raise CapsulePostdeleteReconciliationError(
            "independent postdelete read invalid"
        )
    for f in fields(sample):
        value = getattr(sample, f.name)
        if f.name in ("active_receipt_bytes", "capsule_bytes"):
            if value is not None and (
                type(value) is not bytes
                or len(value) > (16384 if f.name == "active_receipt_bytes" else 81920)
            ):
                raise CapsulePostdeleteReconciliationError("unsafe postdelete bytes")
        elif f.name == "capsule_absence_independently_confirmed":
            if type(value) is not bool:
                raise CapsulePostdeleteReconciliationError("invalid absence assertion")
        elif f.name in (
            "parent_directory_protected",
            "active_receipt_protected_regular_file",
            "exclusive_service_fences_held",
            "all_delete_operations_terminated",
            "no_unaccounted_capsule_writer_in_flight",
            "directory_durability_independently_checked",
            "candidate_physical_bytes_reaudited",
        ):
            if type(value) is not bool or value is not True:
                raise CapsulePostdeleteReconciliationError(
                    "postdelete OS fence missing"
                )
        elif type(value) is not str:
            raise CapsulePostdeleteReconciliationError("postdelete identity invalid")
    if (
        sample.installation_id != request.installation_id
        or sample.transaction_id != reservation.transaction_id
        or sample.capsule_identity_sha256 != claim.capsule_identity_sha256
        or sample.target_identity_sha256 != intent.target_identity_sha256
        or sample.active_receipt_bytes != request.successor_receipt_bytes
        or sample.proposal_sha256 != intent.proposal_sha256
        or sample.selection_sha256 != intent.selection_sha256
        or sample.journal_sha256 != intent.journal_sha256
        or sample.capsule_absence_independently_confirmed
        is not (sample.capsule_bytes is None)
    ):
        raise CapsulePostdeleteReconciliationError(
            "changed active successor, protected target or capsule identity"
        )
    if sample.capsule_bytes is None:
        return _ABSENT, None
    found = _sha(sample.capsule_bytes)
    if found == claim.recovery_capsule_sha256:
        return _PRESENT, found
    return _UNKNOWN, found


class ProtectedCapsulePostdeleteReconciler:
    """Independently classify or certify once on same protected service SQLite."""

    def __init__(self, dispatcher: ProtectedCapsuleDeleteDispatcher) -> None:
        if (
            not isinstance(dispatcher, ProtectedCapsuleDeleteDispatcher)
            or not isinstance(dispatcher._db, sqlite3.Connection)
            or dispatcher._db is not dispatcher._predelete._db
            or dispatcher._db is not dispatcher._predelete._clearance._db
            or dispatcher._db.in_transaction
        ):
            raise CapsulePostdeleteReconciliationError(
                "exact protected delete database required"
            )
        self._dispatcher = dispatcher
        self._db = dispatcher._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise CapsulePostdeleteReconciliationError(
                "postdelete certificate table unavailable"
            ) from error

    def _authorize(self, install: str, op: str, context: object) -> None:
        try:
            self._dispatcher._authorize(install, op, context)
        except CapsuleDeleteDispatchError as error:
            raise CapsulePostdeleteReconciliationError(
                "independent postdelete service authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedCapsulePostdeleteCertificate | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise CapsulePostdeleteReconciliationError("invalid installation identity")
        self._authorize(
            installation_id, "observe_postdelete_certificate", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_capsule_postdelete_reconciliation_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise CapsulePostdeleteReconciliationError(
                "protected postdelete certificate unreadable"
            ) from error
        if row is None:
            return None
        try:
            result = ProtectedCapsulePostdeleteCertificate(*row)
        except (TypeError, ValueError) as error:
            raise CapsulePostdeleteReconciliationError(
                "postdelete certificate malformed"
            ) from error
        if (
            result.installation_id != installation_id
            or type(result.transaction_id) is not str
            or _TX.fullmatch(result.transaction_id) is None
            or type(result.successor_generation) is not int
            or not 1 <= result.successor_generation <= 2**53 - 1
            or type(result.witness_revision) is not int
            or not 1 <= result.witness_revision <= 2**53 - 1
            or any(
                type(getattr(result, f.name)) is not str
                or _SHA.fullmatch(getattr(result, f.name)) is None
                for f in fields(result)
                if f.name.endswith("_sha256")
            )
            or result.status != _RECORDED
            or result.authority != _NO_AUTH
        ):
            raise CapsulePostdeleteReconciliationError(
                "durable postdelete certificate corrupt"
            )
        return result

    def _run(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        convergence: ProtectedLocalConvergenceRecord,
        clearance_preflight: ProtectedCapsuleClearancePreflight,
        predelete_marker: ProtectedCapsulePredeleteUncertainty,
        delete_claim: ProtectedCapsuleDeleteDispatchClaim,
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
        certify: bool,
    ) -> ProtectedPostdeleteRecoveryObservation | ProtectedCapsulePostdeleteCertificate:
        convergence_api = self._dispatcher._predelete._clearance._convergence
        try:
            request = convergence_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise CapsulePostdeleteReconciliationError(
                "invalid protected postdelete basis"
            ) from error
        if not (
            _exact_preflight(
                clearance_preflight, request, reservation, intent, convergence
            )
            and _exact_marker(
                predelete_marker,
                request,
                reservation,
                intent,
                convergence,
                clearance_preflight,
            )
            and _exact_claim(
                delete_claim,
                request,
                reservation,
                intent,
                clearance_preflight,
                predelete_marker,
            )
        ):
            raise CapsulePostdeleteReconciliationError(
                "noncanonical protected predelete/claim basis"
            )
        if (
            not callable(independently_read_postdelete)
            or not callable(independently_confirm_delete_termination)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise CapsulePostdeleteReconciliationError(
                "independent postdelete runtime unavailable"
            )
        self._authorize(
            request.installation_id,
            "certify_postdelete_once" if certify else "inspect_postdelete_uncertainty",
            service_context,
        )
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                convergence_api._read_under_service_lock(
                    request,
                    reservation,
                    preclaim,
                    record,
                    intent,
                    marker,
                    claim,
                    service_context=service_context,
                )
                actual = (
                    convergence_api.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._dispatcher._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._dispatcher._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                )
                expected = (
                    convergence,
                    clearance_preflight,
                    predelete_marker,
                    delete_claim,
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise CapsulePostdeleteReconciliationError(
                        "durable protected postdelete chain changed"
                    )
                if (
                    certify
                    and self._db.execute(
                        "SELECT 1 FROM plan_capsule_postdelete_reconciliation_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise CapsulePostdeleteReconciliationError(
                        "postdelete already certified; no repetition or retry"
                    )

                def sample() -> tuple[
                    IndependentDeleteTerminationEvidence, str, str | None
                ]:
                    try:
                        quiet = independently_confirm_delete_termination(
                            request, service_context
                        )
                        physical = independently_read_postdelete(
                            request, service_context
                        )
                    except Exception as error:
                        raise CapsulePostdeleteReconciliationError(
                            "independent postdelete observation unavailable"
                        ) from error
                    if not _exact_termination(quiet, request, delete_claim):
                        raise CapsulePostdeleteReconciliationError(
                            "delete still in flight or termination fence invalid"
                        )
                    status, observed = _classify_postdelete(
                        physical, request, reservation, intent, delete_claim
                    )
                    assert isinstance(quiet, IndependentDeleteTerminationEvidence)
                    return quiet, status, observed

                first, status, observed = sample()
                try:
                    convergence_api._dispatch._prewrite._signed(
                        request, reservation, witness_transport, pinned_public_key, now
                    )
                except Exception as error:
                    raise CapsulePostdeleteReconciliationError(
                        "fresh signed successor head unavailable"
                    ) from error
                second, status2, observed2 = sample()
                if first != second or status != status2 or observed != observed2:
                    raise CapsulePostdeleteReconciliationError(
                        "postdelete physical observations drifted"
                    )
                if not certify:
                    self._db.execute("ROLLBACK")
                    return ProtectedPostdeleteRecoveryObservation(
                        request.installation_id,
                        reservation.transaction_id,
                        observed,
                        request.successor_sha256,
                        status,
                    )
                if status != _ABSENT:
                    raise CapsulePostdeleteReconciliationError(
                        "capsule absence not certified; no deletion retry"
                    )
                certificate = ProtectedCapsulePostdeleteCertificate(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _claim_hash(delete_claim),
                    delete_claim.capsule_identity_sha256,
                    intent.target_identity_sha256,
                    _sha(
                        bytes.fromhex(first.deletion_fence_sha256)
                        + request.successor_receipt_bytes
                        + bytes.fromhex(delete_claim.capsule_identity_sha256)
                    ),
                    _sha(bytes.fromhex(first.deletion_termination_sha256)),
                )
                self._db.execute(
                    "INSERT INTO plan_capsule_postdelete_reconciliation_v1 "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        certificate.installation_id,
                        certificate.transaction_id,
                        certificate.request_sha256,
                        certificate.successor_sha256,
                        certificate.successor_generation,
                        certificate.witness_revision,
                        certificate.delete_claim_sha256,
                        certificate.capsule_identity_sha256,
                        certificate.target_identity_sha256,
                        certificate.absence_evidence_sha256,
                        certificate.writer_termination_evidence_sha256,
                        certificate.status,
                    ),
                )
                self._db.execute("COMMIT")
                return certificate
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except CapsulePostdeleteReconciliationError:
            raise
        except (
            sqlite3.Error,
            CapsuleDeleteDispatchError,
            LocalConvergenceError,
            LocalPrewriteUncertaintyError,
        ) as error:
            raise CapsulePostdeleteReconciliationError(
                "postdelete state uncertain; inspect without redispatch"
            ) from error

    def inspect(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        convergence: ProtectedLocalConvergenceRecord,
        clearance_preflight: ProtectedCapsuleClearancePreflight,
        predelete_marker: ProtectedCapsulePredeleteUncertainty,
        delete_claim: ProtectedCapsuleDeleteDispatchClaim,
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedPostdeleteRecoveryObservation:
        result = self._run(
            request_bytes,
            reservation,
            preclaim,
            record,
            intent,
            marker,
            claim,
            convergence,
            clearance_preflight,
            predelete_marker,
            delete_claim,
            service_context=service_context,
            independently_read_postdelete=independently_read_postdelete,
            independently_confirm_delete_termination=(
                independently_confirm_delete_termination
            ),
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            certify=False,
        )
        assert isinstance(result, ProtectedPostdeleteRecoveryObservation)
        return result

    def certify_once(
        self,
        request_bytes: bytes,
        reservation: ProtectedFinalizationReservation,
        preclaim: ProtectedPublicationPreclaim,
        record: ProtectedServiceReceiptRecord,
        intent: ProtectedLocalDeploymentIntent,
        marker: ProtectedLocalPrewriteUncertainty,
        claim: ProtectedLocalReceiptDispatchClaim,
        convergence: ProtectedLocalConvergenceRecord,
        clearance_preflight: ProtectedCapsuleClearancePreflight,
        predelete_marker: ProtectedCapsulePredeleteUncertainty,
        delete_claim: ProtectedCapsuleDeleteDispatchClaim,
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedCapsulePostdeleteCertificate:
        result = self._run(
            request_bytes,
            reservation,
            preclaim,
            record,
            intent,
            marker,
            claim,
            convergence,
            clearance_preflight,
            predelete_marker,
            delete_claim,
            service_context=service_context,
            independently_read_postdelete=independently_read_postdelete,
            independently_confirm_delete_termination=(
                independently_confirm_delete_termination
            ),
            witness_transport=witness_transport,
            pinned_public_key=pinned_public_key,
            now=now,
            certify=True,
        )
        assert isinstance(result, ProtectedCapsulePostdeleteCertificate)
        return result


__all__ = (
    "CapsulePostdeleteReconciliationError",
    "IndependentDeleteTerminationEvidence",
    "IndependentDeleteTerminationReader",
    "ProtectedPostdeleteRecoveryObservation",
    "ProtectedCapsulePostdeleteCertificate",
    "ProtectedCapsulePostdeleteReconciler",
)
