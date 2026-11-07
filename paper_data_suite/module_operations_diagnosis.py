"""Explicit, non-authorizing Suite projection of Core operations-profile diagnosis.

Only callers that deliberately opt into Core's executable profile-factory
inspection should call this module. Metadata-only home discovery remains in
``module_operations_inventory`` and never calls this path.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol

from paper_data_suite.applications import ApplicationLaunchStatus
from paper_data_suite.module_operations_inventory import (
    MetadataState,
    ModuleOperationsMetadataInventory,
)

_GROUP = "paper_data_suite.module_operations"
_KIND = "module_operations"
_MAX_RESULTS = 512

ProfileState = Literal[
    "not_declared",
    "metadata_unqualified",
    "diagnosis_unavailable",
    "diagnosis_missing",
    "ambiguous",
    "invalid_diagnostic",
    "owner_mismatch",
    "valid",
    "entry_point_name_invalid",
    "load_failed",
    "not_callable",
    "call_failed",
    "profile_invalid",
    "identity_mismatch",
    "core_incompatible",
    "identity_conflict",
]

_CODE_STATES: dict[str, ProfileState] = {
    "provider.valid": "valid",
    "provider.entry_point_name_invalid": "entry_point_name_invalid",
    "provider.load_failed": "load_failed",
    "provider.not_callable": "not_callable",
    "provider.call_failed": "call_failed",
    "provider.profile_invalid": "profile_invalid",
    "provider.identity_mismatch": "identity_mismatch",
    "provider.core_incompatible": "core_incompatible",
    "provider.identity_conflict": "identity_conflict",
}


class ProviderDiagnosticMetadataLike(Protocol):
    """Core metadata fields; targets are never stored in the projection."""

    provider_kind: str
    entry_point_group: str
    entry_point_name: str
    distribution_name: str | None


class ProviderDiagnosticLike(Protocol):
    """Only documented public Core result fields are inspected."""

    metadata: ProviderDiagnosticMetadataLike
    code: str
    stage: str
    declared_identity: str | None
    registry_conflict: bool
    profile_validation: str
    core_compatibility: str
    load_attempted: bool
    load_succeeded: bool
    provider_call_attempted: bool
    provider_call_succeeded: bool
    validated_profile: object | None


@dataclass(frozen=True, slots=True)
class ModuleOperationsProfileRow:
    """Profile-factory status, not readiness, attention or launch authority."""

    component_id: str
    display_name: str
    expected_distribution: str
    launch_state: ApplicationLaunchStatus | None
    metadata_state: MetadataState
    profile_state: ProfileState
    readiness_declared: bool | None = None
    attention_declared: bool | None = None
    readiness_evaluated: bool = False
    attention_evaluated: bool = False
    provenance_qualified: bool = False


@dataclass(frozen=True, slots=True)
class ModuleOperationsProfileInventory:
    """Six approved rows in Suite order plus unapproved diagnostic count."""

    applications: tuple[ModuleOperationsProfileRow, ...]
    unapproved_diagnostics: int
    diagnosis_available: bool

    def for_component(self, component_id: str) -> ModuleOperationsProfileRow | None:
        return next(
            (row for row in self.applications if row.component_id == component_id),
            None,
        )


def _distribution_key(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _diagnose_installed_profiles() -> Iterable[ProviderDiagnosticLike]:
    """DEEP: Core loads and calls installed zero-argument provider factories."""
    core = import_module("pds_core.provider_diagnostics")
    diagnose = getattr(core, "diagnose_core_providers")
    return diagnose(provider_kind=_KIND)  # type: ignore[no-any-return]


def _safe_diagnostic(
    result: object, *, component_id: str, distribution: str
) -> tuple[ProfileState, bool | None, bool | None]:
    """Fail closed if Core's result is malformed or wrong-owner metadata."""
    try:
        metadata = result.metadata  # type: ignore[attr-defined]
        kind = metadata.provider_kind
        group = metadata.entry_point_group
        name = metadata.entry_point_name
        owner = metadata.distribution_name
        code = result.code  # type: ignore[attr-defined]
        stage = result.stage  # type: ignore[attr-defined]
    except Exception:
        return "invalid_diagnostic", None, None
    if (
        kind != _KIND
        or group != _GROUP
        or type(name) is not str
        or name != component_id
        or type(code) is not str
        or code not in _CODE_STATES
        or type(stage) is not str
        or not stage
    ):
        return "invalid_diagnostic", None, None
    if (
        type(owner) is not str
        or _distribution_key(owner) != _distribution_key(distribution)
    ):
        return "owner_mismatch", None, None
    state = _CODE_STATES[code]
    if state != "valid":
        return state, None, None

    try:
        if not (
            result.stage == "valid"  # type: ignore[attr-defined]
            and result.declared_identity == component_id  # type: ignore[attr-defined]
            and result.registry_conflict is False  # type: ignore[attr-defined]
            and result.profile_validation == "passed"  # type: ignore[attr-defined]
            and result.core_compatibility == "passed"  # type: ignore[attr-defined]
            and result.load_attempted is True  # type: ignore[attr-defined]
            and result.load_succeeded is True  # type: ignore[attr-defined]
            and result.provider_call_attempted is True  # type: ignore[attr-defined]
            and result.provider_call_succeeded is True  # type: ignore[attr-defined]
        ):
            return "invalid_diagnostic", None, None
        profile = result.validated_profile  # type: ignore[attr-defined]
        if profile is None or profile.module_id != component_id:
            return "invalid_diagnostic", None, None
        versions = profile.supported_core_operations_contract_versions
        if type(versions) is not frozenset or "1" not in versions:
            return "invalid_diagnostic", None, None
        readiness = profile.readiness_provider
        attention = profile.attention_provider
        if (readiness is not None and not callable(readiness)) or (
            attention is not None and not callable(attention)
        ):
            return "invalid_diagnostic", None, None
        if readiness is None and attention is None:
            return "invalid_diagnostic", None, None
    except Exception:
        return "invalid_diagnostic", None, None
    return "valid", readiness is not None, attention is not None


