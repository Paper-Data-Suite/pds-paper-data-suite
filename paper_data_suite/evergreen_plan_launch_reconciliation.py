"""Issue #49 Slice 93: independently reconcile a one-shot launch claim.

The pre-existing dispatch claim is never re-issued. Reconciliation observes
an independently fenced process start twice around a fresh signed witness.
No code here launches a process, grants activation, changes a slot, or retries.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Final

from paper_data_suite.evergreen_checkpoint_witness import CheckpointWitnessTransport
from paper_data_suite.evergreen_plan_capsule_clearance_preflight import (
    ProtectedCapsuleClearancePreflight,
)
from paper_data_suite.evergreen_plan_capsule_delete_dispatch import (
    IndependentCapsuleDeleteReader,
    ProtectedCapsuleDeleteDispatchClaim,
)
from paper_data_suite.evergreen_plan_capsule_postdelete_reconciliation import (
    _ABSENT,
    CapsulePostdeleteReconciliationError,
    IndependentDeleteTerminationReader,
    ProtectedCapsulePostdeleteCertificate,
    _classify_postdelete,
    _exact_termination,
)
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    ProtectedCapsulePredeleteUncertainty,
)
from paper_data_suite.evergreen_plan_finalization_fence import (
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_launch_dispatch import (
    IndependentProcessStartReadback,
    IndependentProcessStartReader,
    LaunchDispatchError,
    ProtectedLaunchDispatchClaim,
    ProtectedLaunchDispatcher,
    _exact_prelaunch,
    _exact_process_readback,
    _prelaunch_hash,
)
from paper_data_suite.evergreen_plan_launch_intent import (
    ProtectedLaunchIntent,
    _exact_readiness,
    _hash_record,
)
from paper_data_suite.evergreen_plan_launcher_readiness_preflight import (
    ProtectedLauncherReadinessPreflight,
)
from paper_data_suite.evergreen_plan_local_convergence import (
    LocalConvergenceError,
    ProtectedLocalConvergenceRecord,
)
from paper_data_suite.evergreen_plan_local_deployment_intent import (
    ProtectedLocalDeploymentIntent,
)
from paper_data_suite.evergreen_plan_local_prewrite_uncertainty import (
    ProtectedLocalPrewriteUncertainty,
)
from paper_data_suite.evergreen_plan_local_receipt_dispatch import (
    ProtectedLocalReceiptDispatchClaim,
)
from paper_data_suite.evergreen_plan_prelaunch_uncertainty import (
    ProtectedPrelaunchUncertainty,
    _exact_intent,
    _intent_hash,
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
_CLAIMED: Final = "LAUNCH_DISPATCH_CLAIMED_PROCESS_OUTCOME_UNCERTAIN"
_CLAIM_AUTH: Final = (
    "NO_RELAUNCH_ACTIVATE_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
)
_STATUS: Final = "PROCESS_START_INDEPENDENTLY_RECONCILED_NO_ACTIVATION_AUTHORITY"
_NOT_SEEN: Final = "PROCESS_NOT_OBSERVED_NO_RELAUNCH_AUTHORITY"
_UNKNOWN: Final = "PROCESS_OUTCOME_UNKNOWN_NO_RELAUNCH_AUTHORITY"
_AUTH: Final = "NO_LAUNCH_RETRY_ACTIVATE_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_launch_reconciliation_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    launch_dispatch_claim_sha256 TEXT NOT NULL,
    executable_identity_sha256 TEXT NOT NULL,
    service_boundary_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    process_observation_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'PROCESS_START_INDEPENDENTLY_RECONCILED_NO_ACTIVATION_AUTHORITY'
    )
)
"""


class LaunchReconciliationError(ValueError):
    """Reconciliation refused; the dispatch claim remains non-retryable."""


