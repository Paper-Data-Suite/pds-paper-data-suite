"""Issue #49 Slice 95: protected activation-readiness reservation only.

The persisted postlaunch health certificate is necessary, not sufficient, for
activation. This append-once reservation verifies independent activation-fence
evidence but grants no activation, slot switch, launch, retry, or rollback.
Physical Windows activation and service-fence acceptance remain out of scope.
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
from paper_data_suite.evergreen_plan_launch_health_preflight import (
    IndependentProcessHealthInspection,
    IndependentProcessHealthReader,
    ProtectedLaunchHealthPreflight,
    ProtectedLaunchHealthPreflightLedger,
    _digest,
    _exact_health,
)
from paper_data_suite.evergreen_plan_launch_intent import (
    ProtectedLaunchIntent,
    _exact_readiness,
)
from paper_data_suite.evergreen_plan_launch_reconciliation import (
    LaunchReconciliationError,
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
_STATUS: Final = "ACTIVATION_READINESS_RESERVED_NO_ACTIVATION_DISPATCH"
_AUTH: Final = (
    "NO_ACTIVATE_DISPATCH_SWITCH_LAUNCH_RETRY_ROLLBACK_OR_FILE_MUTATION_AUTHORITY"
)
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_activation_readiness_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    postlaunch_health_preflight_sha256 TEXT NOT NULL,
    launch_reconciliation_sha256 TEXT NOT NULL,
    launch_dispatch_claim_sha256 TEXT NOT NULL,
    executable_identity_sha256 TEXT NOT NULL,
    service_boundary_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    process_observation_sha256 TEXT NOT NULL,
    runtime_health_evidence_sha256 TEXT NOT NULL,
    activation_fence_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
      status = 'ACTIVATION_READINESS_RESERVED_NO_ACTIVATION_DISPATCH'
    )
)
"""


class ActivationReadinessError(ValueError):
    """Fail closed without changing an earlier one-shot launch claim."""


@dataclass(frozen=True, slots=True)
class IndependentActivationFenceInspection:
    """External service inspection; these fields alone establish no OS trust."""

    installation_id: str
    transaction_id: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    process_instance_sha256: str
    activation_fence_sha256: str
    no_prior_activation_attempt_observed: bool
    no_slot_transition_observed: bool
    exclusive_activation_fence_held: bool
    approved_successor_still_active: bool
    approved_process_still_healthy: bool
    protected_classroom_files_unchanged: bool
    no_recovery_operation_in_flight: bool
    no_second_launch_dispatch_observed: bool


class IndependentActivationFenceReader(Protocol):
    def __call__(
        self,
        request: WitnessCommitRequest,
        context: object,
        /,
    ) -> IndependentActivationFenceInspection: ...


