"""Suite #21: explicit OFFLINE Core+named-producer release-evidence probe.

Reuse Suite #16's exact published-wheel byte inspector. Matching installed
metadata is neither provenance attestation for installed executable code nor
authorization to load an entry point or invoke any attention callback.

The existing ScoreForm CLI remains:
    python -m scripts.issue21_scoreform_offline_preflight --wheelhouse PATH
C0/D0 reuse the shared inspector through a second explicit CLI. No provider
code is imported by this module or either CLI.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import metadata
from itertools import islice
from pathlib import Path
from typing import Final, Literal

from paper_data_suite.component_inspection import (
    EntryPointObservation,
    installed_entry_point_inventory,
    normalize_entry_point_owner,
)
from scripts.issue16_official_wheel_acceptance import (
    OFFICIAL_WHEELS,
    OfficialWheel,
    WheelEvidence,
    inspect_official_wheel,
)

_GROUP: Final = "paper_data_suite.module_operations"
_MAX_ENTRY_POINTS: Final = 256
_SUPPORTED_OWNERS: Final[tuple[str, ...]] = (
    "scoreform", "quillan", "concord"
)
_REQUIRED: Final = ("core", "scoreform")
_RELEASE_BY_COMPONENT: Final[dict[str, OfficialWheel]] = {
    row.component: row for row in OFFICIAL_WHEELS
    if row.component in ("core", *_SUPPORTED_OWNERS)
}
# Keep the B1 ScoreForm pair public to existing source tests.
_BY_OWNER: Final[dict[str, OfficialWheel]] = {
    row.component: row for row in OFFICIAL_WHEELS if row.component in _REQUIRED
}

B1Code = Literal[
    "owner_unapproved",
    "wheelhouse_unavailable",
    "wheel_evidence_unverified",
    "installed_metadata_unavailable",
    "installed_version_mismatch",
    "entry_point_unqualified",
    "metadata_consistent_not_admitted",
]


@dataclass(frozen=True, slots=True)
class ModuleOfflineEvidence:
    """Static non-admission result; no executable profile or private path."""

    code: B1Code
    examined: tuple[str, ...] = _REQUIRED

    @property
    def metadata_consistent(self) -> bool:
        return self.code == "metadata_consistent_not_admitted"


# Backward-compatible alias for the ScoreForm B1.0 focused tests.
ScoreFormOfflineEvidence = ModuleOfflineEvidence


def _refused(
    code: B1Code, examined: tuple[str, ...] = _REQUIRED
) -> ModuleOfflineEvidence:
    return ModuleOfflineEvidence(code=code, examined=examined)


def _safe_wheelhouse(path: object) -> bool:
    if not isinstance(path, Path):
        return False
    try:
        return (
            path.is_absolute()
            and path != Path(path.anchor)
            and ".." not in path.parts
            and path.is_dir()
            and not path.is_symlink()
            and path.resolve(strict=True) == path
        )
    except (OSError, RuntimeError, ValueError):
        return False


def inspect_named_producer_offline_release(
    wheelhouse: Path,
    *,
    owner_id: str,
    wheel_inspector: Callable[[Path, OfficialWheel], WheelEvidence] = (
        inspect_official_wheel
    ),
    version_lookup: Callable[[str], str] = metadata.version,
    entrypoint_reader: Callable[[], Iterable[EntryPointObservation]] = (
        installed_entry_point_inventory
    ),
) -> ModuleOfflineEvidence:
    """Check one fixed Core+producer wheel pair and installed metadata.

    This is metadata observation only. In particular, a successful status is
    NOT proof that the installed executable bytes came from either local wheel.
    No provider, workspace or attention callback is ever loaded or inspected.
    """
    if type(owner_id) is not str or owner_id not in _SUPPORTED_OWNERS:
        return _refused("owner_unapproved", ())
    examined = ("core", owner_id)
    if not _safe_wheelhouse(wheelhouse):
        return _refused("wheelhouse_unavailable", examined)

    # Exact official release bytes+metadata: retain #16 as the sole inspector.
    try:
        if not set(examined).issubset(_RELEASE_BY_COMPONENT):
            return _refused("wheel_evidence_unverified", examined)
        for component_id in examined:
            spec = _RELEASE_BY_COMPONENT[component_id]
            evidence = wheel_inspector(wheelhouse, spec)
            if (
                not isinstance(evidence, WheelEvidence)
                or evidence.component != spec.component
                or evidence.version != spec.version
                or evidence.sha256 != spec.digest
                or evidence.status != "verified_metadata"
            ):
                return _refused("wheel_evidence_unverified", examined)
    except Exception:
        return _refused("wheel_evidence_unverified", examined)

    # Read-only installed package metadata, not direct import or provenance.
    try:
        for component_id in examined:
            spec = _RELEASE_BY_COMPONENT[component_id]
            if version_lookup(spec.distribution) != spec.version:
                return _refused("installed_version_mismatch", examined)
    except metadata.PackageNotFoundError:
        return _refused("installed_version_mismatch", examined)
    except Exception:
        return _refused("installed_metadata_unavailable", examined)

    # Unambiguous exact-name EP. Foreign duplicate counts as a conflict.
    target_spec = _RELEASE_BY_COMPONENT[owner_id]
    if target_spec.entry_point is None or target_spec.target is None:
        return _refused("entry_point_unqualified", examined)
    try:
        observed = tuple(islice(entrypoint_reader(), _MAX_ENTRY_POINTS + 1))
        if len(observed) > _MAX_ENTRY_POINTS:
            return _refused("installed_metadata_unavailable", examined)
        matching = [
            row for row in observed
            if row.group == _GROUP and row.name == target_spec.entry_point
        ]
        if len(matching) != 1:
            return _refused("entry_point_unqualified", examined)
        candidate = matching[0]
        if (
            candidate.target != target_spec.target
            or normalize_entry_point_owner(candidate.distribution)
            != normalize_entry_point_owner(target_spec.distribution)
            or candidate.distribution_version != target_spec.version
        ):
            return _refused("entry_point_unqualified", examined)
    except Exception:
        return _refused("installed_metadata_unavailable", examined)

    return ModuleOfflineEvidence(
        code="metadata_consistent_not_admitted", examined=examined
    )


def inspect_scoreform_offline_release(
    wheelhouse: Path,
    *,
    wheel_inspector: Callable[[Path, OfficialWheel], WheelEvidence] = (
        inspect_official_wheel
    ),
    version_lookup: Callable[[str], str] = metadata.version,
    entrypoint_reader: Callable[[], Iterable[EntryPointObservation]] = (
        installed_entry_point_inventory
    ),
) -> ScoreFormOfflineEvidence:
    """Preserve B1.0 ScoreForm API and exact refusal behavior."""
    return inspect_named_producer_offline_release(
        wheelhouse,
        owner_id="scoreform",
        wheel_inspector=wheel_inspector,
        version_lookup=version_lookup,
        entrypoint_reader=entrypoint_reader,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args(argv)
    result = inspect_scoreform_offline_release(args.wheelhouse)
    print(f"PDS21_B1_OFFLINE_SCORE_FORM {result.code}")
    # This intentionally never reports provider qualification success.
    return 0 if result.metadata_consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
