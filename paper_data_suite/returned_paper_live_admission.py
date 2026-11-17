"""#19E3B1: narrowly reviewed installed-paper action-time admission.

This is NOT a durable witness or a teacher-facing dispatch action. Only an
explicit, current audit of the installed Windows Python 3.11 release subset
can produce the exact two module IDs; neither a fabricated diagnostic object
nor historical acceptance markers are accepted as input.
"""

from __future__ import annotations

import platform
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from paper_data_suite.returned_paper_action_time_readiness import (
    PaperActionTimeReadinessV1,
    inspect_paper_action_time_readiness,
)
from paper_data_suite.returned_paper_runtime_probe import _isolated_supported_runtime

_ADMISSION_VERSION: Final[str] = "1"
_APPROVED: Final[frozenset[str]] = frozenset({"scoreform", "quillan"})
_REPARSE: Final[int] = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

LiveAdmissionStatus = Literal[
    "unsupported_runtime", "wheelhouse_unavailable", "audit_refused", "admitted",
]


class LivePaperAdmissionError(ValueError):
    """Attempt to construct contradictory workflow-specific authority."""


@dataclass(frozen=True, slots=True, repr=False)
class LivePaperAdmissionV1:
    """Ephemeral result. Never serialize, cache or use outside this action."""

    status: LiveAdmissionStatus
    qualified_modules: frozenset[str] = frozenset()
    contract_version: Literal["1"] = "1"
    action_time_only: Literal[True] = True
    can_skip_second_consent: Literal[False] = False
    source_retention_authorized: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            self.contract_version != _ADMISSION_VERSION
            or self.action_time_only is not True
            or self.can_skip_second_consent is not False
            or self.source_retention_authorized is not False
            or self.status not in {
                "unsupported_runtime", "wheelhouse_unavailable",
                "audit_refused", "admitted",
            }
            or type(self.qualified_modules) is not frozenset
            or (
                self.qualified_modules != _APPROVED
                if self.status == "admitted"
                else bool(self.qualified_modules)
            )
        ):
            raise LivePaperAdmissionError("invalid action-time admission result")


def _wheelhouse_safe(wheelhouse: Path) -> bool:
    """A caller-selected local folder, never a hidden default or network path."""
    if (
        not isinstance(wheelhouse, Path)
        or not wheelhouse.is_absolute()
        or ".." in wheelhouse.parts
    ):
        return False
    try:
        if not wheelhouse.is_dir():
            return False
        # The trusted wheel comparison performed later reopens actual files.
        for part in (wheelhouse, *wheelhouse.parents):
            data = part.lstat()
            if stat.S_ISLNK(data.st_mode) or (
                getattr(data, "st_file_attributes", 0) & _REPARSE
            ):
                return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _action_host_supported() -> bool:
    """The Windows x64-style Python 3.11 isolated host accepted in E3A."""
    try:
        return (
            sys.platform == "win32"
            and sys.version_info[:2] == (3, 11)
            and platform.machine().casefold() in {"amd64", "x86_64"}
            and _isolated_supported_runtime()
        )
    except (Exception, KeyboardInterrupt):
        return False


def inspect_live_paper_admission(wheelhouse: Path) -> LivePaperAdmissionV1:
    """Reinspect real installed wheel payload, launchers, pip, native profiles.

    No caller-provided release flags, diagnostic objects, eligible module set,
    or synthetic test result can promote this decision. Only the built-in E1
    current-runtime checks are authoritative, and only during the action.
    This does not call #18, construct a teacher consent or invoke a handler.
    """
    if not _action_host_supported():
        return LivePaperAdmissionV1("unsupported_runtime")
    if not _wheelhouse_safe(wheelhouse):
        return LivePaperAdmissionV1("wheelhouse_unavailable")
    try:
        current = inspect_paper_action_time_readiness(wheelhouse)
        accepted = (
            isinstance(current, PaperActionTimeReadinessV1)
            and current.status == "diagnostic_match_not_admitted"
            and current.launchers_checked is True
            and current.pip_checked is True
            and current.pip_ok is True
            and current.native_probe_status == "diagnostic_match"
            and current.qualified_modules == frozenset()
            and current.producer_dispatch_authorized is False
            and current.processing_status == "preview_only"
            and tuple(
                (row.module_id, row.state, row.dispatch_eligible)
                for row in current.producers
            ) == (
                ("scoreform", "diagnostic_match_not_admitted", False),
                ("quillan", "diagnostic_match_not_admitted", False),
            )
        )
    except (Exception, KeyboardInterrupt):
        accepted = False
    if not accepted:
        return LivePaperAdmissionV1("audit_refused")
    # E3A native installed acceptance supported this *exact* combined subset.
    # E3B2 must repeat this action-time check immediately before #18 dispatch.
    return LivePaperAdmissionV1("admitted", _APPROVED)


def render_live_paper_admission(result: LivePaperAdmissionV1) -> str:
    """Bounded, path-free result; never disclose wheelhouse or user data."""
    if not isinstance(result, LivePaperAdmissionV1):
        raise LivePaperAdmissionError("typed action-time result required")
    if result.status == "admitted":
        state = "scoreform and quillan eligible for this action only"
    else:
        state = "no producer eligible for Core dispatch"
    return "\n".join((
        "Returned papers - installed producer action-time policy",
        f"Status: {result.status}.",
        f"Producer readiness: {state}.",
        "This does not authorize Core source retention or skip teacher consent.",
        "No handlers were invoked and no student records were changed.",
        "An accepted result is not a cached credential or provenance signature.",
        "Live dispatch remains disconnected from Teacher Home in this slice.",
    )) + "\n"


__all__ = (
    "LivePaperAdmissionError", "LivePaperAdmissionV1",
    "inspect_live_paper_admission", "render_live_paper_admission",
)
