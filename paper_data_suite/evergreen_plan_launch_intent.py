"""Issue #49 Slice 90: protected, append-once launch intent without execution.

Binding a prior launcher readiness preflight to a new durable reservation is
NOT permission to start a process. Independently revalidate the persisted
recovery chain, successor, absent capsule, completed deletion and launcher
runtime under the service fence, with a signed witness between two samples.
There is no process execution, slot switch, rollback, CAS or file operation.

Python callback/dataclass assertions cannot establish actual OS isolation.
Independent Windows service custody and crash/durability testing are required.
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
    _claim_hash,
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
from paper_data_suite.evergreen_plan_launcher_readiness_preflight import (
    IndependentLauncherReadinessInspection,
    IndependentLauncherReadinessReader,
    LauncherReadinessPreflightError,
    ProtectedLauncherReadinessPreflight,
    ProtectedLauncherReadinessPreflightLedger,
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
_READINESS_STATUS: Final = "LAUNCH_READINESS_PREFLIGHT_RECORDED_NO_LAUNCH_DISPATCH"
_READINESS_AUTH: Final = "NO_LAUNCH_SWITCH_ROLLBACK_CAS_REDELETE_OR_WRITER_AUTHORITY"
_STATUS: Final = "LAUNCH_INTENT_RESERVED_NO_PROCESS_DISPATCH"
_AUTH: Final = "NO_PROCESS_EXECUTION_SWITCH_ROLLBACK_CAS_OR_FILE_MUTATION_AUTHORITY"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_launch_intent_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    launcher_readiness_preflight_sha256 TEXT NOT NULL,
    postdelete_certificate_sha256 TEXT NOT NULL,
    executable_identity_sha256 TEXT NOT NULL,
    service_boundary_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    renewed_runtime_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LAUNCH_INTENT_RESERVED_NO_PROCESS_DISPATCH'
    )
)
"""


class LaunchIntentError(ValueError):
    """Refuse replay, changed service state, unsafe runtime or invalid evidence."""


