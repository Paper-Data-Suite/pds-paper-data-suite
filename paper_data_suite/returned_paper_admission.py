"""Suite #19A: read-only, default-deny returned-paper admission observation.

This is a UI preflight model, NEVER an authorization to call a PDS2 handler.
The exact official Core / producer wheel subset was synthetically qualified by
Suite #18; ordinary installed-package metadata cannot attest installed bytes,
native decoder availability, route profile correctness, or teacher consent.

No files, workspace, provider modules, registry, or network are accessed here;
the only default observation is Suite #49's read-only metadata assessment.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Final, Literal

from paper_data_suite.evergreen_local_compatibility import (
    ComponentAssessment,
    LocalCompatibilityReport,
    Readiness,
    inspect_local_compatibility,
)
from paper_data_suite.evergreen_local_registry import APPROVED_COMPONENTS

ADMISSION_CONTRACT_VERSION: Final[str] = "1"
# Native published-wheel rehearsal for exactly this subset passed on Windows
# and Ubuntu Python 3.11. Do not generalize to every installed Python/OS.
QUALIFIED_SYNTHETIC_RELEASES: Final[tuple[tuple[str, str], ...]] = (
    ("core", "0.6.6"),
    ("scoreform", "0.13.0"),
    ("quillan", "0.10.6"),
)
_SUPPORTED_PLATFORM_TAGS: Final[frozenset[str]] = frozenset({"win32", "linux"})
_SUPPORTED_PYTHON: Final[tuple[int, int]] = (3, 11)
ProducerId = Literal["scoreform", "quillan"]
_PRODUCERS: Final[tuple[ProducerId, ProducerId]] = ("scoreform", "quillan")

AdmissionState = Literal[
    "exact_release_candidate", "not_installed", "incompatible",
    "version_unqualified", "core_unqualified", "runtime_unqualified",
    "metadata_unavailable",
]


class PaperAdmissionError(ValueError):
    """Invalid request shape for a read-only admission observation."""


@dataclass(frozen=True, slots=True)
class ProducerAdmissionV1:
    """Precise candidate status, not a permission or an imported profile."""

    module_id: ProducerId
    installed_version: str | None
    state: AdmissionState
    expected_version: str
    may_dispatch: Literal[False] = False

    def __post_init__(self) -> None:
        if self.module_id not in _PRODUCERS:
            raise PaperAdmissionError("unapproved paper producer")
        if self.state not in {
            "exact_release_candidate", "not_installed", "incompatible",
            "version_unqualified", "core_unqualified", "runtime_unqualified",
            "metadata_unavailable",
        }:
            raise PaperAdmissionError("invalid producer assessment state")
        expected = dict(QUALIFIED_SYNTHETIC_RELEASES)[self.module_id]
        if self.expected_version != expected or self.may_dispatch is not False:
            raise PaperAdmissionError("admission observation cannot grant dispatch")
        if self.state == "exact_release_candidate" and (
            self.installed_version != self.expected_version
        ):
            raise PaperAdmissionError("exact candidate requires exact version")


@dataclass(frozen=True, slots=True)
class PaperAdmissionV1:
    """Read-only status. Later slices must add an independently qualified gate."""

    core_installed_version: str | None
    core_state: AdmissionState
    producers: tuple[ProducerAdmissionV1, ProducerAdmissionV1]
    runtime_platform: str
    runtime_python: tuple[int, int]
    contract_version: Literal["1"] = "1"
    processing_status: Literal["preview_only"] = "preview_only"
    qualified_modules: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.contract_version != ADMISSION_CONTRACT_VERSION:
            raise PaperAdmissionError("unknown paper admission contract")
        if self.processing_status != "preview_only" or self.qualified_modules:
            raise PaperAdmissionError("metadata cannot authorize Core dispatch")
        if type(self.producers) is not tuple or tuple(
            p.module_id for p in self.producers
        ) != _PRODUCERS:
            raise PaperAdmissionError("producer order/identity is invalid")
        if self.core_state not in {
            "exact_release_candidate", "not_installed", "incompatible",
            "version_unqualified", "runtime_unqualified", "metadata_unavailable",
        }:
            raise PaperAdmissionError("invalid Core candidate state")

    @property
    def exact_release_candidates(self) -> tuple[str, ...]:
        """Only a UI hint; NOT eligible/qualified execution modules."""
        return tuple(
            row.module_id for row in self.producers
            if row.state == "exact_release_candidate"
        )


def _approved_distribution(component_id: str) -> str:
    approved = [c for c in APPROVED_COMPONENTS if c.component_id == component_id]
    if len(approved) != 1:
        raise PaperAdmissionError("fixed approved registry is inconsistent")
    return approved[0].distribution


def _read_component(
    report: LocalCompatibilityReport, component_id: str,
) -> ComponentAssessment | None:
    # Do not trust the first match of a potentially malformed external report.
    rows = [r for r in report.components if r.component_id == component_id]
    if len(rows) != 1:
        return None
    row = rows[0]
    if not isinstance(row, ComponentAssessment):
        return None
    if row.distribution != _approved_distribution(component_id):
        return None
    if row.readiness not in {
        Readiness.COMPATIBLE, Readiness.NOT_INSTALLED, Readiness.INCOMPATIBLE,
    }:
        return None
    return row


def _candidate_state(
    row: ComponentAssessment | None,
    expected_version: str,
) -> AdmissionState:
    if row is None:
        return "metadata_unavailable"
    if row.readiness is Readiness.NOT_INSTALLED:
        return "not_installed"
    if row.readiness is not Readiness.COMPATIBLE:
        return "incompatible"
    if row.installed_version != expected_version:
        return "version_unqualified"
    return "exact_release_candidate"


def inspect_paper_admission(
    *,
    report: LocalCompatibilityReport | None = None,
    platform_tag: str | None = None,
    python_version: tuple[int, int] | None = None,
) -> PaperAdmissionV1:
    """Assess *candidate* releases, with no Core/producer execution grant.

    Default dependency is Suite #49's live local metadata observation. Explicit
    arguments are used for deterministic tests; passing a fabricated report or
    runtime can never authorize dispatch, since qualified_modules stays empty.

    The separately reviewed, exact installed-artifact/native/profile witness
    and action-time recheck are deliberately reserved for #19D/#19G. A fixed
    version match is NOT publisher authentication or permission to execute.
    """
    if report is not None and not isinstance(report, LocalCompatibilityReport):
        raise PaperAdmissionError("typed #49 compatibility report required")
    if platform_tag is not None and (
        type(platform_tag) is not str or not 1 <= len(platform_tag) <= 32
    ):
        raise PaperAdmissionError("bounded runtime platform expected")
    if python_version is not None and (
        type(python_version) is not tuple
        or len(python_version) != 2
        or any(
            type(value) is not int or not 0 <= value <= 99
            for value in python_version
        )
    ):
        raise PaperAdmissionError("valid Python major/minor pair required")

    observed = report if report is not None else inspect_local_compatibility()
    current_platform = platform_tag if platform_tag is not None else sys.platform
    current_python = (
        python_version if python_version is not None
        else (sys.version_info.major, sys.version_info.minor)
    )
    supported_runtime = (
        current_platform in _SUPPORTED_PLATFORM_TAGS
        and current_python == _SUPPORTED_PYTHON
    )
    core = _read_component(observed, "core")
    core_state = _candidate_state(core, "0.6.6")
    if not supported_runtime:
        core_state = "runtime_unqualified"

    result: list[ProducerAdmissionV1] = []
    for module_id in _PRODUCERS:
        expected = dict(QUALIFIED_SYNTHETIC_RELEASES)[module_id]
        row = _read_component(observed, module_id)
        state = _candidate_state(row, expected)
        if not supported_runtime:
            state = "runtime_unqualified"
        elif core_state != "exact_release_candidate":
            # Preserve 'missing'/'incompatible' for actionable inventory UI.
            if state == "exact_release_candidate":
                state = "core_unqualified"
        result.append(ProducerAdmissionV1(
            module_id=module_id,
            installed_version=row.installed_version if row is not None else None,
            state=state,
            expected_version=expected,
        ))

    return PaperAdmissionV1(
        core_installed_version=core.installed_version if core is not None else None,
        core_state=core_state,
        producers=(result[0], result[1]),
        runtime_platform=current_platform,
        runtime_python=current_python,
    )


__all__ = (
    "ADMISSION_CONTRACT_VERSION",
    "QUALIFIED_SYNTHETIC_RELEASES",
    "PaperAdmissionError",
    "ProducerAdmissionV1",
    "PaperAdmissionV1",
    "inspect_paper_admission",
)