def collect_module_operations_profile_diagnosis(
    *,
    metadata_inventory: ModuleOperationsMetadataInventory,
    diagnose: Callable[[], Iterable[ProviderDiagnosticLike]] | None = None,
) -> ModuleOperationsProfileInventory:
    """Explicitly diagnose Core operations profiles without evaluating callbacks.

    This must be invoked only by a deliberate diagnostic/qualification action:
    Core executes installed Python profile factories, without an OS sandbox.
    A successful profile says nothing about launch, provenance, or readiness.
    """
    if not isinstance(metadata_inventory, ModuleOperationsMetadataInventory):
        raise TypeError("metadata_inventory must be the metadata-only inventory")
    if not metadata_inventory.inspection_available:
        # Do not execute installed provider factories after metadata inspection
        # itself failed; an explicit retry must begin with a healthy census.
        return ModuleOperationsProfileInventory(
            applications=tuple(
                ModuleOperationsProfileRow(
                    row.component_id,
                    row.display_name,
                    row.expected_distribution,
                    row.launch_state,
                    row.metadata_state,
                    "metadata_unqualified",
                )
                for row in metadata_inventory.applications
            ),
            unapproved_diagnostics=0,
            diagnosis_available=False,
        )
    try:
        reader = _diagnose_installed_profiles if diagnose is None else diagnose
        observed = tuple(reader())
        if len(observed) > _MAX_RESULTS:
            raise ValueError("unbounded provider diagnostics")
    except Exception:
        return ModuleOperationsProfileInventory(
            applications=tuple(
                ModuleOperationsProfileRow(
                    row.component_id,
                    row.display_name,
                    row.expected_distribution,
                    row.launch_state,
                    row.metadata_state,
                    "diagnosis_unavailable",
                )
                for row in metadata_inventory.applications
            ),
            unapproved_diagnostics=0,
            diagnosis_available=False,
        )

    allowed_ids = {row.component_id for row in metadata_inventory.applications}
    by_id: dict[str, list[object]] = {key: [] for key in allowed_ids}
    unknown_count = 0
    for result in observed:
        try:
            name = result.metadata.entry_point_name
        except Exception:
            unknown_count += 1
            continue
        if type(name) is str and name in by_id:
            by_id[name].append(result)
        else:
            unknown_count += 1

    projections: list[ModuleOperationsProfileRow] = []
    for row in metadata_inventory.applications:
        matching = by_id[row.component_id]
        state: ProfileState
        readiness: bool | None = None
        attention: bool | None = None
        if row.metadata_state == "not_declared":
            state = "not_declared" if not matching else "metadata_unqualified"
        elif row.metadata_state != "declared_unvalidated":
            state = "metadata_unqualified"
            if len(matching) == 1:
                outcome, _, _ = _safe_diagnostic(
                    matching[0],
                    component_id=row.component_id,
                    distribution=row.expected_distribution,
                )
                if outcome == "identity_conflict":
                    state = "identity_conflict"
        elif not matching:
            state = "diagnosis_missing"
        elif len(matching) != 1:
            state = "ambiguous"
        else:
            state, readiness, attention = _safe_diagnostic(
                matching[0],
                component_id=row.component_id,
                distribution=row.expected_distribution,
            )
        projections.append(
            ModuleOperationsProfileRow(
                component_id=row.component_id,
                display_name=row.display_name,
                expected_distribution=row.expected_distribution,
                launch_state=row.launch_state,
                metadata_state=row.metadata_state,
                profile_state=state,
                readiness_declared=readiness,
                attention_declared=attention,
            )
        )
    return ModuleOperationsProfileInventory(
        applications=tuple(projections),
        unapproved_diagnostics=unknown_count,
        diagnosis_available=True,
    )