@dataclass(frozen=True, slots=True)
class ProtectedLaunchReconciliationCertificate:
    """Append-once diagnostic proof of independent start observations only."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    launch_dispatch_claim_sha256: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    process_observation_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


@dataclass(frozen=True, slots=True)
class ProtectedLaunchReconciliationObservation:
    """Absence or uncertainty is diagnostic, not a retry/activation signal."""

    installation_id: str
    transaction_id: str
    status: str
    authority: str = _AUTH


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_object(
    item: (ProtectedLaunchDispatchClaim | IndependentProcessStartReadback),
) -> str:
    return _sha(
        json.dumps(
            {field.name: getattr(item, field.name) for field in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_dispatch(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    prelaunch: ProtectedPrelaunchUncertainty,
    launch_intent: ProtectedLaunchIntent,
    readiness: ProtectedLauncherReadinessPreflight,
) -> bool:
    if not isinstance(item, ProtectedLaunchDispatchClaim):
        return False
    for field in fields(item):
        value = getattr(item, field.name)
        if field.name in ("successor_generation", "witness_revision"):
            if type(value) is not int:
                return False
        elif type(value) is not str:
            return False
        if field.name.endswith("_sha256") and _SHA.fullmatch(value) is None:
            return False
    return (
        item.status == _CLAIMED
        and item.authority == _CLAIM_AUTH
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.prelaunch_marker_sha256 == _prelaunch_hash(prelaunch)
        and item.protected_launch_intent_sha256 == _intent_hash(launch_intent)
        and item.launcher_readiness_preflight_sha256 == _hash_record(readiness)
        and item.executable_identity_sha256 == launch_intent.executable_identity_sha256
        and item.service_boundary_sha256 == launch_intent.service_boundary_sha256
        and item.target_identity_sha256 == intent.target_identity_sha256
        and item.renewed_runtime_evidence_sha256
        == launch_intent.renewed_runtime_evidence_sha256
    )


class ProtectedLaunchReconciler:
    """Read a claimed process start; certify stable observations without launch."""

    def __init__(self, dispatcher: ProtectedLaunchDispatcher) -> None:
        if (
            not isinstance(dispatcher, ProtectedLaunchDispatcher)
            or not isinstance(dispatcher._db, sqlite3.Connection)
            or dispatcher._db is not dispatcher._prelaunch._db
            or dispatcher._db.in_transaction
        ):
            raise LaunchReconciliationError("exact protected launch database required")
        self._dispatcher = dispatcher
        self._db = dispatcher._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LaunchReconciliationError(
                "protected launch reconciliation table unavailable"
            ) from error

    def _authorize(self, installation_id: str, operation: str, context: object) -> None:
        try:
            self._dispatcher._authorize(installation_id, operation, context)
        except LaunchDispatchError as error:
            raise LaunchReconciliationError(
                "independent launch reconciliation authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLaunchReconciliationCertificate | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LaunchReconciliationError("invalid installation identity")
        self._authorize(
            installation_id, "observe_launch_reconciliation", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_launch_reconciliation_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LaunchReconciliationError("reconciliation unreadable") from error
        if row is None:
            return None
        try:
            certificate = ProtectedLaunchReconciliationCertificate(*row)
        except (ValueError, TypeError) as error:
            raise LaunchReconciliationError("reconciliation malformed") from error
        if (
            certificate.installation_id != installation_id
            or type(certificate.transaction_id) is not str
            or _TX.fullmatch(certificate.transaction_id) is None
            or type(certificate.successor_generation) is not int
            or type(certificate.witness_revision) is not int
            or not 1 <= certificate.successor_generation <= 2**53 - 1
            or not 1 <= certificate.witness_revision <= 2**53 - 1
            or any(
                type(getattr(certificate, field.name)) is not str
                or _SHA.fullmatch(getattr(certificate, field.name)) is None
                for field in fields(certificate)
                if field.name.endswith("_sha256")
            )
            or certificate.status != _STATUS
            or certificate.authority != _AUTH
        ):
            raise LaunchReconciliationError("protected reconciliation corrupt")
        return certificate

    def reconcile_once(
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
        postdelete_certificate: ProtectedCapsulePostdeleteCertificate,
        launcher_preflight: ProtectedLauncherReadinessPreflight,
        launch_intent: ProtectedLaunchIntent,
        prelaunch_marker: ProtectedPrelaunchUncertainty,
        launch_dispatch_claim: ProtectedLaunchDispatchClaim,
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_inspect_process: IndependentProcessStartReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> (
        ProtectedLaunchReconciliationCertificate
        | ProtectedLaunchReconciliationObservation
    ):
        """Only a true process-start observation can be certified, never activated."""
        dispatcher = self._dispatcher
        reconciler = dispatcher._prelaunch._intents._readiness._reconciler
        delete_dispatch = reconciler._dispatcher
        convergence_api = delete_dispatch._predelete
        physical_api = convergence_api._clearance._convergence
        try:
            request = physical_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise LaunchReconciliationError("noncanonical launch basis") from error
        if not (
            _exact_prelaunch(
                prelaunch_marker,
                request,
                reservation,
                intent,
                launch_intent,
                launcher_preflight,
                postdelete_certificate,
            )
            and _exact_dispatch(
                launch_dispatch_claim,
                request,
                reservation,
                intent,
                prelaunch_marker,
                launch_intent,
                launcher_preflight,
            )
            and _exact_readiness(
                launcher_preflight,
                request,
                reservation,
                intent,
                postdelete_certificate,
                delete_claim,
            )
            and _exact_intent(
                launch_intent,
                request,
                reservation,
                intent,
                launcher_preflight,
                postdelete_certificate,
            )
        ):
            raise LaunchReconciliationError("invalid protected launch basis")
        if (
            not callable(independently_read_postdelete)
            or not callable(independently_confirm_delete_termination)
            or not callable(independently_inspect_process)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise LaunchReconciliationError("independent process evidence unavailable")
        self._authorize(
            request.installation_id, "reconcile_launch_once", service_context
        )
        result: ProtectedLaunchReconciliationCertificate | None = None
        observation: ProtectedLaunchReconciliationObservation | None = None
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                physical_api._read_under_service_lock(
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
                    physical_api.observe(
                        request.installation_id, service_context=service_context
                    ),
                    convergence_api._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    convergence_api.observe(
                        request.installation_id, service_context=service_context
                    ),
                    delete_dispatch.observe(
                        request.installation_id, service_context=service_context
                    ),
                    reconciler.observe(
                        request.installation_id, service_context=service_context
                    ),
                    dispatcher._prelaunch._intents._readiness.observe(
                        request.installation_id, service_context=service_context
                    ),
                    dispatcher._prelaunch._intents.observe(
                        request.installation_id, service_context=service_context
                    ),
                    dispatcher._prelaunch.observe(
                        request.installation_id, service_context=service_context
                    ),
                    dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                )
                expected = (
                    convergence,
                    clearance_preflight,
                    predelete_marker,
                    delete_claim,
                    postdelete_certificate,
                    launcher_preflight,
                    launch_intent,
                    prelaunch_marker,
                    launch_dispatch_claim,
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise LaunchReconciliationError("durable launch chain changed")
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_launch_reconciliation_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LaunchReconciliationError(
                        "launch already reconciled; no duplicate certificate"
                    )

                def sample() -> tuple[IndependentProcessStartReadback, str]:
                    try:
                        terminated = independently_confirm_delete_termination(
                            request, service_context
                        )
                        postdelete = independently_read_postdelete(
                            request, service_context
                        )
                        process = independently_inspect_process(
                            request, service_context
                        )
                    except Exception as error:
                        raise LaunchReconciliationError(
                            "independent process/physical evidence unavailable"
                        ) from error
                    if not _exact_termination(terminated, request, delete_claim):
                        raise LaunchReconciliationError(
                            "deletion is still in flight or fence unavailable"
                        )
                    try:
                        state, observed = _classify_postdelete(
                            postdelete, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise LaunchReconciliationError(
                            "successor or recovery capsule changed"
                        ) from error
                    if state != _ABSENT or observed is not None:
                        raise LaunchReconciliationError(
                            "capsule reappeared; process reconciliation forbidden"
                        )
                    if not _exact_process_readback(
                        process, request, launch_dispatch_claim
                    ):
                        raise LaunchReconciliationError(
                            "independent process observation invalid"
                        )
                    assert isinstance(process, IndependentProcessStartReadback)
                    return process, _hash_object(process)

                first, first_digest = sample()
                try:
                    physical_api._dispatch._prewrite._signed(
                        request,
                        reservation,
                        witness_transport,
                        pinned_public_key,
                        now,
                    )
                except Exception as error:
                    raise LaunchReconciliationError(
                        "fresh signed successor witness unavailable"
                    ) from error
                second, second_digest = sample()
                if first != second or first_digest != second_digest:
                    raise LaunchReconciliationError(
                        "independent process evidence drifted"
                    )
                if first.process_start_observed is not True:
                    observation = ProtectedLaunchReconciliationObservation(
                        request.installation_id,
                        reservation.transaction_id,
                        _NOT_SEEN
                        if first.process_start_observed is False
                        else _UNKNOWN,
                    )
                else:
                    result = ProtectedLaunchReconciliationCertificate(
                        request.installation_id,
                        reservation.transaction_id,
                        reservation.request_sha256,
                        request.successor_sha256,
                        reservation.successor_generation,
                        reservation.witness_revision,
                        _hash_object(launch_dispatch_claim),
                        launch_dispatch_claim.executable_identity_sha256,
                        launch_dispatch_claim.service_boundary_sha256,
                        intent.target_identity_sha256,
                        first_digest,
                    )
                    self._db.execute(
                        "INSERT INTO plan_launch_reconciliation_v1 VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            result.installation_id,
                            result.transaction_id,
                            result.request_sha256,
                            result.successor_sha256,
                            result.successor_generation,
                            result.witness_revision,
                            result.launch_dispatch_claim_sha256,
                            result.executable_identity_sha256,
                            result.service_boundary_sha256,
                            result.target_identity_sha256,
                            result.process_observation_sha256,
                            result.status,
                        ),
                    )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LaunchReconciliationError:
            raise
        except (sqlite3.Error, LocalConvergenceError, LaunchDispatchError) as error:
            raise LaunchReconciliationError(
                "postlaunch COMMIT uncertain; inspect durable state, never relaunch"
            ) from error
        if result is not None:
            return result
        assert observation is not None
        return observation


__all__ = (
    "LaunchReconciliationError",
    "ProtectedLaunchReconciliationCertificate",
    "ProtectedLaunchReconciliationObservation",
    "ProtectedLaunchReconciler",
)
