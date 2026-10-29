"""Issue #49 Slice 94: diagnostic postlaunch runtime-health preflight.

This append-once health certificate does not grant activation, process launch,
retry, receipt mutation, slot switching, or rollback authority. Actual Windows
process-health attestations require a separately qualified privileged service.
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
    IndependentProcessStartReader,
    ProtectedLaunchDispatchClaim,
    _exact_prelaunch,
    _exact_process_readback,
)
from paper_data_suite.evergreen_plan_launch_intent import (
    ProtectedLaunchIntent,
    _exact_readiness,
)
from paper_data_suite.evergreen_plan_launch_reconciliation import (
    LaunchReconciliationError,
    ProtectedLaunchReconciler,
    ProtectedLaunchReconciliationCertificate,
    _exact_dispatch,
    _hash_object,
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
_CERT_STATUS: Final = "PROCESS_START_INDEPENDENTLY_RECONCILED_NO_ACTIVATION_AUTHORITY"
_CERT_AUTH: Final = (
    "NO_LAUNCH_RETRY_ACTIVATE_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
)
_STATUS: Final = "POSTLAUNCH_RUNTIME_HEALTH_PREFLIGHT_RECORDED_NO_ACTIVATION_AUTHORITY"
_AUTH: Final = (
    "NO_PROCESS_LAUNCH_RETRY_ACTIVATE_SWITCH_ROLLBACK_OR_FILE_MUTATION_AUTHORITY"
)
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_launch_health_preflight_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    launch_reconciliation_sha256 TEXT NOT NULL,
    launch_dispatch_claim_sha256 TEXT NOT NULL,
    executable_identity_sha256 TEXT NOT NULL,
    service_boundary_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    process_observation_sha256 TEXT NOT NULL,
    runtime_health_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
      status = 'POSTLAUNCH_RUNTIME_HEALTH_PREFLIGHT_RECORDED_NO_ACTIVATION_AUTHORITY'
    )
)
"""


class LaunchHealthPreflightError(ValueError):
    """Fail closed without changing an earlier one-shot launch claim."""


@dataclass(frozen=True, slots=True)
class IndependentProcessHealthInspection:
    """Attested by an external service; fields alone establish no OS trust."""

    installation_id: str
    transaction_id: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    process_instance_sha256: str
    readiness_probe_sha256: str
    heartbeat_sequence: int
    exact_process_instance_still_running: bool
    launcher_service_fence_held: bool
    no_second_launch_attempt_observed: bool
    approved_executable_still_mapped: bool
    runtime_readiness_probe_succeeded: bool
    successor_receipt_independently_confirmed: bool
    capsule_still_absent_independently_confirmed: bool
    protected_classroom_files_unchanged: bool


class IndependentProcessHealthReader(Protocol):
    def __call__(
        self,
        request: WitnessCommitRequest,
        context: object,
        /,
    ) -> IndependentProcessHealthInspection: ...


