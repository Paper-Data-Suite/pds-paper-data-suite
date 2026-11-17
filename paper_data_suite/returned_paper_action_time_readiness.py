"""#19E1: opt-in current-environment paper readiness, never dispatch permission.

Reuses #49 launch observation, #19A1 exact candidates, and #19A3 isolated
wheel/native/profile evidence. Nothing executes on Teacher Home entry.
Even a complete diagnostic match is NOT installed E2E acceptance or admission.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from paper_data_suite.applications import (
    ApplicationInventory,
    ApplicationLaunchStatus,
)
from paper_data_suite.evergreen_local_application_inventory import (
    collect_local_launch_inventory,
)
from paper_data_suite.returned_paper_admission import (
    PaperAdmissionV1,
    inspect_paper_admission,
)
from paper_data_suite.returned_paper_runtime_probe import (
    InstalledPaperRuntimeProbeV1,
    RuntimeProbeStatus,
    inspect_installed_paper_runtime,
)

_ACTION_VERSION: Final[str] = "1"
_PRODUCERS: Final[tuple[str, str]] = ("scoreform", "quillan")

ReadinessStatus = Literal[
    "candidate_unqualified",
    "launcher_unqualified",
    "dependencies_unqualified",
    "runtime_unqualified",
    "diagnostic_match_not_admitted",
]
ProducerStatus = Literal[
    "not_installed", "incompatible", "metadata_unqualified",
    "launcher_unqualified", "dependencies_unqualified",
    "runtime_unqualified", "diagnostic_match_not_admitted",
]


class ActionTimeReadinessError(ValueError):
    """Malformed nonauthorizing current-environment diagnostic."""


@dataclass(frozen=True, slots=True)
class PaperProducerReadinessV1:
    """One approved module ID and honest, local, nonauthorizing observation."""

    module_id: str
    state: ProducerStatus
    dispatch_eligible: Literal[False] = False

    def __post_init__(self) -> None:
        if self.module_id not in _PRODUCERS or self.state not in {
            "not_installed", "incompatible", "metadata_unqualified",
            "launcher_unqualified", "dependencies_unqualified",
            "runtime_unqualified", "diagnostic_match_not_admitted",
        } or self.dispatch_eligible is not False:
            raise ActionTimeReadinessError("invalid producer readiness observation")


@dataclass(frozen=True, slots=True)
class PaperActionTimeReadinessV1:
    """Diagnostic evidence only; never convertible to a qualified module set."""

    status: ReadinessStatus
    producers: tuple[PaperProducerReadinessV1, PaperProducerReadinessV1]
    launchers_checked: bool
    pip_checked: bool
    pip_ok: bool
    native_probe_status: RuntimeProbeStatus | None
    contract_version: Literal["1"] = "1"
    processing_status: Literal["preview_only"] = "preview_only"
    qualified_modules: frozenset[str] = frozenset()
    producer_dispatch_authorized: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            self.status not in {
                "candidate_unqualified", "launcher_unqualified",
                "dependencies_unqualified", "runtime_unqualified",
                "diagnostic_match_not_admitted",
            }
            or self.contract_version != _ACTION_VERSION
            or self.processing_status != "preview_only"
            or self.qualified_modules
            or self.producer_dispatch_authorized is not False
            or type(self.producers) is not tuple
            or any(not isinstance(p, PaperProducerReadinessV1)
                   for p in self.producers)
            or tuple(p.module_id for p in self.producers) != _PRODUCERS
            or any(type(flag) is not bool for flag in (
                self.launchers_checked, self.pip_checked, self.pip_ok,
            ))
            or (self.pip_ok and not self.pip_checked)
            or (self.native_probe_status is not None and not self.pip_ok)
        ):
            raise ActionTimeReadinessError("diagnostic cannot grant dispatch")
        if self.status == "candidate_unqualified":
            good = not self.launchers_checked and not self.pip_checked
        elif self.status == "launcher_unqualified":
            good = self.launchers_checked and not self.pip_checked
        elif self.status == "dependencies_unqualified":
            good = self.launchers_checked and self.pip_checked and not self.pip_ok
        elif self.status == "runtime_unqualified":
            good = (
                self.launchers_checked and self.pip_ok
                and self.native_probe_status not in {None, "diagnostic_match"}
            )
        else:
            good = (
                self.launchers_checked and self.pip_ok
                and self.native_probe_status == "diagnostic_match"
            )
        if not good:
            raise ActionTimeReadinessError("contradictory readiness stage")


CandidateReader = Callable[[], PaperAdmissionV1]
LauncherReader = Callable[[], ApplicationInventory]
NativeReader = Callable[[Path], InstalledPaperRuntimeProbeV1]
PipCheck = Callable[[], bool]


def _pip_check_current_interpreter() -> bool:
    """No network, package install, repair, shell, or raw subprocess logging."""
    try:
        completed = subprocess.run(
            (sys.executable, "-m", "pip", "check"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return completed.returncode == 0
    except (Exception, KeyboardInterrupt):
        return False


def _metadata_rows(candidate: PaperAdmissionV1) -> tuple[
    PaperProducerReadinessV1, PaperProducerReadinessV1
]:
    def state(module_id: str) -> PaperProducerReadinessV1:
        entry = next(p for p in candidate.producers if p.module_id == module_id)
        if entry.state == "not_installed":
            value: ProducerStatus = "not_installed"
        elif entry.state in {"incompatible", "version_unqualified"}:
            value = "incompatible"
        else:
            value = "metadata_unqualified"
        return PaperProducerReadinessV1(module_id, value)

    return state("scoreform"), state("quillan")


def _rows_with(
    state: ProducerStatus,
) -> tuple[PaperProducerReadinessV1, PaperProducerReadinessV1]:
    return (
        PaperProducerReadinessV1("scoreform", state),
        PaperProducerReadinessV1("quillan", state),
    )


def inspect_paper_action_time_readiness(
    wheelhouse: Path,
    *,
    candidate_reader: CandidateReader = inspect_paper_admission,
    launcher_reader: LauncherReader = collect_local_launch_inventory,
    pip_check: PipCheck = _pip_check_current_interpreter,
    native_reader: NativeReader = inspect_installed_paper_runtime,
) -> PaperActionTimeReadinessV1:
    """Explicit read-only diagnostic; no arbitrary trust callback can admit.

    Call only in a deliberately prepared disposable installed-wheel environment.
    A3 imports native modules and profile factories only after its own gates.
    Returned evidence is safe for diagnostics, NOT for #18 qualified_modules.
    """
    if not isinstance(wheelhouse, Path) or not wheelhouse.is_absolute():
        raise ActionTimeReadinessError("explicit absolute wheelhouse required")
    if not all(callable(x) for x in (
        candidate_reader, launcher_reader, pip_check, native_reader,
    )):
        raise ActionTimeReadinessError("diagnostic callbacks unavailable")

    try:
        candidate = candidate_reader()
    except (Exception, KeyboardInterrupt):
        candidate = None
    exact = (
        isinstance(candidate, PaperAdmissionV1)
        and candidate.core_state == "exact_release_candidate"
        and candidate.exact_release_candidates == _PRODUCERS
        and candidate.processing_status == "preview_only"
        and not candidate.qualified_modules
    )
    if not exact:
        rows = _metadata_rows(candidate) if isinstance(
            candidate, PaperAdmissionV1
        ) else _rows_with("metadata_unqualified")
        return PaperActionTimeReadinessV1(
            "candidate_unqualified", rows, False, False, False, None,
        )

    try:
        inventory = launcher_reader()
        if not isinstance(inventory, ApplicationInventory):
            raise ActionTimeReadinessError("invalid #49 inventory")
        for name in _PRODUCERS:
            observed = tuple(
                a for a in inventory.applications if a.component_id == name
            )
            if (
                len(observed) != 1
                or observed[0].status is not ApplicationLaunchStatus.AVAILABLE
                or observed[0].launcher_path is None
            ):
                raise ActionTimeReadinessError("launcher not usable")
    except (Exception, KeyboardInterrupt):
        return PaperActionTimeReadinessV1(
            "launcher_unqualified", _rows_with("launcher_unqualified"),
            True, False, False, None,
        )

    try:
        pip_ok = pip_check() is True
    except (Exception, KeyboardInterrupt):
        pip_ok = False
    if not pip_ok:
        return PaperActionTimeReadinessV1(
            "dependencies_unqualified", _rows_with("dependencies_unqualified"),
            True, True, False, None,
        )

    try:
        probe = native_reader(wheelhouse)
        if not isinstance(probe, InstalledPaperRuntimeProbeV1):
            raise ActionTimeReadinessError("untyped runtime diagnostic")
        stage = probe.status
    except (Exception, KeyboardInterrupt):
        stage = "runtime_unqualified"
    if stage != "diagnostic_match":
        return PaperActionTimeReadinessV1(
            "runtime_unqualified", _rows_with("runtime_unqualified"),
            True, True, True, stage,
        )
    return PaperActionTimeReadinessV1(
        "diagnostic_match_not_admitted",
        _rows_with("diagnostic_match_not_admitted"),
        True, True, True, stage,
    )


def render_paper_action_time_readiness(report: PaperActionTimeReadinessV1) -> str:
    """Path-free diagnostic; never prints native exception or installer output."""
    if not isinstance(report, PaperActionTimeReadinessV1):
        raise ActionTimeReadinessError("typed readiness observation required")
    lines = [
        "Returned papers - isolated installed-runtime readiness (READ ONLY)",
        f"Status: {report.status}.",
        f"Current-environment launcher check: {report.launchers_checked}.",
        f"Offline pip check passed: {report.pip_ok}.",
        "Producer paper integration:",
    ]
    for row in report.producers:
        lines.append(f"  {row.module_id}: {row.state}; NOT admitted")
    lines.extend((
        "No teacher pages were inspected and no producer handlers ran.",
        "This is a diagnostic, NOT permission to retain or dispatch.",
        "Wheel payload matching does not prove loaded native-code provenance.",
        "Complete installed synthetic E2E acceptance and review policy are",
        "required before a separate action-time dispatch gate can admit producers.",
    ))
    return "\n".join(lines) + "\n"


__all__ = (
    "ActionTimeReadinessError", "PaperProducerReadinessV1",
    "PaperActionTimeReadinessV1", "inspect_paper_action_time_readiness",
    "render_paper_action_time_readiness",
)
