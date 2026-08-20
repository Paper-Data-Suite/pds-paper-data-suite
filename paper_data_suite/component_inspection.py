"""Shared installed-component metadata inspection for suite workflows."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from importlib import metadata

from paper_data_suite.bootstrap import (
    BootstrapPlanningError,
    normalize_distribution_name,
)
from paper_data_suite.compatibility import ComponentCompatibility

_DISTRIBUTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

DistributionVersionLookup = Callable[[str], str]
DistributionInventoryLookup = Callable[[], Iterable[metadata.Distribution]]


@dataclass(frozen=True, slots=True)
class EntryPointObservation:
    """Metadata-only observation of one installed public entry point."""

    group: str
    name: str
    target: str
    distribution: str
    distribution_version: str


EntryPointInventoryLookup = Callable[[], Sequence[EntryPointObservation]]


class EntryPointMatchStatus(str, Enum):
    """Metadata-only comparison result for one expected public entry point."""

    MATCH = "MATCH"
    MISSING = "MISSING"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    DUPLICATE = "DUPLICATE"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class EntryPointMatch:
    """Bounded metadata observations for one expected entry-point identity."""

    status: EntryPointMatchStatus
    owned: tuple[EntryPointObservation, ...]
    foreign: tuple[EntryPointObservation, ...]


def lookup_distribution_version(
    distribution: str,
    version_lookup: DistributionVersionLookup,
) -> str | None:
    """Return an installed distribution version, or ``None`` when absent."""
    try:
        return version_lookup(distribution)
    except metadata.PackageNotFoundError:
        return None


def component_is_suite_qualified(
    component: ComponentCompatibility,
    *,
    version_lookup: DistributionVersionLookup,
) -> bool:
    """Return whether one component is installed at its exact qualified version."""
    return (
        lookup_distribution_version(component.distribution, version_lookup)
        == component.version
    )


def normalize_entry_point_owner(value: str) -> str | None:
    """Normalize an installed entry-point owner without trusting malformed names."""
    stripped = value.strip()
    if _DISTRIBUTION_NAME_RE.fullmatch(stripped) is None:
        return None
    try:
        return normalize_distribution_name(stripped)
    except BootstrapPlanningError:
        return None


def match_entry_point_metadata(
    component: ComponentCompatibility,
    *,
    group: str,
    name: str,
    target: str,
    inventory: Sequence[EntryPointObservation],
) -> EntryPointMatch:
    """Compare one expected entry point without loading its Python target."""
    expected_owner = normalize_distribution_name(component.distribution)
    same_identity = tuple(
        item for item in inventory if item.group == group and item.name == name
    )
    owned = tuple(
        item
        for item in same_identity
        if normalize_entry_point_owner(item.distribution) == expected_owner
    )
    foreign = tuple(
        item
        for item in same_identity
        if normalize_entry_point_owner(item.distribution) != expected_owner
    )

    if not owned:
        status = (
            EntryPointMatchStatus.OWNER_MISMATCH
            if foreign
            else EntryPointMatchStatus.MISSING
        )
    elif len(owned) != 1:
        status = EntryPointMatchStatus.DUPLICATE
    elif owned[0].target != target:
        status = EntryPointMatchStatus.TARGET_MISMATCH
    elif foreign:
        status = EntryPointMatchStatus.CONFLICT
    else:
        status = EntryPointMatchStatus.MATCH

    return EntryPointMatch(status=status, owned=owned, foreign=foreign)


def installed_entry_point_inventory(
    distributions_lookup: DistributionInventoryLookup = metadata.distributions,
) -> tuple[EntryPointObservation, ...]:
    """Read installed entry-point metadata without loading entry-point targets."""
    observations: list[EntryPointObservation] = []
    for distribution in distributions_lookup():
        try:
            owner = distribution.metadata["Name"]
            version = distribution.version
            entry_points = tuple(distribution.entry_points)
        except (KeyError, OSError, TypeError, ValueError):
            continue
        if not owner or not version:
            continue
        for entry_point in entry_points:
            observations.append(
                EntryPointObservation(
                    group=entry_point.group,
                    name=entry_point.name,
                    target=entry_point.value,
                    distribution=str(owner),
                    distribution_version=str(version),
                )
            )
    return tuple(
        sorted(
            observations,
            key=lambda item: (
                item.group,
                item.name,
                normalize_entry_point_owner(item.distribution) or "",
                item.distribution_version,
                item.target,
            ),
        )
    )


__all__ = (
    "DistributionInventoryLookup",
    "DistributionVersionLookup",
    "EntryPointInventoryLookup",
    "EntryPointMatch",
    "EntryPointMatchStatus",
    "EntryPointObservation",
    "component_is_suite_qualified",
    "installed_entry_point_inventory",
    "lookup_distribution_version",
    "match_entry_point_metadata",
    "normalize_entry_point_owner",
)
