"""Suite #21 B1: explicit OFFLINE Core/ScoreForm release-evidence probe.

Reuse Suite #16's exact published-wheel byte inspector. Reading matching
installed metadata is neither provenance attestation for installed code nor
authorization to load an entry point or invoke any attention callback.

Invoke deliberately via: python -m scripts.issue21_scoreform_offline_preflight
    --wheelhouse PATH
Never import this from pds startup, launch, or Teacher Home.
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
_REQUIRED: Final = ("core", "scoreform")
_BY_OWNER: Final[dict[str, OfficialWheel]] = {
    row.component: row for row in OFFICIAL_WHEELS if row.component in _REQUIRED
}

B1Code = Literal[
    "wheelhouse_unavailable",
    "wheel_evidence_unverified",
    "installed_metadata_unavailable",
    "installed_version_mismatch",
    "entry_point_unqualified",
    "metadata_consistent_not_admitted",
]


@dataclass(frozen=True, slots=True)
class ScoreFormOfflineEvidence:
    """Static result: no executable profile, authority or private paths."""

    code: B1Code
    examined: tuple[str, ...] = _REQUIRED

    @property
    def metadata_consistent(self) -> bool:
        return self.code == "metadata_consistent_not_admitted"


def _refused(code: B1Code) -> ScoreFormOfflineEvidence:
    return ScoreFormOfflineEvidence(code=code)


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
    """Check fixed Core+ScoreForm release bytes and installed metadata.

    The exact available #16 tagged wheel specs are the sole release pins.
    This process NEVER loads the entry point, calls its factory, or reads
    teacher workspaces. A matching installed version/EP is not proof that
    the currently installed package's bytes came from the checked wheel.
    """
    if not _safe_wheelhouse(wheelhouse):
        return _refused("wheelhouse_unavailable")

    # Exact official release bytes+metadata, using existing #16 gate only.
    try:
        if set(_BY_OWNER) != set(_REQUIRED):
            return _refused("wheel_evidence_unverified")
        for component_id in _REQUIRED:
            spec = _BY_OWNER[component_id]
            evidence = wheel_inspector(wheelhouse, spec)
            if (
                not isinstance(evidence, WheelEvidence)
                or evidence.component != spec.component
                or evidence.version != spec.version
                or evidence.sha256 != spec.digest
                or evidence.status != "verified_metadata"
            ):
                return _refused("wheel_evidence_unverified")
    except Exception:
        return _refused("wheel_evidence_unverified")

    # Version metadata is read-only, not a direct executable source import.
    try:
        for component_id in _REQUIRED:
            spec = _BY_OWNER[component_id]
            if version_lookup(spec.distribution) != spec.version:
                return _refused("installed_version_mismatch")
    except metadata.PackageNotFoundError:
        return _refused("installed_version_mismatch")
    except Exception:
        return _refused("installed_metadata_unavailable")

    # Only inspect metadata for the exact published operations EP. A foreign
    # duplicate is a conflict even if one official candidate also matches.
    target_spec = _BY_OWNER["scoreform"]
    if target_spec.entry_point is None or target_spec.target is None:
        return _refused("entry_point_unqualified")
    try:
        observed = tuple(islice(entrypoint_reader(), _MAX_ENTRY_POINTS + 1))
        if len(observed) > _MAX_ENTRY_POINTS:
            return _refused("installed_metadata_unavailable")
        matching = [
            row for row in observed
            if row.group == _GROUP and row.name == target_spec.entry_point
        ]
        if len(matching) != 1:
            return _refused("entry_point_unqualified")
        candidate = matching[0]
        if (
            candidate.target != target_spec.target
            or normalize_entry_point_owner(candidate.distribution)
            != normalize_entry_point_owner(target_spec.distribution)
            or candidate.distribution_version != target_spec.version
        ):
            return _refused("entry_point_unqualified")
    except Exception:
        return _refused("installed_metadata_unavailable")

    return ScoreFormOfflineEvidence(code="metadata_consistent_not_admitted")


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
