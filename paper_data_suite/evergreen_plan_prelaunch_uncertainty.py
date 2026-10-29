"""Issue #49 Slice 91: one-shot protected prelaunch uncertainty barrier.

Append uncertainty before any future launch-service dispatch may be considered.
There is NO executable launch, slot switch, file mutation, or launcher callback.
A missing or ambiguous acknowledgment never supplies permission to rearm,
retry, activate or infer a successful process start.

Independence, OS writer/execution fencing, caller identity and protected storage
custody are deployment obligations, not established by Python dataclasses.
"""

from __future__ import annotations

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
    _exact_marker,
)
from paper_data_suite.evergreen_plan_capsule_postdelete_reconciliation import (
    _ABSENT,
    CapsulePostdeleteReconciliationError,
    IndependentDeleteTerminationReader,
    ProtectedCapsulePostdeleteCertificate,
    _classify_postdelete,
    _exact_claim,
    _exact_termination,
)
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    ProtectedCapsulePredeleteUncertainty,
    _exact_preflight,
)
from paper_data_suite.evergreen_plan_finalization_fence import (
    ProtectedFinalizationReservation,
)
from paper_data_suite.evergreen_plan_launch_intent import (
    LaunchIntentError,
    ProtectedLaunchIntent,
    ProtectedLaunchIntentLedger,
    _exact_readiness,
    _hash_record,
)
from paper_data_suite.evergreen_plan_launcher_readiness_preflight import (
    IndependentLauncherReadinessInspection,
    IndependentLauncherReadinessReader,
    LauncherReadinessPreflightError,
    ProtectedLauncherReadinessPreflight,
    _exact_certificate,
    _exact_runtime,
    _record_hash,
    _sha,
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
from paper_data_suite.evergreen_plan_protected_receipt import (
    ProtectedServiceReceiptRecord,
)
from paper_data_suite.evergreen_plan_publication_preclaim import (
    ProtectedPublicationPreclaim,
)
from paper_data_suite.evergreen_witness_commit_protocol import WitnessCommitRequest

_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED: Final = "LAUNCH_INTENT_RESERVED_NO_PROCESS_DISPATCH"
_RESERVED_AUTH: Final = (
    "NO_PROCESS_EXECUTION_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
)
_STATUS: Final = "PRELAUNCH_UNCERTAINTY_ARMED_NO_PROCESS_DISPATCH"
_AUTH: Final = "NO_REARM_LAUNCH_RETRY_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_prelaunch_uncertainty_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    protected_launch_intent_sha256 TEXT NOT NULL,
    launcher_readiness_preflight_sha256 TEXT NOT NULL,
    postdelete_certificate_sha256 TEXT NOT NULL,
    executable_identity_sha256 TEXT NOT NULL,
    service_boundary_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    renewed_runtime_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'PRELAUNCH_UNCERTAINTY_ARMED_NO_PROCESS_DISPATCH'
    )
)
"""


class PrelaunchUncertaintyError(ValueError):
    """Refuse uncertain or changed protected launch state, without execution."""


@dataclass(frozen=True, slots=True)
class ProtectedPrelaunchUncertainty:
    """Service-owned append-once barrier; explicitly not a launch capability."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    protected_launch_intent_sha256: str
    launcher_readiness_preflight_sha256: str
    postdelete_certificate_sha256: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    renewed_runtime_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


def _intent_hash(value: ProtectedLaunchIntent) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(value, f.name) for f in fields(value)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_intent(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    readiness: ProtectedLauncherReadinessPreflight,
    certificate: ProtectedCapsulePostdeleteCertificate,
) -> bool:
    if not isinstance(item, ProtectedLaunchIntent):
        return False
    for f in fields(item):
        value = getattr(item, f.name)
        if f.name in ("successor_generation", "witness_revision"):
            if type(value) is not int:
                return False
        elif type(value) is not str:
            return False
        if f.name.endswith("_sha256") and (
            not isinstance(value, str) or _SHA.fullmatch(value) is None
        ):
            return False
    return (
        item.status == _RESERVED
        and item.authority == _RESERVED_AUTH
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.launcher_readiness_preflight_sha256 == _hash_record(readiness)
        and item.postdelete_certificate_sha256 == _record_hash(certificate)
        and item.target_identity_sha256 == intent.target_identity_sha256
        and item.renewed_runtime_evidence_sha256
        == _sha(
            bytes.fromhex(readiness.launcher_runtime_evidence_sha256)
            + bytes.fromhex(readiness.postdelete_recheck_evidence_sha256)
        )
    )


