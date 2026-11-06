"""Issue #49 Slice 67: bind a signed update plan to observed candidate bytes.

This is read-only orchestration of independently reauthenticated evidence.
Neither a verified wheelhouse nor an inspected isolated pip/native candidate
proves protected ACTIVE installation state or authorizes software execution.
The witness and bytes must be reverified under cooperating update locks before
any future teacher-approved activation or receipt commit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from packaging.utils import canonicalize_name

from paper_data_suite.evergreen_catalog_stage_correlation import (
    CatalogStageCorrelation,
    CatalogStageCorrelationError,
    CatalogStagedWheel,
    inspect_catalog_bound_staged_bytes,
)
from paper_data_suite.evergreen_catalog_state import CatalogSnapshot
from paper_data_suite.evergreen_catalog_verification import TrustedKeyring
from paper_data_suite.evergreen_install_records import (
    PreparedRecordError,
    UnverifiedPreparedRecord,
    verify_prepared_record_against_wheelhouse,
)
from paper_data_suite.evergreen_plan_wheelhouse_preflight import (
    PlanWheelhousePreflight,
    PlanWheelhousePreflightError,
    inspect_plan_bound_wheelhouse,
)
from paper_data_suite.evergreen_update_journal import (
    UpdateJournalError,
    _relative_child,
    _safe_root,
)
from paper_data_suite.evergreen_witness_selected_stage import (
    WitnessSelectedStageObservation,
)


class PlanStagedCandidateError(ValueError):
    """Plan, signed wheel inputs and installed candidate bytes do not agree."""


@dataclass(frozen=True, slots=True)
class PlanStagedCandidateObservation:
    """Transient, non-authoritative proof that staged files match a plan."""

    transaction_id: str
    baseline_transaction_id: str
    baseline_witness_revision: int
    registry_payload_sha256: str
    signed_lock_payload_sha256: str
    prepared_record_sha256: str
    pip_inventory_sha256: str
    native_payload_sha256: str
    modules: tuple[CatalogStagedWheel, ...]
    external_wheels: tuple[tuple[str, str, str], ...]
    status: str = "PLAN_BOUND_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
    authority: str = "NO_ACTIVE_INSTALL_RECEIPT_LAUNCH_OR_ACTIVATION_AUTHORITY"


def _expected_wheels(
    checked: PlanWheelhousePreflight,
) -> tuple[set[tuple[str, str, str, str]], set[tuple[str, str, str]]]:
    """Bind every selected PDS wheel and each signed transitive dependency."""
    pds = {
        (
            str(canonicalize_name(item.distribution)),
            item.version,
            item.filename,
            item.sha256,
        )
        for item in checked.pds_wheels
    }
    external = {
        (str(canonicalize_name(distribution)), version, digest)
        for distribution, version, digest in checked.external_wheels
    }
    if (
        not pds
        or len(pds) != len(checked.pds_wheels)
        or len(external) != len(checked.external_wheels)
        or {row[0] for row in pds} & {row[0] for row in external}
    ):
        raise PlanStagedCandidateError("ambiguous plan wheel identities")
    return pds, external


def _match_prepared(
    checked: PlanWheelhousePreflight,
    record: UnverifiedPreparedRecord,
) -> None:
    pds, external = _expected_wheels(checked)
    rows = {
        (
            str(canonicalize_name(item.distribution)),
            item.version,
            item.filename,
            item.sha256,
        )
        for item in record.wheels
    }
    if len(rows) != len(record.wheels):
        raise PlanStagedCandidateError("duplicate prepared wheel identity")
    normalized_roots = {str(canonicalize_name(item)) for item in record.roots}
    if (
        record.registry_payload_sha256 != checked.registry_payload_sha256
        or record.lock_payload_sha256 != checked.signed_lock_payload_sha256
        or record.lock_revision != checked.signed_lock_revision
        or record.python_minor != checked.python_minor
        or record.platform != checked.platform_tag
        or normalized_roots != {item[0] for item in pds}
        or len(normalized_roots) != len(record.roots)
        or not pds <= rows
        or {(name, version, digest) for name, version, _, digest in rows - pds}
        != external
        or len(rows) != len(pds) + len(external)
    ):
        raise PlanStagedCandidateError("prepared transaction differs from signed plan")


def _match_stage(
    checked: PlanWheelhousePreflight,
    prepared: UnverifiedPreparedRecord,
    observed: CatalogStageCorrelation,
) -> None:
    expected = {
        (
            wheel.component_id,
            str(canonicalize_name(wheel.distribution)),
            wheel.version,
            wheel.sha256,
            wheel.publisher_payload_sha256,
        )
        for wheel in checked.pds_wheels
    }
    actual = {
        (
            wheel.component_id,
            str(canonicalize_name(wheel.distribution)),
            wheel.version,
            wheel.wheel_sha256,
            wheel.publisher_payload_sha256,
        )
        for wheel in observed.modules
    }
    if (
        observed.transaction_id != prepared.transaction_id
        or observed.registry_payload_sha256 != checked.registry_payload_sha256
        or len(actual) != len(observed.modules)
        or expected != actual
        or observed.status != "SIGNED_STAGED_BYTES_OBSERVED_NOT_ACTIVE"
        or observed.authority != "NO_LAUNCH_RECEIPT_ACTIVATION_OR_UPDATE_AUTHORITY"
    ):
        raise PlanStagedCandidateError("audited staged bytes differ from signed plan")


def inspect_plan_bound_staged_candidate(
    snapshot: CatalogSnapshot,
    witnessed: WitnessSelectedStageObservation,
    software_root: Path,
    *,
    classroom_workspace: Path,
    stage_root: Path,
    wheelhouse: Path,
    prepared_record: bytes,
    requested_targets: dict[str, str | None],
    python_minor: str,
    platform_tag: str,
    registry_envelope: bytes,
    lock_envelope: bytes,
    module_envelopes: dict[str, bytes],
    native_envelope: bytes,
    trust: TrustedKeyring,
    now: datetime,
    layout: str | None = None,
) -> PlanStagedCandidateObservation:
    """Reconcile plan, complete wheelhouse and existing isolated installed bytes.

    The caller must have independently authenticated the baseline witness and
    publisher trust. Nothing is written, staged or executed here. A positive
    observation expires as soon as any inputs or selected bytes can change.
    """
    if (
        not isinstance(snapshot, CatalogSnapshot)
        or not isinstance(witnessed, WitnessSelectedStageObservation)
        or not isinstance(software_root, Path)
        or not isinstance(classroom_workspace, Path)
        or not isinstance(stage_root, Path)
        or not isinstance(wheelhouse, Path)
        or not isinstance(trust, TrustedKeyring)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or any(
            type(blob) is not bytes
            for blob in (
                prepared_record,
                registry_envelope,
                lock_envelope,
                native_envelope,
            )
        )
        or type(module_envelopes) is not dict
        or not 1 <= len(module_envelopes) <= 32
        or any(
            type(key) is not str or type(value) is not bytes
            for key, value in module_envelopes.items()
        )
        or layout not in (None, "windows", "posix")
    ):
        raise PlanStagedCandidateError("invalid plan-stage verification inputs")
    try:
        root = _safe_root(software_root, classroom_workspace)
        stage = stage_root.absolute()
        wheels = wheelhouse.absolute()
        stage_relative = _relative_child(root, stage)
        wheels_relative = _relative_child(root, wheels)
        if (
            stage_relative == wheels_relative
            or stage in wheels.parents
            or wheels in stage.parents
        ):
            raise PlanStagedCandidateError("stage and wheelhouse must be isolated")

        def signed_plan() -> PlanWheelhousePreflight:
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
            if (
                checked.baseline_transaction_id != witnessed.transaction_id
                or checked.baseline_witness_revision != witnessed.witness_revision
                or checked.registry_payload_sha256 != snapshot.registry.payload_sha256
            ):
                raise PlanStagedCandidateError("plan baseline or registry has drifted")
            return checked

        def prepared() -> UnverifiedPreparedRecord:
            return verify_prepared_record_against_wheelhouse(
                prepared_record,
                wheels,
                lock_envelope=lock_envelope,
                registry_envelope=registry_envelope,
                trust=trust,
                now=now,
            )

        def staged() -> CatalogStageCorrelation:
            return inspect_catalog_bound_staged_bytes(
                snapshot,
                stage,
                wheels,
                prepared_record=prepared_record,
                registry_envelope=registry_envelope,
                lock_envelope=lock_envelope,
                module_envelopes=module_envelopes,
                native_envelope=native_envelope,
                trust=trust,
                now=now,
                layout=layout,
            )

        first_plan = signed_plan()
        first_record = prepared()
        _match_prepared(first_plan, first_record)
        first_stage = staged()
        _match_stage(first_plan, first_record, first_stage)
        second_plan = signed_plan()
        second_record = prepared()
        second_stage = staged()
        if (
            first_plan != second_plan
            or first_record != second_record
            or first_stage != second_stage
        ):
            raise PlanStagedCandidateError(
                "candidate or signed plan changed during audit"
            )
        _match_prepared(second_plan, second_record)
        _match_stage(second_plan, second_record, second_stage)
        if (
            _relative_child(root, stage) != stage_relative
            or _relative_child(root, wheels) != wheels_relative
        ):
            raise PlanStagedCandidateError("candidate paths changed during audit")
        return PlanStagedCandidateObservation(
            second_record.transaction_id,
            witnessed.transaction_id,
            witnessed.witness_revision,
            second_plan.registry_payload_sha256,
            second_plan.signed_lock_payload_sha256,
            hashlib.sha256(prepared_record).hexdigest(),
            second_stage.pip_inventory_sha256,
            second_stage.native_payload_sha256,
            second_stage.modules,
            second_plan.external_wheels,
        )
    except (
        PlanWheelhousePreflightError,
        PreparedRecordError,
        CatalogStageCorrelationError,
        UpdateJournalError,
        OSError,
    ) as error:
        raise PlanStagedCandidateError(
            "signed plan, prepared transaction or staged bytes refused"
        ) from error


__all__ = (
    "PlanStagedCandidateError",
    "PlanStagedCandidateObservation",
    "inspect_plan_bound_staged_candidate",
)