@dataclass(frozen=True, slots=True)
class ProtectedLaunchIntent:
    """Protected diagnostic reservation, explicitly *not* a launch capability."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    launcher_readiness_preflight_sha256: str
    postdelete_certificate_sha256: str
    executable_identity_sha256: str
    service_boundary_sha256: str
    target_identity_sha256: str
    renewed_runtime_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


def _hash_record(item: ProtectedLauncherReadinessPreflight) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(item, f.name) for f in fields(item)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_readiness(
    item: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    certificate: ProtectedCapsulePostdeleteCertificate,
    delete_claim: ProtectedCapsuleDeleteDispatchClaim,
) -> bool:
    if not isinstance(item, ProtectedLauncherReadinessPreflight):
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
        item.status == _READINESS_STATUS
        and item.authority == _READINESS_AUTH
        and item.installation_id == request.installation_id
        and item.transaction_id == reservation.transaction_id
        and item.request_sha256 == reservation.request_sha256
        and item.successor_sha256 == request.successor_sha256
        and item.successor_generation == reservation.successor_generation
        and item.witness_revision == reservation.witness_revision
        and item.postdelete_certificate_sha256 == _record_hash(certificate)
        and item.delete_claim_sha256 == _claim_hash(delete_claim)
        and item.target_identity_sha256 == intent.target_identity_sha256
        and item.capsule_identity_sha256 == delete_claim.capsule_identity_sha256
    )


class ProtectedLaunchIntentLedger:
    """Service-owned one-shot non-executing launch intent ledger."""

    def __init__(self, readiness: ProtectedLauncherReadinessPreflightLedger) -> None:
        if (
            not isinstance(readiness, ProtectedLauncherReadinessPreflightLedger)
            or not isinstance(readiness._db, sqlite3.Connection)
            or readiness._db is not readiness._reconciler._db
            or readiness._db is not readiness._reconciler._dispatcher._db
            or readiness._db.in_transaction
        ):
            raise LaunchIntentError("exact protected readiness connection required")
        self._readiness = readiness
        self._db = readiness._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LaunchIntentError("launch intent table unavailable") from error

    def _authorize(self, install: str, action: str, context: object) -> None:
        try:
            self._readiness._authorize(install, action, context)
        except LauncherReadinessPreflightError as error:
            raise LaunchIntentError(
                "independent launch intent authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLaunchIntent | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LaunchIntentError("invalid installation identity")
        self._authorize(installation_id, "observe_launch_intent", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_launch_intent_v1 WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LaunchIntentError("durable launch intent unreadable") from error
        if row is None:
            return None
        try:
            result = ProtectedLaunchIntent(*row)
        except (TypeError, ValueError) as error:
            raise LaunchIntentError("durable launch intent malformed") from error
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
            raise LaunchIntentError("durable launch intent corrupt")
        return result

    def reserve_once(
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
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_read_launcher: IndependentLauncherReadinessReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLaunchIntent:
        """Reserve once after fresh checks. Never dispatch any process."""
        convergence_api = (
            self._readiness._reconciler._dispatcher._predelete._clearance._convergence
        )
        try:
            request = convergence_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise LaunchIntentError("invalid protected launch intent basis") from error
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
        ):
            raise LaunchIntentError("invalid protected launch readiness chain")
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
            raise LaunchIntentError("independent launcher runtime unavailable")
        self._authorize(
            request.installation_id, "reserve_launch_intent_once", service_context
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
                    self._readiness._reconciler._dispatcher._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._readiness._reconciler._dispatcher._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._readiness._reconciler._dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._readiness._reconciler.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._readiness.observe(
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
                )
                if any(
                    type(a) is not type(b) or a != b for a, b in zip(actual, expected)
                ):
                    raise LaunchIntentError("durable protected launch chain changed")
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_launch_intent_v1 WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LaunchIntentError("launch intent already reserved; no replay")

                def sample() -> tuple[str, str, str, str]:
                    try:
                        term = independently_confirm_delete_termination(
                            request, service_context
                        )
                        post = independently_read_postdelete(request, service_context)
                        runtime = independently_read_launcher(request, service_context)
                    except Exception as error:
                        raise LaunchIntentError(
                            "independent launch/physical readback unavailable"
                        ) from error
                    if not _exact_termination(term, request, delete_claim):
                        raise LaunchIntentError(
                            "deletion fence or termination uncertain"
                        )
                    try:
                        status, observed = _classify_postdelete(
                            post, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise LaunchIntentError("successor/capsule changed") from error
                    if status != _ABSENT or observed is not None:
                        raise LaunchIntentError("capsule reappeared; no launch intent")
                    if not _exact_runtime(
                        runtime, request, reservation, intent, delete_claim
                    ):
                        raise LaunchIntentError("runtime identity or fence unverified")
                    assert isinstance(runtime, IndependentLauncherReadinessInspection)
                    runtime_hash = _sha(
                        json.dumps(
                            {f.name: getattr(runtime, f.name) for f in fields(runtime)},
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                        ).encode("ascii")
                    )
                    delete_hash = _sha(
                        bytes.fromhex(term.deletion_fence_sha256)
                        + bytes.fromhex(term.deletion_termination_sha256)
                        + request.successor_receipt_bytes
                        + bytes.fromhex(delete_claim.capsule_identity_sha256)
                    )
                    if (
                        runtime_hash
                        != launcher_preflight.launcher_runtime_evidence_sha256
                        or delete_hash
                        != launcher_preflight.postdelete_recheck_evidence_sha256
                    ):
                        raise LaunchIntentError("readiness evidence expired or changed")
                    return (
                        runtime.executable_identity_sha256,
                        runtime.service_boundary_sha256,
                        runtime_hash,
                        delete_hash,
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
                    raise LaunchIntentError(
                        "fresh signed successor unavailable"
                    ) from error
                second = sample()
                if first != second:
                    raise LaunchIntentError("launcher physical evidence drifted")
                entry = ProtectedLaunchIntent(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _hash_record(launcher_preflight),
                    _record_hash(postdelete_certificate),
                    first[0],
                    first[1],
                    intent.target_identity_sha256,
                    _sha(bytes.fromhex(first[2]) + bytes.fromhex(first[3])),
                )
                self._db.execute(
                    "INSERT INTO plan_launch_intent_v1 VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.installation_id,
                        entry.transaction_id,
                        entry.request_sha256,
                        entry.successor_sha256,
                        entry.successor_generation,
                        entry.witness_revision,
                        entry.launcher_readiness_preflight_sha256,
                        entry.postdelete_certificate_sha256,
                        entry.executable_identity_sha256,
                        entry.service_boundary_sha256,
                        entry.target_identity_sha256,
                        entry.renewed_runtime_evidence_sha256,
                        entry.status,
                    ),
                )
                self._db.execute("COMMIT")
                return entry
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LaunchIntentError:
            raise
        except (
            sqlite3.Error,
            CapsulePostdeleteReconciliationError,
            LocalConvergenceError,
            LocalPrewriteUncertaintyError,
        ) as error:
            raise LaunchIntentError(
                "launch intent outcome uncertain; no execution authorized"
            ) from error


__all__ = (
    "LaunchIntentError",
    "ProtectedLaunchIntent",
    "ProtectedLaunchIntentLedger",
)