class ProtectedPrelaunchUncertaintyLedger:
    """On the same SQLite connection as protected Slices 78--90."""

    def __init__(self, launch_intents: ProtectedLaunchIntentLedger) -> None:
        if (
            not isinstance(launch_intents, ProtectedLaunchIntentLedger)
            or not isinstance(launch_intents._db, sqlite3.Connection)
            or launch_intents._db is not launch_intents._readiness._db
            or launch_intents._db is not launch_intents._readiness._reconciler._db
            or launch_intents._db.in_transaction
        ):
            raise PrelaunchUncertaintyError("exact protected launch database required")
        self._intents = launch_intents
        self._db = launch_intents._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise PrelaunchUncertaintyError(
                "prelaunch uncertainty table unavailable"
            ) from error

    def _authorize(self, install: str, action: str, context: object) -> None:
        try:
            self._intents._authorize(install, action, context)
        except LaunchIntentError as error:
            raise PrelaunchUncertaintyError(
                "independent prelaunch authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedPrelaunchUncertainty | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise PrelaunchUncertaintyError("invalid installation identity")
        self._authorize(
            installation_id, "observe_prelaunch_uncertainty", service_context
        )
        try:
            row = self._db.execute(
                "SELECT * FROM plan_prelaunch_uncertainty_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise PrelaunchUncertaintyError(
                "prelaunch uncertainty unreadable"
            ) from error
        if row is None:
            return None
        try:
            result = ProtectedPrelaunchUncertainty(*row)
        except (TypeError, ValueError) as error:
            raise PrelaunchUncertaintyError(
                "prelaunch uncertainty malformed"
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
            or result.status != _STATUS
            or result.authority != _AUTH
        ):
            raise PrelaunchUncertaintyError("durable prelaunch uncertainty corrupt")
        return result

    def arm_once(
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
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_read_launcher: IndependentLauncherReadinessReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedPrelaunchUncertainty:
        """Durably arm once; no future launch dispatch is implemented here."""
        dispatcher = self._intents._readiness._reconciler._dispatcher
        convergence_api = dispatcher._predelete._clearance._convergence
        try:
            request = convergence_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise PrelaunchUncertaintyError(
                "invalid protected prelaunch basis"
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
            and _exact_certificate(
                postdelete_certificate, request, reservation, intent, delete_claim
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
            raise PrelaunchUncertaintyError("invalid protected launch/prelaunch chain")
        if (
            not callable(independently_read_postdelete)
            or not callable(independently_confirm_delete_termination)
            or not callable(independently_read_launcher)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise PrelaunchUncertaintyError("independent prelaunch inputs unavailable")
        self._authorize(
            request.installation_id, "arm_prelaunch_uncertainty_once", service_context
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
                    self._intents._readiness._reconciler._dispatcher._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._intents._readiness._reconciler._dispatcher._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._intents._readiness._reconciler._dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._intents._readiness._reconciler.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._intents._readiness.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._intents.observe(
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
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise PrelaunchUncertaintyError("durable protected chain changed")
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_prelaunch_uncertainty_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise PrelaunchUncertaintyError(
                        "prelaunch uncertainty already armed; no repeat or retry"
                    )

                def sample() -> tuple[str, str, str, str]:
                    try:
                        terminated = independently_confirm_delete_termination(
                            request, service_context
                        )
                        post = independently_read_postdelete(request, service_context)
                        runtime = independently_read_launcher(request, service_context)
                    except Exception as error:
                        raise PrelaunchUncertaintyError(
                            "independent prelaunch/physical read unavailable"
                        ) from error
                    if not _exact_termination(terminated, request, delete_claim):
                        raise PrelaunchUncertaintyError(
                            "deletion still in flight or service fence absent"
                        )
                    try:
                        status, observed = _classify_postdelete(
                            post, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise PrelaunchUncertaintyError(
                            "installed successor or capsule changed"
                        ) from error
                    if status != _ABSENT or observed is not None:
                        raise PrelaunchUncertaintyError(
                            "capsule reappeared; process launch forbidden"
                        )
                    if not _exact_runtime(
                        runtime, request, reservation, intent, delete_claim
                    ):
                        raise PrelaunchUncertaintyError(
                            "independent launcher execution fence unverified"
                        )
                    assert isinstance(runtime, IndependentLauncherReadinessInspection)
                    runtime_sha = _sha(
                        json.dumps(
                            {f.name: getattr(runtime, f.name) for f in fields(runtime)},
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                        ).encode("ascii")
                    )
                    delete_sha = _sha(
                        bytes.fromhex(terminated.deletion_fence_sha256)
                        + bytes.fromhex(terminated.deletion_termination_sha256)
                        + request.successor_receipt_bytes
                        + bytes.fromhex(delete_claim.capsule_identity_sha256)
                    )
                    if (
                        runtime_sha
                        != launcher_preflight.launcher_runtime_evidence_sha256
                        or delete_sha
                        != launcher_preflight.postdelete_recheck_evidence_sha256
                        or runtime.executable_identity_sha256
                        != launch_intent.executable_identity_sha256
                        or runtime.service_boundary_sha256
                        != launch_intent.service_boundary_sha256
                        or _sha(bytes.fromhex(runtime_sha) + bytes.fromhex(delete_sha))
                        != launch_intent.renewed_runtime_evidence_sha256
                    ):
                        raise PrelaunchUncertaintyError(
                            "reserved launcher identity or runtime evidence changed"
                        )
                    return (
                        runtime.executable_identity_sha256,
                        runtime.service_boundary_sha256,
                        runtime_sha,
                        delete_sha,
                    )

                first = sample()
                try:
                    convergence_api._dispatch._prewrite._signed(
                        request,
                        reservation,
                        witness_transport,
                        pinned_public_key,
                        now,
                    )
                except Exception as error:
                    raise PrelaunchUncertaintyError(
                        "fresh signed successor witness unavailable"
                    ) from error
                second = sample()
                if first != second:
                    raise PrelaunchUncertaintyError(
                        "prelaunch independent evidence drifted"
                    )
                barrier = ProtectedPrelaunchUncertainty(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _intent_hash(launch_intent),
                    _hash_record(launcher_preflight),
                    _record_hash(postdelete_certificate),
                    first[0],
                    first[1],
                    intent.target_identity_sha256,
                    _sha(bytes.fromhex(first[2]) + bytes.fromhex(first[3])),
                )
                self._db.execute(
                    "INSERT INTO plan_prelaunch_uncertainty_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        barrier.installation_id,
                        barrier.transaction_id,
                        barrier.request_sha256,
                        barrier.successor_sha256,
                        barrier.successor_generation,
                        barrier.witness_revision,
                        barrier.protected_launch_intent_sha256,
                        barrier.launcher_readiness_preflight_sha256,
                        barrier.postdelete_certificate_sha256,
                        barrier.executable_identity_sha256,
                        barrier.service_boundary_sha256,
                        barrier.target_identity_sha256,
                        barrier.renewed_runtime_evidence_sha256,
                        barrier.status,
                    ),
                )
                self._db.execute("COMMIT")
                return barrier
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except PrelaunchUncertaintyError:
            raise
        except (
            sqlite3.Error,
            CapsulePostdeleteReconciliationError,
            LocalConvergenceError,
            LauncherReadinessPreflightError,
            LaunchIntentError,
        ) as error:
            raise PrelaunchUncertaintyError(
                "protected prelaunch outcome uncertain; no execution permitted"
            ) from error


__all__ = (
    "PrelaunchUncertaintyError",
    "ProtectedPrelaunchUncertainty",
    "ProtectedPrelaunchUncertaintyLedger",
)