@dataclass(frozen=True, slots=True)
class ProtectedActivationReadinessReservation:
    """One-shot reservation only. Never an activation permit."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    postlaunch_health_preflight_sha256: str
    launch_reconciliation_sha256: str
    launch_dispatch_claim_sha256: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    process_observation_sha256: str
    runtime_health_evidence_sha256: str
    activation_fence_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


def _fence_digest(item: IndependentActivationFenceInspection) -> str:
    return hashlib.sha256(
        json.dumps(
            {f.name: getattr(item, f.name) for f in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def _health_digest(item: ProtectedLaunchHealthPreflight) -> str:
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


def _exact_fence(
    item: object,
    request: WitnessCommitRequest,
    claim: ProtectedLaunchDispatchClaim,
    health: IndependentProcessHealthInspection,
) -> bool:
    if not isinstance(item, IndependentActivationFenceInspection):
        return False
    for f in fields(item):
        value = getattr(item, f.name)
        if f.name.startswith(("no_", "exclusive_", "approved_", "protected_")):
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
        and item.process_instance_sha256 == health.process_instance_sha256
        and item.activation_fence_sha256 != "0" * 64
    )


def _exact_health_record(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    launch_certificate: ProtectedLaunchReconciliationCertificate,
    claim: ProtectedLaunchDispatchClaim,
) -> bool:
    if not isinstance(item, ProtectedLaunchHealthPreflight):
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
        item.status
        == ("POSTLAUNCH_RUNTIME_HEALTH_PREFLIGHT_RECORDED_NO_ACTIVATION_AUTHORITY")
        and item.authority
        == "NO_PROCESS_LAUNCH_RETRY_ACTIVATE_SWITCH_ROLLBACK_OR_FILE_MUTATION_AUTHORITY"
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.launch_reconciliation_sha256 == _digest(launch_certificate)
        and item.launch_dispatch_claim_sha256 == _hash_object(claim)
        and item.executable_identity_sha256 == claim.executable_identity_sha256
        and item.service_boundary_sha256 == claim.service_boundary_sha256
        and item.target_identity_sha256 == claim.target_identity_sha256
        and item.process_observation_sha256
        == launch_certificate.process_observation_sha256
    )


class ProtectedActivationReadinessLedger:
    """Reserve activation readiness without activating under the protected lock."""

    def __init__(self, health_ledger: ProtectedLaunchHealthPreflightLedger) -> None:
        if (
            not isinstance(health_ledger, ProtectedLaunchHealthPreflightLedger)
            or not isinstance(health_ledger._db, sqlite3.Connection)
            or health_ledger._db is not health_ledger._reconciler._db
            or health_ledger._db.in_transaction
        ):
            raise ActivationReadinessError("exact protected launch database required")
        self._health_ledger = health_ledger
        self._reconciler = health_ledger._reconciler
        self._db = health_ledger._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise ActivationReadinessError(
                "activation readiness table unavailable"
            ) from error

    def _authorize(self, installation_id: str, operation: str, context: object) -> None:
        try:
            self._reconciler._authorize(installation_id, operation, context)
        except LaunchReconciliationError as error:
            raise ActivationReadinessError(
                "independent postlaunch service authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedActivationReadinessReservation | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise ActivationReadinessError("invalid installation identity")
        self._authorize(
            installation_id, "observe_activation_readiness", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_activation_readiness_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise ActivationReadinessError(
                "activation reservation unreadable"
            ) from error
        if row is None:
            return None
        try:
            result = ProtectedActivationReadinessReservation(*row)
        except (ValueError, TypeError) as error:
            raise ActivationReadinessError(
                "activation reservation malformed"
            ) from error
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
            raise ActivationReadinessError("durable activation reservation corrupt")
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
        postlaunch_health_preflight: ProtectedLaunchHealthPreflight,
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_inspect_process: IndependentProcessStartReader,
        independently_inspect_health: IndependentProcessHealthReader,
        independently_inspect_activation: IndependentActivationFenceReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedActivationReadinessReservation:
        """Persist readiness once, without activating or switching."""
        dispatcher = self._reconciler._dispatcher
        postdelete = dispatcher._prelaunch._intents._readiness._reconciler
        physical_api = postdelete._dispatcher._predelete._clearance._convergence
        try:
            request = physical_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise ActivationReadinessError("noncanonical health basis") from error
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
            and _exact_health_record(
                postlaunch_health_preflight,
                request,
                reservation,
                launch_reconciliation,
                launch_dispatch_claim,
            )
        ):
            raise ActivationReadinessError("invalid protected activation basis")
        if (
            not callable(independently_read_postdelete)
            or not callable(independently_confirm_delete_termination)
            or not callable(independently_inspect_process)
            or not callable(independently_inspect_health)
            or not callable(independently_inspect_activation)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise ActivationReadinessError(
                "independent activation evidence unavailable"
            )
        self._authorize(
            request.installation_id,
            "reserve_activation_readiness_once",
            service_context,
        )
        result: ProtectedActivationReadinessReservation | None = None
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
                    self._health_ledger.observe(
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
                    postlaunch_health_preflight,
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise ActivationReadinessError("durable activation chain changed")
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_activation_readiness_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise ActivationReadinessError(
                        "activation readiness already reserved; no duplicate"
                    )

                def sample() -> tuple[str, str, str]:
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
                        fence = independently_inspect_activation(
                            request, service_context
                        )
                    except Exception as error:
                        raise ActivationReadinessError(
                            "independent activation evidence unavailable"
                        ) from error
                    if not _exact_termination(terminated, request, delete_claim):
                        raise ActivationReadinessError(
                            "deletion in flight or independent lock lost"
                        )
                    try:
                        state, leftover = _classify_postdelete(
                            physical, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise ActivationReadinessError(
                            "successor or capsule state changed"
                        ) from error
                    if state != _ABSENT or leftover is not None:
                        raise ActivationReadinessError("capsule reappeared")
                    if not _exact_process_readback(
                        process, request, launch_dispatch_claim
                    ):
                        raise ActivationReadinessError(
                            "independent process start evidence invalid"
                        )
                    if process.process_start_observed is not True:
                        raise ActivationReadinessError(
                            "no independently confirmed process start"
                        )
                    if _hash_object(process) != (
                        launch_reconciliation.process_observation_sha256
                    ):
                        raise ActivationReadinessError(
                            "process-start identity changed since reconciliation"
                        )
                    if not _exact_health(health, request, launch_dispatch_claim):
                        raise ActivationReadinessError(
                            "independent runtime health invalid"
                        )
                    if _digest(health) != (
                        postlaunch_health_preflight.runtime_health_evidence_sha256
                    ):
                        raise ActivationReadinessError(
                            "health inspection changed since preflight"
                        )
                    if not _exact_fence(fence, request, launch_dispatch_claim, health):
                        raise ActivationReadinessError(
                            "independent activation fence invalid"
                        )
                    return _hash_object(process), _digest(health), _fence_digest(fence)

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
                    raise ActivationReadinessError(
                        "fresh signed successor witness unavailable"
                    ) from error
                after = sample()
                if before != after:
                    raise ActivationReadinessError(
                        "activation readiness evidence drifted"
                    )
                result = ProtectedActivationReadinessReservation(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _health_digest(postlaunch_health_preflight),
                    _digest(launch_reconciliation),
                    launch_reconciliation.launch_dispatch_claim_sha256,
                    launch_dispatch_claim.executable_identity_sha256,
                    launch_dispatch_claim.service_boundary_sha256,
                    intent.target_identity_sha256,
                    before[0],
                    before[1],
                    before[2],
                )
                self._db.execute(
                    "INSERT INTO plan_activation_readiness_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.postlaunch_health_preflight_sha256,
                        result.launch_reconciliation_sha256,
                        result.launch_dispatch_claim_sha256,
                        result.executable_identity_sha256,
                        result.service_boundary_sha256,
                        result.target_identity_sha256,
                        result.process_observation_sha256,
                        result.runtime_health_evidence_sha256,
                        result.activation_fence_evidence_sha256,
                        result.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except ActivationReadinessError:
            raise
        except (
            sqlite3.Error,
            LocalConvergenceError,
            LaunchReconciliationError,
        ) as error:
            raise ActivationReadinessError(
                "activation reservation COMMIT uncertain; inspect durable state"
            ) from error
        assert result is not None
        return result


__all__ = (
    "ActivationReadinessError",
    "IndependentActivationFenceInspection",
    "IndependentActivationFenceReader",
    "ProtectedActivationReadinessReservation",
    "ProtectedActivationReadinessLedger",
)
