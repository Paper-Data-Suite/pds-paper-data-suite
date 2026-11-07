"""Suite #16: metadata-only, non-authorizing operations provider census.

Core owns entry-point enumeration and provider validation. Suite associates the
observed metadata with its *approved* application identities and never loads a
provider from this path. This is not a launch or readiness qualification.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol

from paper_data_suite.applications import ApplicationInventory, ApplicationLaunchStatus
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS

_GROUP = "paper_data_suite.module_operations"
_KIND = "module_operations"
_MAX_ROWS = 512

MetadataState = Literal[
    "not_declared",
    "declared_unvalidated",
    "owner_mismatch",
    "ambiguous",
    "invalid_metadata",
    "inspection_unavailable",
]


class ProviderMetadataLike(Protocol):
    """Public, bounded Core metadata shape; no provider object or callable."""

    provider_kind: str
    entry_point_group: str
    entry_point_name: str
    entry_point_target: str
    distribution_name: str | None


@dataclass(frozen=True, slots=True)
class ModuleOperationsMetadataRow:
    """One approved module's *observed* entry-point status, not authority."""

    component_id: str
    display_name: str
    expected_distribution: str
    launch_state: ApplicationLaunchStatus | None
    metadata_state: MetadataState
    readiness_state: Literal["not_evaluated"] = "not_evaluated"
    attention_state: Literal["not_evaluated"] = "not_evaluated"
    profile_validated: bool = False
    provenance_qualified: bool = False


@dataclass(frozen=True, slots=True)
class ModuleOperationsMetadataInventory:
    """Stable Suite registry order; unapproved metadata is only counted."""

    applications: tuple[ModuleOperationsMetadataRow, ...]
    unapproved_candidates: int
    inspection_available: bool

    def for_component(self, component_id: str) -> ModuleOperationsMetadataRow | None:
        return next(
            (row for row in self.applications if row.component_id == component_id),
            None,
        )


def _distribution_key(value: str) -> str:
    """PEP 503 normalization for comparison only, never trust attestation."""
    return re.sub(r"[-_.]+", "-", value).lower()


def _valid_metadata(row: object) -> bool:
    """Bound expected Core metadata; reject malformed rows as unavailable data."""
    try:
        kind = row.provider_kind  # type: ignore[attr-defined]
        group = row.entry_point_group  # type: ignore[attr-defined]
        name = row.entry_point_name  # type: ignore[attr-defined]
        target = row.entry_point_target  # type: ignore[attr-defined]
        owner = row.distribution_name  # type: ignore[attr-defined]
    except Exception:
        # Core supplies frozen metadata; fail closed for malformed substitutes.
        return False
    return (
        kind == _KIND
        and group == _GROUP
        and type(name) is str
        and 0 < len(name) <= 256
        and type(target) is str
        and 0 < len(target) <= 1024
        and (owner is None or (type(owner) is str and 0 < len(owner) <= 256))
    )


def _launch_state(
    inventory: ApplicationInventory | None, component_id: str
) -> ApplicationLaunchStatus | None:
    if inventory is None:
        return None
    row = inventory.for_component(component_id)
    return None if row is None else row.status


def _inspect_installed_metadata() -> Iterable[ProviderMetadataLike]:
    """Use *only* Core's public metadata-only enumeration. No EP.load()."""
    module = import_module("pds_core.provider_diagnostics")
    inspect = getattr(module, "inspect_core_provider_entry_points")
    return inspect(provider_kind=_KIND)  # type: ignore[no-any-return]


def collect_module_operations_metadata(
    *,
    launch_inventory: ApplicationInventory | None = None,
    inspect: Callable[[], Iterable[ProviderMetadataLike]] | None = None,
) -> ModuleOperationsMetadataInventory:
    """Classify six approved modules without executing any provider code.

    1. Metadata is observed, never adopted as trustworthy producer identity.
    2. Errors do not become a false 'no providers installed' finding.
    3. No real workspace, provider factory, capability or launcher is called.
    """
    approved = tuple(item for item in APPROVED_COMPONENTS if item.launchable)
    by_id: dict[str, list[object]] = {item.component_id: [] for item in approved}
    unknown_count = 0
    try:
        reader = _inspect_installed_metadata if inspect is None else inspect
        observed = tuple(reader())
        if len(observed) > _MAX_ROWS:
            raise ValueError("unbounded provider metadata")
    except Exception:
        return ModuleOperationsMetadataInventory(
            applications=tuple(
                ModuleOperationsMetadataRow(
                    item.component_id,
                    item.display_name,
                    item.distribution,
                    _launch_state(launch_inventory, item.component_id),
                    "inspection_unavailable",
                )
                for item in approved
            ),
            unapproved_candidates=0,
            inspection_available=False,
        )

    for metadata in observed:
        try:
            name = getattr(metadata, "entry_point_name", None)
        except Exception:
            unknown_count += 1
            continue
        if type(name) is str and name in by_id:
            by_id[name].append(metadata)
        else:
            unknown_count += 1

    rows: list[ModuleOperationsMetadataRow] = []
    for item in approved:
        candidates = by_id[item.component_id]
        state: MetadataState
        if not candidates:
            state = "not_declared"
        elif len(candidates) != 1:
            state = "ambiguous"
        elif not _valid_metadata(candidates[0]):
            state = "invalid_metadata"
        else:
            owner = candidates[0].distribution_name  # type: ignore[attr-defined]
            state = (
                "declared_unvalidated"
                if owner is not None
                and _distribution_key(owner) == _distribution_key(item.distribution)
                else "owner_mismatch"
            )
        rows.append(
            ModuleOperationsMetadataRow(
                component_id=item.component_id,
                display_name=item.display_name,
                expected_distribution=item.distribution,
                launch_state=_launch_state(launch_inventory, item.component_id),
                metadata_state=state,
            )
        )
    return ModuleOperationsMetadataInventory(
        applications=tuple(rows),
        unapproved_candidates=unknown_count,
        inspection_available=True,
    )
