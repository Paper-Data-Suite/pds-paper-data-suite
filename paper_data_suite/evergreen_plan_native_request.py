"""Issue #49 Slice 69: produce an UNSIGNED native-evidence signing request.

Local hashes, even when observed after signed publisher/pip checks, do not
establish native-code provenance. This module cannot sign, install, launch,
activate, write a receipt or entrust local observations with root authority.
An independent authorized signer MUST authenticate the payload and provenance
before emitting the root-quorum signed envelope required by existing auditors.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    UnverifiedPreparedRecord,
    verify_prepared_record_against_wheelhouse,
)
from paper_data_suite.evergreen_native_evidence import (
    NativeEvidenceError,
)
from paper_data_suite.evergreen_native_evidence import (
    _digest as _native_digest,
)
from paper_data_suite.evergreen_plan_stage_installer import IsolatedPlanStageResult
from paper_data_suite.evergreen_plan_staged_candidate import (
    PlanStagedCandidateError,
    _match_prepared,
)
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflight,
    PlanWheelhousePreflightError,
    inspect_plan_bound_wheelhouse,
)
from paper_data_suite.evergreen_publisher_pip_preflight import (
    ObservedPublisherPipCandidate,
    PublisherPipPreflightError,
    audit_publisher_bound_pip_candidate,
)
from paper_data_suite.evergreen_staged_runtime import (
    StagedRuntimeError,
    StagedRuntimeInspection,
    inspect_staged_virtualenv,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)

_MAX_NATIVE: Final = 64 * 1024 * 1024
_MAX_FILES: Final = 64
_MAX_PAYLOAD: Final = 24 * 1024
_TX: Final = re.compile(r"[0-9a-f]{32}\Z")
_SHA: Final = re.compile(r"[0-9a-f]{64}\Z")
_PATH: Final = re.compile(r"(?:Scripts|bin)/[A-Za-z][A-Za-z0-9._-]{0,79}\Z")


class NativeSigningRequestError(ValueError):
    """Cannot prepare a consistent, bounded, unsigned native signing request."""


@dataclass(frozen=True, slots=True)
class UnsignedNativeSigningRequest:
    """Canonical unsigned payload; NEVER an attestation or activation token."""

    transaction_id: str
    payload: bytes
    payload_sha256: str
    file_count: int
    signed_lock_payload_sha256: str
    pip_inventory_sha256: str
    status: str = "UNSIGNED_NATIVE_EVIDENCE_REQUEST_REQUIRES_INDEPENDENT_REVIEW"
    authority: str = "NO_SIGNING_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"


def _clock(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NativeSigningRequestError(f"{label} requires an aware datetime")
    utc = value.astimezone(timezone.utc)
    if utc.microsecond:
        raise NativeSigningRequestError(f"{label} requires whole seconds")
    return utc


def _native_paths(
    stage: Path, inspection: StagedRuntimeInspection, layout: str | None
) -> tuple[str, ...]:
    windows = layout == "windows" or (layout is None and sys.platform == "win32")
    names = {"Scripts/python.exe" if windows else "bin/python"}
    for launcher in inspection.console_launchers:
        try:
            relative = launcher.path.relative_to(stage).as_posix()
        except ValueError as error:
            raise NativeSigningRequestError(
                "console launcher escapes candidate"
            ) from error
        names.add(relative)
    if windows and (stage / "Scripts/pythonw.exe").exists():
        names.add("Scripts/pythonw.exe")
    if (
        not 1 <= len(names) <= _MAX_FILES
        or any(_PATH.fullmatch(name) is None for name in names)
        or len({name.lower() for name in names}) != len(names)
    ):
        raise NativeSigningRequestError("unsafe or colliding staged native paths")
    return tuple(sorted(names))


def _native_rows(
    stage: Path, names: tuple[str, ...]
) -> tuple[tuple[str, str, int], ...]:
    rows: list[tuple[str, str, int]] = []
    for name in names:
        path = stage / name
        try:
            before = path.lstat()
            if not 1 <= before.st_size <= _MAX_NATIVE:
                raise NativeSigningRequestError("native executable size invalid")
            digest = _native_digest(path, stage_root=stage, size=before.st_size)
            after = path.lstat()
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ino != after.st_ino
            ):
                raise NativeSigningRequestError("native bytes changed while hashing")
        except OSError as error:
            raise NativeSigningRequestError(
                "native executable cannot be read"
            ) from error
        if _SHA.fullmatch(digest) is None:
            raise NativeSigningRequestError("native hash observation invalid")
        rows.append((name, digest, before.st_size))
    return tuple(rows)


def _measure_once(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    installed: IsolatedPlanStageResult,
    wheels: Path,
    *,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None,
) -> tuple[
    PlanWheelhousePreflight,
    UnverifiedPreparedRecord,
    ObservedPublisherPipCandidate,
    tuple[tuple[str, str, int], ...],
]:
    checked = inspect_plan_bound_wheelhouse(
        snapshot,
        witnessed,
        wheels,
        requested_targets=requested_targets,
        python_minor=python_minor,
        platform_tag=platform_tag,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        module_envelopes=module_envelopes,
        trust=trust,
        now=now,
    )
    prepared = verify_prepared_record_against_wheelhouse(
        installed.prepared_record,
        wheels,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        trust=trust,
        now=now,
    )
    _match_prepared(checked, prepared)
    pip = audit_publisher_bound_pip_candidate(
        installed.stage_root,
        wheels,
        prepared_record=installed.prepared_record,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        module_envelopes=module_envelopes,
        trust=trust,
        now=now,
        layout=layout,
    )
    runtime = inspect_staged_virtualenv(
        installed.stage_root,
        wheels,
        prepared_record=installed.prepared_record,
        registry_envelope=registry_envelope,
        lock_envelope=lock_envelope,
        trust=trust,
        now=now,
        layout=layout,
    )
    if (
        prepared.transaction_id != installed.transaction_id
        or checked.baseline_transaction_id != witnessed.transaction_id
        or checked.baseline_witness_revision != witnessed.witness_revision
        or checked.registry_payload_sha256 != snapshot.registry.payload_sha256
        or checked.signed_lock_payload_sha256 != installed.signed_lock_payload_sha256
        or pip.transaction_id != installed.transaction_id
        or pip.stage_root != installed.stage_root
        or pip.wheelhouse != wheels
        or pip.pip_inventory_sha256 != installed.pip_inventory_sha256
        or pip.registry_payload_sha256 != checked.registry_payload_sha256
        or pip.lock_payload_sha256 != checked.signed_lock_payload_sha256
        or runtime.transaction_id != installed.transaction_id
        or runtime.stage_root != installed.stage_root
        or installed.baseline_transaction_id != witnessed.transaction_id
        or installed.baseline_witness_revision != witnessed.witness_revision
    ):
        raise NativeSigningRequestError("staged installation or signed plan drifted")
    rows = _native_rows(
        installed.stage_root,
        _native_paths(installed.stage_root, runtime, layout),
    )
    return checked, prepared, pip, rows


def prepare_unsigned_native_evidence_request(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    installed: IsolatedPlanStageResult,
    software_root: Path,
    *,
    classroom_workspace: Path,
    wheelhouse: Path,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    trust: TrustedKeyring,
    now: datetime,
    revision: int,
    issued_at: datetime,
    expires_at: datetime,
    layout: str | None = None,
) -> UnsignedNativeSigningRequest:
    """Create a canonical unsigned request after two independent physical audits.

    Returned bytes are not trusted, do not carry a signature, and are not
    eligible for the native verifier until independently reviewed and signed.
    The signer must separately establish native executable provenance and
    replay protection; locally measured hashes alone never suffice.
    """
    if (
        not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(installed, IsolatedPlanStageResult)
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or type(requested_targets) is not dict
        or type(registry_envelope) is not bytes
        or type(lock_envelope) is not bytes
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= 32
        or any(
            type(k) is not str or type(v) is not bytes
            for k, v in module_envelopes.items()
        )
        or type(revision) is not int
        or not 1 <= revision <= 2**53 - 1
        or layout not in (None, "windows", "posix")
    ):
        raise NativeSigningRequestError("invalid unsigned signing-request inputs")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise NativeSigningRequestError("now requires an aware datetime")
    now_utc = now.astimezone(timezone.utc)
    issued = _clock(issued_at, "issuance")
    expires = _clock(expires_at, "expiry")
    if not issued <= now_utc < expires or expires - issued > timedelta(days=30):
        raise NativeSigningRequestError("invalid native evidence validity window")
    if (
        type(installed.transaction_id) is not str
        or _TX.fullmatch(installed.transaction_id) is None
    ):
        raise NativeSigningRequestError("invalid installed candidate transaction")
    try:
        root = _safe_root(software_root, classroom_workspace)
        stage = installed.stage_root.absolute()
        wheels = wheelhouse.absolute()
        _relative_child(root, stage)
        _relative_child(root, wheels)
        if stage != root / "candidate-builds" / installed.transaction_id:
            raise NativeSigningRequestError("candidate path differs from transaction")
        if stage == wheels or stage in wheels.parents or wheels in stage.parents:
            raise NativeSigningRequestError("native stage and wheelhouse overlap")
        first = _measure_once(
            snapshot,
            witnessed,
            installed,
            wheels,
            requested_targets=requested_targets,
            python_minor=python_minor,
            platform_tag=platform_tag,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            trust=trust,
            now=now,
            layout=layout,
        )
        second = _measure_once(
            snapshot,
            witnessed,
            installed,
            wheels,
            requested_targets=requested_targets,
            python_minor=python_minor,
            platform_tag=platform_tag,
            registry_envelope=registry_envelope,
            lock_envelope=lock_envelope,
            module_envelopes=module_envelopes,
            trust=trust,
            now=now,
            layout=layout,
        )
        if first != second:
            raise NativeSigningRequestError("signed inputs or native bytes changed")
        checked, record, pip, binaries = second
        doc = {
            "record_type": "pds_evergreen_staged_native_evidence",
            "schema_version": 1,
            "revision": revision,
            "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "transaction_id": record.transaction_id,
            "registry_payload_sha256": record.registry_payload_sha256,
            "lock_payload_sha256": record.lock_payload_sha256,
            "trust_fingerprint": record.trust_fingerprint,
            "python_minor": record.python_minor,
            "platform": record.platform,
            "files": [
                {"relative_path": name, "sha256": digest, "size": size}
                for name, digest, size in binaries
            ],
        }
        data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        if not 1 <= len(data) <= _MAX_PAYLOAD:
            raise NativeSigningRequestError("unsigned evidence payload exceeds limit")
        if (
            checked.signed_lock_payload_sha256 != record.lock_payload_sha256
            or pip.pip_inventory_sha256 != installed.pip_inventory_sha256
        ):
            raise NativeSigningRequestError("final unsigned evidence binding invalid")
        return UnsignedNativeSigningRequest(
            record.transaction_id,
            data,
            hashlib.sha256(data).hexdigest(),
            len(binaries),
            checked.signed_lock_payload_sha256,
            pip.pip_inventory_sha256,
        )
    except (
        PlanWheelhousePreflightError,
        PreparedRecordError,
        PlanStagedCandidateError,
        PublisherPipPreflightError,
        StagedRuntimeError,
        NativeEvidenceError,
        UpdateJournalError,
        OSError,
    ) as error:
        raise NativeSigningRequestError(
            "native signing request verification refused"
        ) from error


__all__ = (
    "NativeSigningRequestError",
    "UnsignedNativeSigningRequest",
    "prepare_unsigned_native_evidence_request",
)
