"""Suite #17 Slice 3: non-authorizing Core routing metadata and route checks.

Default provider observation only calls Core's metadata reader. Opt-in profile
validation and explicit, authorized registration inspection are separate paths.
Neither path builds a Core runtime registry or invokes any route handler.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from paper_data_suite.evergreen_local_registry import (
    APPROVED_COMPONENTS,
    ApprovedComponent,
)
from paper_data_suite.returned_paper_preview_contract import (
    ModuleRoutingPreview,
    RegistrationStatus,
    RoutingMetadataStatus,
    RoutingProfileStatus,
)

_PROVIDER_KIND = "routing_module"
_PROVIDER_GROUP = "paper_data_suite.modules"
_MAX_ROWS = 512
_VALID_ROUTING_VERSION = "1"  # Core 0.6.6 routing contract, not package version.


class RoutingMetadataLike(Protocol):
    provider_kind: str
    entry_point_group: str
    entry_point_name: str
    entry_point_target: str
    distribution_name: str | None


@dataclass(frozen=True, slots=True)
class RoutingInventory:
    """Six approved metadata observations; no executable route authority."""

    applications: tuple[ModuleRoutingPreview, ...]
    inspection_available: bool
    unapproved_candidates: int = 0

    def for_component(self, module_id: str) -> ModuleRoutingPreview | None:
        return next((x for x in self.applications if x.module_id == module_id), None)


def _approved() -> tuple[ApprovedComponent, ...]:
    return tuple(component for component in APPROVED_COMPONENTS if component.launchable)


def _distribution_key(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _declared_metadata(
    candidate: object, name: str, distribution: str,
) -> RoutingMetadataStatus:
    try:
        kind = candidate.provider_kind  # type: ignore[attr-defined]
        group = candidate.entry_point_group  # type: ignore[attr-defined]
        entry_name = candidate.entry_point_name  # type: ignore[attr-defined]
        target = candidate.entry_point_target  # type: ignore[attr-defined]
        owner = candidate.distribution_name  # type: ignore[attr-defined]
    except Exception:
        return "invalid_metadata"
    if not (
        kind == _PROVIDER_KIND
        and group == _PROVIDER_GROUP
        and type(entry_name) is str and entry_name == name
        and type(target) is str and 0 < len(target) <= 1024
        and (owner is None or (type(owner) is str and 0 < len(owner) <= 256))
    ):
        return "invalid_metadata"
    if owner is None or _distribution_key(owner) != _distribution_key(distribution):
        return "owner_mismatch"
    return "declared_unvalidated"


def _inspect_core_routing_metadata() -> Iterable[RoutingMetadataLike]:
    core = import_module("pds_core.provider_diagnostics")
    reader = getattr(core, "inspect_core_provider_entry_points")
    return cast(Iterable[RoutingMetadataLike], reader(provider_kind=_PROVIDER_KIND))


def collect_routing_metadata(
    *, inspect: Callable[[], Iterable[RoutingMetadataLike]] | None = None,
) -> RoutingInventory:
    """Inspect metadata only; never load entry points or producer code."""
    approved = _approved()
    by_name: dict[str, list[object]] = {x.component_id: [] for x in approved}
    try:
        reader = _inspect_core_routing_metadata if inspect is None else inspect
        candidates = tuple(reader())
        if len(candidates) > _MAX_ROWS:
            raise ValueError("too many provider declarations")
    except Exception:
        return RoutingInventory(
            applications=tuple(
                ModuleRoutingPreview(x.component_id, "inspection_unavailable")
                for x in approved
            ),
            inspection_available=False,
        )
    unapproved = 0
    for candidate in candidates:
        try:
            name = candidate.entry_point_name
        except Exception:
            name = None
        if type(name) is str and name in by_name:
            by_name[name].append(candidate)
        else:
            unapproved += 1
    rows: list[ModuleRoutingPreview] = []
    for component in approved:
        module_id = component.component_id
        found = by_name[module_id]
        if not found:
            state: RoutingMetadataStatus = "not_declared"
        elif len(found) > 1:
            state = "ambiguous"
        else:
            state = _declared_metadata(
                found[0], module_id, component.distribution
            )
        rows.append(ModuleRoutingPreview(module_id, state))
    return RoutingInventory(tuple(rows), True, unapproved)


def _diagnose_core_routing_profiles() -> Iterable[object]:
    core = import_module("pds_core.provider_diagnostics")
    reader = getattr(core, "diagnose_core_providers")
    return cast(Iterable[object], reader(provider_kind=_PROVIDER_KIND))


def _diagnostic_status(candidate: object, module_id: str) -> RoutingProfileStatus:
    try:
        code = candidate.code  # type: ignore[attr-defined]
        profile = candidate.validated_profile  # type: ignore[attr-defined]
        if code != "provider.valid":
            return "profile_invalid"
        if profile is None or profile.module_id != module_id:
            return "profile_invalid"
        if (
            _VALID_ROUTING_VERSION
            not in profile.supported_core_routing_contract_versions
            or "PDS2" not in profile.supported_qr_schemas
            or "1" not in profile.supported_route_registration_schema_versions
            or "active" not in profile.dispatchable_route_statuses
        ):
            return "core_incompatible"
        return "profile_valid"
    except Exception:
        return "profile_invalid"


def evaluate_routing_profiles(
    inventory: RoutingInventory,
    *,
    diagnose: Callable[[], Iterable[object]] | None = None,
) -> RoutingInventory:
    """**Opt-in executable** profile diagnosis, never routing/dispatch.

    A valid result is associated only with the exact approved declaration.
    No diagnostic can promote an ambiguous, foreign or missing declaration.
    """
    if not inventory.inspection_available:
        return inventory
    try:
        reader = _diagnose_core_routing_profiles if diagnose is None else diagnose
        results = tuple(reader())
        if len(results) > _MAX_ROWS:
            raise ValueError("too many provider diagnostics")
    except Exception:
        return RoutingInventory(
            tuple(
                ModuleRoutingPreview(
                    row.module_id, row.metadata_status,
                    (
                        "profile_unavailable"
                        if row.metadata_status == "declared_unvalidated"
                        else "not_evaluated"
                    ),
                ) for row in inventory.applications
            ),
            inventory.inspection_available,
            inventory.unapproved_candidates,
        )
    by_name: dict[str, list[object]] = {}
    for candidate in results:
        try:
            meta = candidate.metadata  # type: ignore[attr-defined]
            name = meta.entry_point_name
            owner = meta.distribution_name
            kind = meta.provider_kind
            group = meta.entry_point_group
        except Exception:
            continue
        if (
            type(name) is str
            and type(owner) is str
            and kind == _PROVIDER_KIND and group == _PROVIDER_GROUP
        ):
            by_name.setdefault(name, []).append(candidate)
    expected = {x.component_id: x.distribution for x in _approved()}
    rows: list[ModuleRoutingPreview] = []
    for row in inventory.applications:
        if row.metadata_status != "declared_unvalidated":
            rows.append(row)
            continue
        found = [
            candidate for candidate in by_name.get(row.module_id, ())
            if _distribution_key(
                candidate.metadata.distribution_name  # type: ignore[attr-defined]
            ) == _distribution_key(expected[row.module_id])
        ]
        if len(found) != 1:
            state: RoutingProfileStatus = (
                "profile_unavailable" if not found else "profile_invalid"
            )
        else:
            state = _diagnostic_status(found[0], row.module_id)
        rows.append(ModuleRoutingPreview(row.module_id, row.metadata_status, state))
    return RoutingInventory(tuple(rows), True, inventory.unapproved_candidates)


def _unsafe_route_path(root: Path, route_path: Path) -> bool:
    """Refuse redirected route ancestry before invoking Core's public reader."""
    try:
        canonical_root = root.resolve(strict=True)
        canonical_route = route_path.resolve(strict=False)
        canonical_route.relative_to(canonical_root)
        relative_parts = route_path.relative_to(root).parts
        current = root
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                return True
            is_junction = getattr(current, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
        return False
    except (OSError, ValueError, RuntimeError):
        return True


def make_core_registration_check(
    workspace_root: Path | None,
    *,
    authorize_route: Callable[[Path, object], bool] | None = None,
) -> Callable[[int, int, object], RegistrationStatus]:
    """Make an *opt-in* check for a caller-authorized Core route.

    Authorize *each locator* for the selected teacher, not merely the root.
    The caller provides this security decision; this function cannot prove
    teacher identity. Never serialize a locator or a registration. Calling it
    does not grant dispatch authority or establish producer target validity.
    """

    def check(
        _source_number: int, _page_number: int, locator: object,
    ) -> RegistrationStatus:
        if workspace_root is None or authorize_route is None:
            return "workspace_unavailable"
        try:
            if (
                not isinstance(workspace_root, Path)
                or not workspace_root.is_absolute()
                or ".." in workspace_root.parts
                or not workspace_root.is_dir()
                or any(
                    part.is_symlink()
                    for part in (workspace_root, *workspace_root.parents)
                )
            ):
                return "workspace_unavailable"
            models = import_module("pds_core.routing_models")
            locator_type = getattr(models, "RouteLocator")
            if not isinstance(locator, locator_type):
                return "registration_invalid"
            if not authorize_route(workspace_root, locator):
                return "workspace_unavailable"
        except Exception:
            return "workspace_unavailable"
        try:
            routes = import_module("pds_core.routes")
            registrations = import_module("pds_core.route_registrations")
            path_fn = getattr(routes, "route_registration_path")
            route_path = cast(Path, path_fn(workspace_root, locator))
            if _unsafe_route_path(workspace_root, route_path):
                return "registration_invalid"
            loader = getattr(registrations, "load_route_registration")
            record = loader(workspace_root, locator)
            if record.locator != locator:
                return "registration_invalid"
            return (
                "structurally_consistent"
                if record.status == "active" else "registration_inactive"
            )
        except Exception as error:
            if error.__class__.__module__ == "pds_core.route_registrations" and (
                error.__class__.__name__ == "RouteRegistrationNotFoundError"
            ):
                return "registration_not_found"
            return "registration_invalid"
    return check


__all__ = [
    "RoutingInventory",
    "collect_routing_metadata",
    "evaluate_routing_profiles",
    "make_core_registration_check",
]
