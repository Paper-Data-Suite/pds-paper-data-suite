"""Issue #49 Slice 92: protected, one-shot launcher dispatch boundary.

The service commits an immutable claim BEFORE a future service-owned process
start may be dispatched once. A missing acknowledgment, missing process, or
uncertain process outcome NEVER gives permission to launch again. A callback
or dataclass cannot establish the true Windows service privilege boundary.
No slot switch, rollback, cleanup, activation or process acceptance is here.
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
    ProtectedLaunchIntent,
    _exact_readiness,
    _hash_record,
)
from paper_data_suite.evergreen_plan_launcher_readiness_preflight import (
    IndependentLauncherReadinessInspection,
    IndependentLauncherReadinessReader,
    ProtectedLauncherReadinessPreflight,
    _exact_certificate,
    _exact_runtime,
    _record_hash,
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
    PrelaunchUncertaintyError,
    ProtectedPrelaunchUncertainty,
    ProtectedPrelaunchUncertaintyLedger,
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
_ARMED: Final = "PRELAUNCH_UNCERTAINTY_ARMED_NO_PROCESS_DISPATCH"
_ARMED_AUTH: Final = (
    "NO_REARM_LAUNCH_RETRY_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
)
_STATUS: Final = "LAUNCH_DISPATCH_CLAIMED_PROCESS_OUTCOME_UNCERTAIN"
_AUTH: Final = "NO_RELAUNCH_ACTIVATE_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
_SEEN: Final = "PROCESS_START_OBSERVED_ACTIVATION_NOT_AUTHORIZED"
_NOT_SEEN: Final = "PROCESS_NOT_OBSERVED_NO_RETRY_AUTHORITY"
_UNKNOWN: Final = "PROCESS_OUTCOME_UNKNOWN_QUARANTINE_REQUIRED"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_launch_dispatch_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    prelaunch_marker_sha256 TEXT NOT NULL,
    protected_launch_intent_sha256 TEXT NOT NULL,
    launcher_readiness_preflight_sha256 TEXT NOT NULL,
    executable_identity_sha256 TEXT NOT NULL,
    service_boundary_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    renewed_runtime_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LAUNCH_DISPATCH_CLAIMED_PROCESS_OUTCOME_UNCERTAIN'
    )
)
"""


class LaunchDispatchError(ValueError):
    """Refuse changed protected launch basis or uncertain process dispatch."""


