"""Issue #49 Slice 89: protected, non-activating launcher readiness preflight.

A completed deletion and protected certificate do not authorize execution.
Verify the entire persisted service chain and independently inspect the actual
post-delete state, writer termination, and launcher/runtime prerequisites twice.
Append one protected diagnostic row. There is NO launcher, switch, CAS, rollback,
re-delete, receipt writer, or further capsule cleanup operation in this module.

Callbacks/dataclasses do not establish independent operating-system custody.
Privileged Windows service enforcement and crash/durability acceptance remain
separate deployment obligations.
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
    _RECORDED,
    CapsulePostdeleteReconciliationError,
    IndependentDeleteTerminationReader,
    ProtectedCapsulePostdeleteCertificate,
    ProtectedCapsulePostdeleteReconciler,
    _claim_hash,
    _classify_postdelete,
    _exact_claim,
    _exact_termination,
)
from paper_data_suite.evergreen_plan_capsule_postdelete_reconciliation import (
    _NO_AUTH as _POSTDELETE_AUTH,
)
from paper_data_suite.evergreen_plan_capsule_predelete_uncertainty import (
    ProtectedCapsulePredeleteUncertainty,
    _exact_preflight,
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
_STATUS: Final = "LAUNCH_READINESS_PREFLIGHT_RECORDED_NO_LAUNCH_DISPATCH"
_AUTH: Final = "NO_LAUNCH_SWITCH_ROLLBACK_CAS_REDELETE_OR_WRITER_AUTHORITY"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS plan_launcher_readiness_preflight_v1 (
    installation_id TEXT PRIMARY KEY NOT NULL,
    transaction_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    successor_sha256 TEXT NOT NULL,
    successor_generation INTEGER NOT NULL,
    witness_revision INTEGER NOT NULL,
    postdelete_certificate_sha256 TEXT NOT NULL,
    delete_claim_sha256 TEXT NOT NULL,
    target_identity_sha256 TEXT NOT NULL,
    capsule_identity_sha256 TEXT NOT NULL,
    launcher_runtime_evidence_sha256 TEXT NOT NULL,
    postdelete_recheck_evidence_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status = 'LAUNCH_READINESS_PREFLIGHT_RECORDED_NO_LAUNCH_DISPATCH'
    )
)
"""


class LauncherReadinessPreflightError(ValueError):
    """Refuse changed protected state, unsafe runtime evidence, or replay."""


@dataclass(frozen=True, slots=True)
class IndependentLauncherReadinessInspection:
    """Service-owned, read-only runtime probe; data type does NOT prove custody.

    The independent service must pin executable/runtime identities, verify the
    installed candidate and its transitive dependencies without launching it,
    maintain OS fences, and exclude any caller-supplied paths or fake booleans.
    """

    installation_id: str
    transaction_id: str
    request_sha256: str
    target_identity_sha256: str
    capsule_identity_sha256: str
    selection_sha256: str
    journal_sha256: str
    executable_identity_sha256: str
    installed_runtime_sha256: str
    service_boundary_sha256: str
    read_only_runtime_audit_completed: bool
    candidate_dependencies_independently_verified: bool
    installed_candidate_identity_matches_signed_successor: bool
    active_receipt_and_capsule_directories_os_fenced: bool
    no_inflight_deleter_writer_or_launcher: bool
    classroom_and_user_data_untouched: bool
    no_launcher_execution_attempted: bool


class IndependentLauncherReadinessReader(Protocol):
    """Independent privileged runtime reader, never teacher-supplied."""

    def __call__(
        self, request: WitnessCommitRequest, service_context: object, /
    ) -> IndependentLauncherReadinessInspection: ...


