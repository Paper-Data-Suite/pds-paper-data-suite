"""Suite #21 Slice B0: read-only, explicit selection-scope preflight.

This module does NOT acquire a provider profile, attest a release, or invoke
attention. It must not be imported by normal teacher-home startup. A valid
Core request is necessary but *not* proof of teacher authorization or a
qualified installed producer. Core #249 is required before live admission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from pds_core.classes import class_folder
from pds_core.module_operations import (
    ModuleOperationsRequest,
    validate_module_operations_request,
)
from pds_core.routes import classes_dir
from pds_core.school_years import get_active_school_year, school_year_state_path
from pds_core.workspace import inspect_workspace_root, resolve_workspace_root

_SELECTION_OWNERS: Final[tuple[str, ...]] = ("scoreform", "quillan", "concord")

ScopeCode = Literal[
    "scope_validated",
    "invalid_selection",
    "workspace_unavailable",
    "workspace_mismatch",
    "school_year_mismatch",
    "class_unavailable",
]


@dataclass(frozen=True, slots=True)
class AttentionScopePreflight:
    """One bounded selection observation; *never* executable authority.

    The Core request carries a private workspace and class identifier, so it
    is excluded from repr. This type is not an installed release attestation,
    a callable profile, a capability result, or authorization to access files.
    """

    code: ScopeCode
    requested_owners: tuple[str, ...] = ()
    request: ModuleOperationsRequest | None = field(default=None, repr=False)

    @property
    def scope_validated(self) -> bool:
        return self.code == "scope_validated" and self.request is not None


def _refused(
    code: ScopeCode, owners: tuple[str, ...] = ()
) -> AttentionScopePreflight:
    return AttentionScopePreflight(code=code, requested_owners=owners)


def _approved_owners(value: object) -> tuple[str, ...] | None:
    """Require an explicit, nonempty, unambiguous subset of the first 3 owners."""
    if not isinstance(value, tuple) or type(value) is not tuple:
        return None
    if not 1 <= len(value) <= len(_SELECTION_OWNERS):
        return None
    if any(type(owner) is not str or owner not in _SELECTION_OWNERS for owner in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(owner for owner in _SELECTION_OWNERS if owner in value)


def prepare_selected_attention_scope(
    *,
    workspace_root: Path | None,
    active_school_year: str | None,
    class_id: str | None,
    requested_owners: tuple[str, ...],
) -> AttentionScopePreflight:
    """Read-only, fail-closed inspection of an explicitly supplied Core context.

    An explicit root must match the CURRENT Core selection; no cached/default
    value is substituted for the caller's root. A selected year must match the
    workspace's open year and a selected class must exist without a redirect.

    This is strictly a prerequisite for later, separately authorized,
    publisher-qualified provider acquisition. It never executes one.
    """
    owners = _approved_owners(requested_owners)
    if owners is None:
        return _refused("invalid_selection")
    if not isinstance(workspace_root, Path):
        return _refused("invalid_selection", owners)
    if (
        not workspace_root.is_absolute()
        or workspace_root == Path(workspace_root.anchor)
        or ".." in workspace_root.parts
        or type(active_school_year) is not str
        or active_school_year == ""
        or (
            class_id is not None
            and (type(class_id) is not str or not class_id)
        )
    ):
        return _refused("invalid_selection", owners)

    try:
        request = ModuleOperationsRequest(
            workspace_root=workspace_root,
            active_school_year=active_school_year,
            class_id=class_id,
        )
        validate_module_operations_request(request)
    except Exception:
        return _refused("invalid_selection", owners)

    try:
        # Do not permit a missing root or a symlink/junction to redirect a
        # selected workspace to an unreviewed location.
        if workspace_root.resolve(strict=True) != workspace_root:
            return _refused("workspace_unavailable", owners)
        observed = inspect_workspace_root(workspace_root)
        if (
            observed.source != "explicit"
            or observed.root != workspace_root
            or observed.exists is not True
            or observed.is_dir is not True
        ):
            return _refused("workspace_unavailable", owners)
        # This reads Core's selected root only to compare it; it is NEVER an
        # evaluation root fallback.
        if resolve_workspace_root() != workspace_root:
            return _refused("workspace_mismatch", owners)
    except Exception:
        return _refused("workspace_unavailable", owners)

    # Core's public year and class readers must not traverse a symlinked
    # container into another teacher/workspace. These checks are preflight,
    # not a claim of race-free filesystem isolation during later callbacks.
    try:
        year_path = school_year_state_path(workspace_root)
        classes_path = classes_dir(workspace_root)
        if (
            not classes_path.is_dir()
            or classes_path.resolve(strict=True) != classes_path
            or year_path.parent.resolve(strict=True) != year_path.parent
            or (
                year_path.exists()
                and year_path.resolve(strict=True) != year_path
            )
        ):
            return _refused("workspace_unavailable", owners)
    except Exception:
        return _refused("workspace_unavailable", owners)

    try:
        if get_active_school_year(workspace_root) != active_school_year:
            return _refused("school_year_mismatch", owners)
    except Exception:
        return _refused("school_year_mismatch", owners)

    if class_id is not None:
        try:
            folder = class_folder(workspace_root, class_id)
            # Directories may not point at a different class or external store.
            if (
                not folder.class_dir.is_dir()
                or folder.class_dir.resolve(strict=True) != folder.class_dir
            ):
                return _refused("class_unavailable", owners)
        except Exception:
            return _refused("class_unavailable", owners)

    return AttentionScopePreflight(
        code="scope_validated",
        requested_owners=owners,
        request=request,
    )


__all__ = [
    "AttentionScopePreflight",
    "ScopeCode",
    "prepare_selected_attention_scope",
]