class IndependentProcessLauncher(Protocol):
    """An independently provisioned, OS-isolated service; never a teacher hook.

    Production must bind a pinned executable, ensure launch isolation, and
    reject retries even when a Python process dies after this dispatch claim.
    Python protocol conformance establishes NONE of these runtime properties.
    """

    def __call__(
        self,
        request: WitnessCommitRequest,
        executable_identity_sha256: str,
        service_context: object,
        /,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class IndependentProcessStartReadback:
    """Service-side process observation, never an activation certificate."""

    installation_id: str
    transaction_id: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    process_start_observed: bool | None
    exclusive_launcher_service_fence_held: bool
    no_second_dispatch_observed: bool
    successor_receipt_independently_confirmed: bool
    capsule_still_absent_independently_confirmed: bool
    protected_software_and_classroom_files_unchanged: bool


class IndependentProcessStartReader(Protocol):
    def __call__(
        self,
        request: WitnessCommitRequest,
        context: object,
        /,
    ) -> IndependentProcessStartReadback: ...


@dataclass(frozen=True, slots=True)
class ProtectedLaunchDispatchClaim:
    """Append-once claim, recorded before one potential process start."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    prelaunch_marker_sha256: str
    protected_launch_intent_sha256: str
    launcher_readiness_preflight_sha256: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    renewed_runtime_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


@dataclass(frozen=True, slots=True)
class ProtectedLaunchDispatchObservation:
    """Diagnostic only. No authority to retry, launch, or activate."""

    installation_id: str
    transaction_id: str
    executable_identity_sha256: str
    status: str
    authority: str = _AUTH


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _prelaunch_hash(value: ProtectedPrelaunchUncertainty) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(value, f.name) for f in fields(value)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_prelaunch(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    launch_intent: ProtectedLaunchIntent,
    readiness: ProtectedLauncherReadinessPreflight,
    certificate: ProtectedCapsulePostdeleteCertificate,
) -> bool:
    if not isinstance(item, ProtectedPrelaunchUncertainty):
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
        item.status == _ARMED
        and item.authority == _ARMED_AUTH
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.protected_launch_intent_sha256 == _intent_hash(launch_intent)
        and item.launcher_readiness_preflight_sha256 == _hash_record(readiness)
        and item.postdelete_certificate_sha256 == _record_hash(certificate)
        and item.executable_identity_sha256 == launch_intent.executable_identity_sha256
        and item.service_boundary_sha256 == launch_intent.service_boundary_sha256
        and item.target_identity_sha256 == intent.target_identity_sha256
        and item.renewed_runtime_evidence_sha256
        == launch_intent.renewed_runtime_evidence_sha256
    )


def _exact_process_readback(
    sample: object,
    request: WitnessCommitRequest,
    claim: ProtectedLaunchDispatchClaim,
) -> bool:
    if not isinstance(sample, IndependentProcessStartReadback):
        return False
    for f in fields(sample):
        value = getattr(sample, f.name)
        if f.name == "process_start_observed":
            if value is not None and type(value) is not bool:
                return False
        elif f.name in (
            "exclusive_launcher_service_fence_held",
            "no_second_dispatch_observed",
            "successor_receipt_independently_confirmed",
            "capsule_still_absent_independently_confirmed",
            "protected_software_and_classroom_files_unchanged",
        ):
            if type(value) is not bool or value is not True:
                return False
        elif type(value) is not str:
            return False
    return (
        sample.installation_id == request.installation_id
        and sample.transaction_id == claim.transaction_id
        and sample.executable_identity_sha256 == claim.executable_identity_sha256
        and sample.service_boundary_sha256 == claim.service_boundary_sha256
        and sample.target_identity_sha256 == claim.target_identity_sha256
    )


class ProtectedLaunchDispatcher:
    """Service-owned, guarded claim before at most one external launch call."""

    def __init__(self, prelaunch: ProtectedPrelaunchUncertaintyLedger) -> None:
        if (
            not isinstance(prelaunch, ProtectedPrelaunchUncertaintyLedger)
            or not isinstance(prelaunch._db, sqlite3.Connection)
            or prelaunch._db is not prelaunch._intents._db
            or prelaunch._db is not prelaunch._intents._readiness._db
            or prelaunch._db.in_transaction
        ):
            raise LaunchDispatchError("exact protected launcher database required")
        self._prelaunch = prelaunch
        self._db = prelaunch._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LaunchDispatchError("launch dispatch table unavailable") from error

    def _authorize(self, install: str, operation: str, context: object) -> None:
        try:
            self._prelaunch._authorize(install, operation, context)
        except PrelaunchUncertaintyError as error:
            raise LaunchDispatchError(
                "independent launch-dispatch authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLaunchDispatchClaim | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LaunchDispatchError("invalid installation identity")
        self._authorize(installation_id, "observe_launch_dispatch", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_launch_dispatch_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LaunchDispatchError("launch dispatch claim unreadable") from error
        if row is None:
            return None
        try:
            result = ProtectedLaunchDispatchClaim(*row)
        except (TypeError, ValueError) as error:
            raise LaunchDispatchError("launch dispatch claim malformed") from error
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
            raise LaunchDispatchError("durable launch dispatch claim corrupt")
        return result

    def dispatch_once(
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
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_read_launcher: IndependentLauncherReadinessReader,
        independently_inspect_process: IndependentProcessStartReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
        service_owned_launch: IndependentProcessLauncher,
    ) -> ProtectedLaunchDispatchObservation:
        """Commit dispatch claim then invoke one service launch, never relaunch."""
        dispatcher = self._prelaunch._intents._readiness._reconciler._dispatcher
        convergence_api = dispatcher._predelete._clearance._convergence
        try:
            request = convergence_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise LaunchDispatchError("noncanonical protected launch basis") from error
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
            and _exact_prelaunch(
                prelaunch_marker,
                request,
                reservation,
                intent,
                launch_intent,
                launcher_preflight,
                postdelete_certificate,
            )
        ):
            raise LaunchDispatchError("invalid protected launch dispatch basis")
        if (
            not callable(independently_read_postdelete)
            or not callable(independently_confirm_delete_termination)
            or not callable(independently_read_launcher)
            or not callable(independently_inspect_process)
            or not callable(service_owned_launch)
            or not callable(witness_transport)
            or type(pinned_public_key) is not bytes
            or len(pinned_public_key) != 32
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or now.microsecond != 0
            or self._db.in_transaction
        ):
            raise LaunchDispatchError("independent launcher dispatch inputs missing")
        self._authorize(
            request.installation_id, "dispatch_launch_once", service_context
        )
        result = ProtectedLaunchDispatchClaim(
            request.installation_id,
            reservation.transaction_id,
            reservation.request_sha256,
            request.successor_sha256,
            reservation.successor_generation,
            reservation.witness_revision,
            _prelaunch_hash(prelaunch_marker),
            _intent_hash(launch_intent),
            _hash_record(launcher_preflight),
            launch_intent.executable_identity_sha256,
            launch_intent.service_boundary_sha256,
            intent.target_identity_sha256,
            launch_intent.renewed_runtime_evidence_sha256,
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
                    dispatcher._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    dispatcher._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                    dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._prelaunch._intents._readiness._reconciler.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._prelaunch._intents._readiness.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._prelaunch._intents.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._prelaunch.observe(
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
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise LaunchDispatchError("durable protected launch chain changed")
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_launch_dispatch_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LaunchDispatchError(
                        "launch already claimed; no redispatch or retry"
                    )

                def sample() -> tuple[str, str, str, str]:
                    try:
                        terminated = independently_confirm_delete_termination(
                            request, service_context
                        )
                        post = independently_read_postdelete(request, service_context)
                        runtime = independently_read_launcher(request, service_context)
                    except Exception as error:
                        raise LaunchDispatchError(
                            "independent launcher/physical read unavailable"
                        ) from error
                    if not _exact_termination(terminated, request, delete_claim):
                        raise LaunchDispatchError(
                            "deletion still in flight or service fence missing"
                        )
                    try:
                        state, observed = _classify_postdelete(
                            post, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise LaunchDispatchError(
                            "installed successor or capsule changed"
                        ) from error
                    if state != _ABSENT or observed is not None:
                        raise LaunchDispatchError(
                            "capsule reappeared; launcher dispatch forbidden"
                        )
                    if not _exact_runtime(
                        runtime, request, reservation, intent, delete_claim
                    ):
                        raise LaunchDispatchError(
                            "independent launcher service fence not verified"
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
                        or (
                            _sha(bytes.fromhex(runtime_sha) + bytes.fromhex(delete_sha))
                            != launch_intent.renewed_runtime_evidence_sha256
                        )
                    ):
                        raise LaunchDispatchError(
                            "reserved launcher executable/runtime evidence changed"
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
                    raise LaunchDispatchError(
                        "fresh signed successor witness unavailable"
                    ) from error
                second = sample()
                if first != second:
                    raise LaunchDispatchError("independent prelaunch evidence drifted")
                if result.renewed_runtime_evidence_sha256 != _sha(
                    bytes.fromhex(first[2]) + bytes.fromhex(first[3])
                ):
                    raise LaunchDispatchError("prelaunch evidence hash drifted")
                self._db.execute(
                    "INSERT INTO plan_launch_dispatch_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.installation_id,
                        result.transaction_id,
                        result.request_sha256,
                        result.successor_sha256,
                        result.successor_generation,
                        result.witness_revision,
                        result.prelaunch_marker_sha256,
                        result.protected_launch_intent_sha256,
                        result.launcher_readiness_preflight_sha256,
                        result.executable_identity_sha256,
                        result.service_boundary_sha256,
                        result.target_identity_sha256,
                        result.renewed_runtime_evidence_sha256,
                        result.status,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LaunchDispatchError:
            raise
        except (
            sqlite3.Error,
            LocalConvergenceError,
            PrelaunchUncertaintyError,
        ) as error:
            raise LaunchDispatchError(
                "launch claim COMMIT outcome uncertain; inspect without retry"
            ) from error
        # The claim is durable BEFORE the sole external launch call. A crash,
        # lost acknowledgment, missing process, or failed readback cannot give
        # permission to call service_owned_launch again.
        try:
            service_owned_launch(
                request, launch_intent.executable_identity_sha256, service_context
            )
        except Exception as error:
            raise LaunchDispatchError(
                "process launch outcome uncertain; no relaunch"
            ) from error
        try:
            observed = independently_inspect_process(request, service_context)
            convergence_api._dispatch._prewrite._signed(
                request, reservation, witness_transport, pinned_public_key, now
            )
        except Exception as error:
            raise LaunchDispatchError(
                "postlaunch independent observation unavailable; no relaunch"
            ) from error
        if not _exact_process_readback(observed, request, result):
            raise LaunchDispatchError(
                "postlaunch process/service state unverified; no relaunch"
            )
        assert isinstance(observed, IndependentProcessStartReadback)
        state = (
            _SEEN
            if observed.process_start_observed is True
            else _NOT_SEEN
            if observed.process_start_observed is False
            else _UNKNOWN
        )
        return ProtectedLaunchDispatchObservation(
            request.installation_id,
            reservation.transaction_id,
            launch_intent.executable_identity_sha256,
            state,
        )


__all__ = (
    "LaunchDispatchError",
    "IndependentProcessLauncher",
    "IndependentProcessStartReadback",
    "IndependentProcessStartReader",
    "ProtectedLaunchDispatchClaim",
    "ProtectedLaunchDispatchObservation",
    "ProtectedLaunchDispatcher",
)