@dataclass(frozen=True, slots=True)
class ProtectedLaunchHealthPreflight:
    """One-shot diagnostic evidence only. Never an activation permit."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    launch_reconciliation_sha256: str
    launch_dispatch_claim_sha256: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    process_observation_sha256: str
    runtime_health_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


def _digest(
    item: ProtectedLaunchReconciliationCertificate | IndependentProcessHealthInspection,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {f.name: getattr(item, f.name) for f in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def _exact_reconciliation(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    claim: ProtectedLaunchDispatchClaim,
) -> bool:
    if not isinstance(item, ProtectedLaunchReconciliationCertificate):
        return False
    for f in fields(item):
        value = getattr(item, f.name)
        if f.name in ("successor_generation", "witness_revision"):
            if type(value) is not int:
                return False
        elif type(value) is not str:
            return False
        if f.name.endswith("_sha256") and _SHA.fullmatch(value) is None:
            return False
    return (
        item.status == _CERT_STATUS
        and item.authority == _CERT_AUTH
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.launch_dispatch_claim_sha256 == _hash_object(claim)
        and item.executable_identity_sha256 == claim.executable_identity_sha256
        and item.service_boundary_sha256 == claim.service_boundary_sha256
        and item.target_identity_sha256 == claim.target_identity_sha256
    )


def _exact_health(
    item: object,
    request: WitnessCommitRequest,
    claim: ProtectedLaunchDispatchClaim,
) -> bool:
    if not isinstance(item, IndependentProcessHealthInspection):
        return False
    for f in fields(item):
        value = getattr(item, f.name)
        if f.name == "heartbeat_sequence":
            if type(value) is not int or not 1 <= value <= 2**53 - 1:
                return False
        elif f.name in (
            "exact_process_instance_still_running",
            "launcher_service_fence_held",
            "no_second_launch_attempt_observed",
            "approved_executable_still_mapped",
            "runtime_readiness_probe_succeeded",
            "successor_receipt_independently_confirmed",
            "capsule_still_absent_independently_confirmed",
            "protected_classroom_files_unchanged",
        ):
            if type(value) is not bool or value is not True:
                return False
        elif type(value) is not str:
            return False
        if f.name.endswith("_sha256") and _SHA.fullmatch(value) is None:
            return False
    return (
        item.installation_id == request.installation_id
        and item.transaction_id == claim.transaction_id
        and item.executable_identity_sha256 == claim.executable_identity_sha256
        and item.service_boundary_sha256 == claim.service_boundary_sha256
        and item.target_identity_sha256 == claim.target_identity_sha256
        and item.process_instance_sha256 != "0" * 64
        and item.readiness_probe_sha256 != "0" * 64
    )


class ProtectedLaunchHealthPreflightLedger:
    """Record stable postlaunch health evidence under the protected DB lock."""

    def __init__(self, reconciler: ProtectedLaunchReconciler) -> None:
        if (
            not isinstance(reconciler, ProtectedLaunchReconciler)
            or not isinstance(reconciler._db, sqlite3.Connection)
            or reconciler._db is not reconciler._dispatcher._db
            or reconciler._db.in_transaction
        ):
            raise LaunchHealthPreflightError("exact protected launch database required")
        self._reconciler = reconciler
        self._db = reconciler._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LaunchHealthPreflightError("health table unavailable") from error

    def _authorize(self, installation_id: str, operation: str, context: object) -> None:
        try:
            self._reconciler._authorize(installation_id, operation, context)
        except LaunchReconciliationError as error:
            raise LaunchHealthPreflightError(
                "independent postlaunch service authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLaunchHealthPreflight | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LaunchHealthPreflightError("invalid installation identity")
        self._authorize(installation_id, "observe_launch_health", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_launch_health_preflight_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LaunchHealthPreflightError("health preflight unreadable") from error
        if row is None:
            return None
        try:
            result = ProtectedLaunchHealthPreflight(*row)
        except (ValueError, TypeError) as error:
            raise LaunchHealthPreflightError("health preflight malformed") from error
        if (
            result.installation_id != installation_id
            or type(result.transaction_id) is not str
            or _TX.fullmatch(result.transaction_id) is None
            or type(result.successor_generation) is not int
            or type(result.witness_revision) is not int
            or not 1 <= result.successor_generation <= 2**53 - 1
            or not 1 <= result.witness_revision <= 2**53 - 1
            or any(
                type(getattr(result, f.name)) is not str
                or _SHA.fullmatch(getattr(result, f.name)) is None
                for f in fields(result)
                if f.name.endswith("_sha256")
            )
            or result.status != _STATUS
            or result.authority != _AUTH
        ):
            raise LaunchHealthPreflightError("durable health preflight corrupt")
        return result

    def record_once(
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
        launch_reconciliation: ProtectedLaunchReconciliationCertificate,
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_inspect_process: IndependentProcessStartReader,
        independently_inspect_health: IndependentProcessHealthReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLaunchHealthPreflight:
        """Only persist matching, still-running health checks; do not activate."""
        dispatcher = self._reconciler._dispatcher
        postdelete = dispatcher._prelaunch._intents._readiness._reconciler
        physical_api = postdelete._dispatcher._predelete._clearance._convergence
        try:
            request = physical_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise LaunchHealthPreflightError("noncanonical health basis") from error
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
            and _exact_reconciliation(
                launch_reconciliation, request, reservation, launch_dispatch_claim
            )
        ):
            raise LaunchHealthPreflightError("invalid protected health basis")
        if (
            not callable(independently_read_postdelete)
            or not callable(independently_confirm_delete_termination)
            or not callable(independently_inspect_process)
            or not callable(independently_inspect_health)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise LaunchHealthPreflightError("independent health evidence unavailable")
        self._authorize(
            request.installation_id, "record_postlaunch_health_once", service_context
        )
        result: ProtectedLaunchHealthPreflight | None = None
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
                    postdelete._dispatcher._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    postdelete._dispatcher._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                    postdelete._dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                    postdelete.observe(
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
                    self._reconciler.observe(
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
                    launch_reconciliation,
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise LaunchHealthPreflightError("durable health chain changed")
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_launch_health_preflight_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LaunchHealthPreflightError(
                        "health preflight already recorded; no duplicate"
                    )

                def sample() -> tuple[str, str]:
                    try:
                        terminated = independently_confirm_delete_termination(
                            request, service_context
                        )
                        physical = independently_read_postdelete(
                            request, service_context
                        )
                        process = independently_inspect_process(
                            request, service_context
                        )
                        health = independently_inspect_health(request, service_context)
                    except Exception as error:
                        raise LaunchHealthPreflightError(
                            "independent process health evidence unavailable"
                        ) from error
                    if not _exact_termination(terminated, request, delete_claim):
                        raise LaunchHealthPreflightError(
                            "deletion in flight or independent lock lost"
                        )
                    try:
                        state, leftover = _classify_postdelete(
                            physical, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise LaunchHealthPreflightError(
                            "successor or capsule state changed"
                        ) from error
                    if state != _ABSENT or leftover is not None:
                        raise LaunchHealthPreflightError("capsule reappeared")
                    if not _exact_process_readback(
                        process, request, launch_dispatch_claim
                    ):
                        raise LaunchHealthPreflightError(
                            "independent process start evidence invalid"
                        )
                    if process.process_start_observed is not True:
                        raise LaunchHealthPreflightError(
                            "no independently confirmed process start"
                        )
                    if _hash_object(process) != (
                        launch_reconciliation.process_observation_sha256
                    ):
                        raise LaunchHealthPreflightError(
                            "process-start identity changed since reconciliation"
                        )
                    if not _exact_health(health, request, launch_dispatch_claim):
                        raise LaunchHealthPreflightError(
                            "independent runtime health invalid"
                        )
                    return _hash_object(process), _digest(health)

                before = sample()
                try:
                    physical_api._dispatch._prewrite._signed(
                        request,
                        reservation,
                        witness_transport,
                        pinned_public_key,
                        now,
                    )
                except Exception as error:
                    raise LaunchHealthPreflightError(
                        "fresh signed successor witness unavailable"
                    ) from error
                after = sample()
                if before != after:
                    raise LaunchHealthPreflightError(
                        "postlaunch runtime evidence drifted"
                    )
                result = ProtectedLaunchHealthPreflight(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _digest(launch_reconciliation),
                    launch_reconciliation.launch_dispatch_claim_sha256,
                    launch_dispatch_claim.executable_identity_sha256,
                    launch_dispatch_claim.service_boundary_sha256,
                    intent.target_identity_sha256,
                    before[0],
                    before[1],
                )
                self._db.execute(
                    "INSERT INTO plan_launch_health_preflight_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.launch_reconciliation_sha256,
                        result.launch_dispatch_claim_sha256,
                        result.executable_identity_sha256,
                        result.service_boundary_sha256,
                        result.target_identity_sha256,
                        result.process_observation_sha256,
                        result.runtime_health_evidence_sha256,
                        result.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LaunchHealthPreflightError:
            raise
        except (
            sqlite3.Error,
            LocalConvergenceError,
            LaunchReconciliationError,
        ) as error:
            raise LaunchHealthPreflightError(
                "health COMMIT uncertain; inspect durable state, never activate"
            ) from error
        assert result is not None
        return result


__all__ = (
    "IndependentProcessHealthInspection",
    "IndependentProcessHealthReader",
    "LaunchHealthPreflightError",
    "ProtectedLaunchHealthPreflight",
    "ProtectedLaunchHealthPreflightLedger",
)
