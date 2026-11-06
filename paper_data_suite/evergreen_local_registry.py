"""Fixed, reviewable Suite component identities for local launch assessment.

These identities are approved *names and public console contracts*, not an
assertion that an installed wheel came from an official release. The v0.1.0
release_compatibility_v1.json remains immutable historical evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ApprovedConsole:
    name: str
    target: str


@dataclass(frozen=True, slots=True)
class ApprovedComponent:
    component_id: str
    distribution: str
    display_name: str
    console_scripts: tuple[ApprovedConsole, ...]
    historical_version: str | None
    launchable: bool = True


APPROVED_COMPONENTS: Final[tuple[ApprovedComponent, ...]] = (
    ApprovedComponent(
        "core",
        "pds-core",
        "PDS Core",
        (
            ApprovedConsole("core", "pds_core.core_menu:main"),
            ApprovedConsole("pds-core", "pds_core.cli:main"),
        ),
        "0.6.3",
        launchable=False,
    ),
    ApprovedComponent(
        "scoreform",
        "scoreform",
        "ScoreForm",
        (ApprovedConsole("scoreform", "scoreform.cli:main"),),
        "0.10.0",
    ),
    ApprovedComponent(
        "quillan",
        "quillan",
        "Quillan",
        (ApprovedConsole("quillan", "quillan.cli:main"),),
        "0.9.0",
    ),
    ApprovedComponent(
        "concord",
        "pds-concord",
        "Concord",
        (ApprovedConsole("concord", "concord.cli:main"),),
        "0.2.0",
    ),
    ApprovedComponent(
        "meridian",
        "pds-meridian",
        "Meridian",
        (ApprovedConsole("meridian", "meridian.cli:main"),),
        None,
    ),
    ApprovedComponent(
        "vitrine",
        "pds-vitrine",
        "Vitrine",
        (ApprovedConsole("vitrine", "vitrine.cli:main"),),
        "0.2.0",
    ),
    ApprovedComponent(
        "portia",
        "pds-portia",
        "Portia",
        (ApprovedConsole("portia", "portia.cli:main"),),
        None,
    ),
)

APPROVED_IDS: Final[frozenset[str]] = frozenset(
    component.component_id for component in APPROVED_COMPONENTS
)