@dataclass(frozen=True, slots=True)
class ProtectedLauncherReadinessPreflight:
    """Durable diagnostic; never a capability to launch or switch."""

    installation_id: str
    transaction_id: str
    request_sha256: str
    successor_sha256: str
    successor_generation: int
    witness_revision: int
    postdelete_certificate_sha256: str
    delete_claim_sha256: str
    target_identity_sha256: str
    capsule_identity_sha256: str
    launcher_runtime_evidence_sha256: str
    postdelete_recheck_evidence_sha256: str
    status: str = _STATUS
    authority: str = _AUTH


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record_hash(record: ProtectedCapsulePostdeleteCertificate) -> str:
    return _sha(
        json.dumps(
            {f.name: getattr(record, f.name) for f in fields(record)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _exact_certificate(
    certificate: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    delete_claim: ProtectedCapsuleDeleteDispatchClaim,
) -> bool:
    if not isinstance(certificate, ProtectedCapsulePostdeleteCertificate):
        return False
    for f in fields(certificate):
        value = getattr(certificate, f.name)
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
        certificate.status == _RECORDED
        and certificate.authority == _POSTDELETE_AUTH
        and certificate.installation_id == request.installation_id
        and certificate.transaction_id == reservation.transaction_id
        and certificate.request_sha256 == reservation.request_sha256
        and certificate.successor_sha256 == request.successor_sha256
        and certificate.successor_generation == reservation.successor_generation
        and certificate.witness_revision == reservation.witness_revision
        and certificate.delete_claim_sha256 == _claim_hash(delete_claim)
        and certificate.capsule_identity_sha256 == delete_claim.capsule_identity_sha256
        and certificate.target_identity_sha256 == intent.target_identity_sha256
    )


def _exact_runtime(
    evidence: object,
    request: WitnessCommitRequest,
    reservation: ProtectedFinalizationReservation,
    intent: ProtectedLocalDeploymentIntent,
    delete_claim: ProtectedCapsuleDeleteDispatchClaim,
) -> bool:
    if not isinstance(evidence, IndependentLauncherReadinessInspection):
        return False
    bools = {
        "read_only_runtime_audit_completed",
        "candidate_dependencies_independently_verified",
        "installed_candidate_identity_matches_signed_successor",
        "active_receipt_and_capsule_directories_os_fenced",
        "no_inflight_deleter_writer_or_launcher",
        "classroom_and_user_data_untouched",
        "no_launcher_execution_attempted",
    }
    for f in fields(evidence):
        value = getattr(evidence, f.name)
        if f.name in bools:
            if type(value) is not bool or value is not True:
                return False
        elif type(value) is not str:
            return False
        elif f.name.endswith("_sha256") and _SHA.fullmatch(value) is None:
            return False
    return (
        evidence.installation_id == request.installation_id
        and evidence.transaction_id == reservation.transaction_id
        and evidence.request_sha256 == reservation.request_sha256
        and evidence.target_identity_sha256 == intent.target_identity_sha256
        and evidence.capsule_identity_sha256 == delete_claim.capsule_identity_sha256
        and evidence.selection_sha256 == reservation.selection_sha256
        and evidence.journal_sha256 == reservation.journal_sha256
    )


class ProtectedLauncherReadinessPreflightLedger:
    """Same protected SQLite connection as Slices 78--88; no launch method."""

    def __init__(self, reconciler: ProtectedCapsulePostdeleteReconciler) -> None:
        if (
            not isinstance(reconciler, ProtectedCapsulePostdeleteReconciler)
            or not isinstance(reconciler._db, sqlite3.Connection)
            or reconciler._db is not reconciler._dispatcher._db
            or reconciler._db is not reconciler._dispatcher._predelete._db
            or reconciler._db.in_transaction
        ):
            raise LauncherReadinessPreflightError(
                "exact protected postdelete connection required"
            )
        self._reconciler = reconciler
        self._db = reconciler._db
        try:
            self._db.execute(_SCHEMA)
        except sqlite3.Error as error:
            raise LauncherReadinessPreflightError(
                "protected launcher preflight table unavailable"
            ) from error

    def _authorize(self, install: str, operation: str, context: object) -> None:
        try:
            self._reconciler._authorize(install, operation, context)
        except CapsulePostdeleteReconciliationError as error:
            raise LauncherReadinessPreflightError(
                "independent launch preflight authorization refused"
            ) from error

    def observe(
        self, installation_id: str, *, service_context: object
    ) -> ProtectedLauncherReadinessPreflight | None:
        if type(installation_id) is not str or _TX.fullmatch(installation_id) is None:
            raise LauncherReadinessPreflightError("invalid installation identity")
        self._authorize(installation_id, "observe_launcher_preflight", service_context)
        try:
            row = self._db.execute(
                "SELECT * FROM plan_launcher_readiness_preflight_v1 "
                "WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise LauncherReadinessPreflightError(
                "protected launcher preflight unreadable"
            ) from error
        if row is None:
            return None
        try:
            result = ProtectedLauncherReadinessPreflight(*row)
        except (TypeError, ValueError) as error:
            raise LauncherReadinessPreflightError(
                "launcher preflight record malformed"
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
            raise LauncherReadinessPreflightError(
                "durable launcher preflight record corrupt"
            )
        return result

    def prepare_once(
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
        *,
        service_context: object,
        independently_read_postdelete: IndependentCapsuleDeleteReader,
        independently_confirm_delete_termination: IndependentDeleteTerminationReader,
        independently_read_launcher: IndependentLauncherReadinessReader,
        witness_transport: CheckpointWitnessTransport,
        pinned_public_key: bytes,
        now: datetime,
    ) -> ProtectedLauncherReadinessPreflight:
        """Record diagnostic once; never dispatch actual launch or filesystem I/O."""
        convergence_api = (
            self._reconciler._dispatcher._predelete._clearance._convergence
        )
        try:
            request = convergence_api._basis(
                request_bytes, reservation, preclaim, record, intent, marker, claim
            )
        except LocalConvergenceError as error:
            raise LauncherReadinessPreflightError(
                "invalid protected launcher preflight basis"
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
        ):
            raise LauncherReadinessPreflightError(
                "invalid protected postdelete certificate or deletion chain"
            )
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
            raise LauncherReadinessPreflightError(
                "independent launcher preflight runtime missing"
            )
        self._authorize(
            request.installation_id,
            "prepare_launcher_readiness_once",
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
                protected_actual = (
                    convergence_api.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._reconciler._dispatcher._predelete._clearance.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._reconciler._dispatcher._predelete.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._reconciler._dispatcher.observe(
                        request.installation_id, service_context=service_context
                    ),
                    self._reconciler.observe(
                        request.installation_id, service_context=service_context
                    ),
                )
                protected_expected = (
                    convergence,
                    clearance_preflight,
                    predelete_marker,
                    delete_claim,
                    postdelete_certificate,
                )
                if any(
                    type(a) is not type(b) or a != b
                    for a, b in zip(protected_actual, protected_expected)
                ):
                    raise LauncherReadinessPreflightError(
                        "durable protected launcher preflight chain changed"
                    )
                if (
                    self._db.execute(
                        "SELECT 1 FROM plan_launcher_readiness_preflight_v1 "
                        "WHERE installation_id = ?",
                        (request.installation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise LauncherReadinessPreflightError(
                        "launcher preflight already recorded; no replay"
                    )

                def physical_sample() -> tuple[
                    IndependentLauncherReadinessInspection, str, str, str
                ]:
                    try:
                        term = independently_confirm_delete_termination(
                            request, service_context
                        )
                        post = independently_read_postdelete(request, service_context)
                        launch = independently_read_launcher(request, service_context)
                    except Exception as error:
                        raise LauncherReadinessPreflightError(
                            "independent launcher/physical inspection unavailable"
                        ) from error
                    if not _exact_termination(term, request, delete_claim):
                        raise LauncherReadinessPreflightError(
                            "delete termination, OS fencing or custody uncertain"
                        )
                    try:
                        status, observed = _classify_postdelete(
                            post, request, reservation, intent, delete_claim
                        )
                    except CapsulePostdeleteReconciliationError as error:
                        raise LauncherReadinessPreflightError(
                            "changed active successor or unsafe capsule readback"
                        ) from error
                    if status != _ABSENT or observed is not None:
                        raise LauncherReadinessPreflightError(
                            "capsule is not absent; manual reconciliation required"
                        )
                    if not _exact_runtime(
                        launch, request, reservation, intent, delete_claim
                    ):
                        raise LauncherReadinessPreflightError(
                            "unverified launcher runtime or unsafe execution state"
                        )
                    assert isinstance(launch, IndependentLauncherReadinessInspection)
                    runtime_hash = _sha(
                        json.dumps(
                            {f.name: getattr(launch, f.name) for f in fields(launch)},
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                        ).encode("ascii")
                    )
                    assert isinstance(term.deletion_fence_sha256, str)
                    assert isinstance(term.deletion_termination_sha256, str)
                    delete_evidence = _sha(
                        bytes.fromhex(term.deletion_fence_sha256)
                        + bytes.fromhex(term.deletion_termination_sha256)
                        + request.successor_receipt_bytes
                        + bytes.fromhex(delete_claim.capsule_identity_sha256)
                    )
                    return (
                        launch,
                        runtime_hash,
                        delete_evidence,
                        term.deletion_fence_sha256,
                    )

                first = physical_sample()
                try:
                    convergence_api._dispatch._prewrite._signed(
                        request,
                        reservation,
                        witness_transport,
                        pinned_public_key,
                        now,
                    )
                except Exception as error:
                    raise LauncherReadinessPreflightError(
                        "fresh signed successor head unavailable"
                    ) from error
                second = physical_sample()
                if first != second:
                    raise LauncherReadinessPreflightError(
                        "launcher or postdelete physical evidence drifted"
                    )
                entry = ProtectedLauncherReadinessPreflight(
                    request.installation_id,
                    reservation.transaction_id,
                    reservation.request_sha256,
                    request.successor_sha256,
                    reservation.successor_generation,
                    reservation.witness_revision,
                    _record_hash(postdelete_certificate),
                    _claim_hash(delete_claim),
                    intent.target_identity_sha256,
                    delete_claim.capsule_identity_sha256,
                    first[1],
                    first[2],
                )
                self._db.execute(
                    "INSERT INTO plan_launcher_readiness_preflight_v1 "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.installation_id,
                        entry.transaction_id,
                        entry.request_sha256,
                        entry.successor_sha256,
                        entry.successor_generation,
                        entry.witness_revision,
                        entry.postdelete_certificate_sha256,
                        entry.delete_claim_sha256,
                        entry.target_identity_sha256,
                        entry.capsule_identity_sha256,
                        entry.launcher_runtime_evidence_sha256,
                        entry.postdelete_recheck_evidence_sha256,
                        entry.status,
                    ),
                )
                self._db.execute("COMMIT")
                return entry
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except LauncherReadinessPreflightError:
            raise
        except (
            sqlite3.Error,
            CapsulePostdeleteReconciliationError,
            LocalConvergenceError,
            LocalPrewriteUncertaintyError,
        ) as error:
            raise LauncherReadinessPreflightError(
                "launcher preflight state uncertain, no execution authorized"
            ) from error


__all__ = (
    "LauncherReadinessPreflightError",
    "IndependentLauncherReadinessInspection",
    "IndependentLauncherReadinessReader",
    "ProtectedLauncherReadinessPreflight",
    "ProtectedLauncherReadinessPreflightLedger",
)
